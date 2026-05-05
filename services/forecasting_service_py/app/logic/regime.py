"""Per-asset-class regime threshold lookup.

Maps a ticker (+ its asset_type/sector) to a class label, looks up the
latest active threshold row from the `regimethreshold` table, and combines
per-holding thresholds into one portfolio-level (high, low) pair by
weight-averaging.

On first read with an empty table, seeds default rows from
`app/data/regime_thresholds.json` so a fresh deploy works without manual
setup.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, select

from app.db.database import engine
from app.db.models import RegimeThreshold


log = logging.getLogger(__name__)

_DEFAULT_HIGH = 1.50
_DEFAULT_LOW = 0.80

_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "regime_thresholds.json"

_cache_lock = threading.Lock()
_cache: Optional[dict[str, dict[str, float]]] = None
_seeded = False

# Sector buckets used for further sub-classification of equity/ETF holdings.
_BROAD_ETF_TICKERS = {
    "SPY", "VOO", "VTI", "IVV", "QQQ", "DIA", "IWM", "RSP",
    "EFA", "EEM", "ACWI", "VEA", "VWO", "IEFA", "IEMG", "VT",
}
_TREASURY_ETF_TICKERS = {"TLT", "IEF", "SHY", "GOVT", "BIL", "TIP", "VGIT", "VGSH"}
_CREDIT_ETF_TICKERS = {"LQD", "HYG", "JNK", "AGG", "BND", "BNDX", "VCIT", "VCSH"}
_COMMODITY_TICKERS = {"GLD", "SLV", "USO", "UNG", "DBC", "GSG", "PALL", "PPLT", "DBA"}
_INTL_HINTS = ("EFA", "EEM", "ACWI", "VEA", "VWO", "VXUS", "EWJ", "EWG", "EWU", "FXI")


def _seed_from_json_if_empty(session: Session) -> None:
    """If the table is empty, populate it from the bundled JSON seed file."""
    global _seeded
    if _seeded:
        return
    existing = session.exec(select(RegimeThreshold).limit(1)).first()
    if existing is not None:
        _seeded = True
        return

    if not _SEED_PATH.exists():
        log.warning("regime: seed JSON not found at %s, skipping seed", _SEED_PATH)
        _seeded = True
        return

    try:
        with _SEED_PATH.open("r") as f:
            blob = json.load(f)
    except Exception as exc:
        log.warning("regime: failed to read seed JSON (%s)", exc)
        _seeded = True
        return

    classes = blob.get("classes") or {}
    now = datetime.utcnow()
    inserted = 0
    for cls, vals in classes.items():
        if not isinstance(vals, dict):
            continue
        try:
            high = float(vals.get("high", _DEFAULT_HIGH))
            low = float(vals.get("low", _DEFAULT_LOW))
        except (TypeError, ValueError):
            continue
        session.add(
            RegimeThreshold(
                asset_class=cls,
                high=high,
                low=low,
                is_active=True,
                source=str(blob.get("_source") or "default-seed"),
                years_of_history=blob.get("_years_of_history"),
                calibrated_at=now,
                created_at=now,
            )
        )
        inserted += 1
    if inserted > 0:
        session.commit()
        log.info("regime: seeded %d default thresholds from %s", inserted, _SEED_PATH.name)
    _seeded = True


def _load_thresholds() -> dict[str, dict[str, float]]:
    """Return the latest active threshold per asset class, cached.

    Cache is process-local. Call `invalidate_cache()` after a calibration job
    inserts new rows to pick them up without restart.
    """
    global _cache
    if _cache is not None:
        return _cache

    with _cache_lock:
        if _cache is not None:
            return _cache

        out: dict[str, dict[str, float]] = {}
        try:
            with Session(engine) as session:
                _seed_from_json_if_empty(session)
                rows = session.exec(
                    select(RegimeThreshold)
                    .where(RegimeThreshold.is_active == True)  # noqa: E712
                    .order_by(RegimeThreshold.calibrated_at.desc())
                ).all()
                # Latest active row per class (rows are in desc order, so first wins)
                for r in rows:
                    if r.asset_class not in out:
                        out[r.asset_class] = {"high": float(r.high), "low": float(r.low)}
        except Exception as exc:
            log.warning("regime: DB lookup failed (%s) — falling back to default", exc)

        if "default" not in out:
            out["default"] = {"high": _DEFAULT_HIGH, "low": _DEFAULT_LOW}

        _cache = out
    return _cache


def invalidate_cache() -> None:
    """Drop the in-process threshold cache. Call after a calibration job."""
    global _cache
    with _cache_lock:
        _cache = None


def classify_ticker(ticker: str, fundamentals: Optional[dict[str, Any]] = None) -> str:
    """Map a ticker to one of the regime asset classes."""
    t = (ticker or "").upper()
    fund = fundamentals or {}
    asset_type = str(fund.get("type", "")).upper()
    profile = fund.get("profile") if isinstance(fund.get("profile"), dict) else {}
    sector = (profile.get("sector") or "") if isinstance(profile, dict) else ""
    sector = str(sector or "").strip()

    if asset_type == "CRYPTO" or t.endswith("-USD") or t.endswith("USDT"):
        return "crypto"

    if asset_type == "BOND":
        return "bond_treasury"
    if t in _TREASURY_ETF_TICKERS:
        return "bond_treasury"
    if t in _CREDIT_ETF_TICKERS:
        return "bond_credit"

    if t in _COMMODITY_TICKERS:
        return "commodity"

    if asset_type == "ETF" or (asset_type == "" and t in _BROAD_ETF_TICKERS):
        if t in _BROAD_ETF_TICKERS:
            return "etf_broad"
        if any(t.startswith(p) or t == p for p in _INTL_HINTS):
            return "etf_broad"
        if t.startswith("XL") or sector or asset_type == "ETF":
            return "etf_sector"
        return "etf_broad"

    if asset_type == "FUTURE":
        return "commodity"

    if t.endswith(".L") or t.endswith(".T") or t.endswith(".HK") or t.endswith(".PA"):
        return "equity_intl"

    return "equity_us"


def thresholds_for_class(asset_class: str) -> tuple[float, float]:
    table = _load_thresholds()
    entry = table.get(asset_class) or table.get("default") or {"high": _DEFAULT_HIGH, "low": _DEFAULT_LOW}
    return float(entry["high"]), float(entry["low"])


def portfolio_thresholds(
    holdings: list[dict[str, Any]],
    fundamentals_map: Optional[dict[str, dict[str, Any]]] = None,
) -> tuple[float, float, dict[str, float]]:
    """Weight-averaged (high, low) thresholds for a portfolio + class breakdown."""
    fund_map = fundamentals_map or {}
    if not holdings:
        return _DEFAULT_HIGH, _DEFAULT_LOW, {}

    total_w = 0.0
    weighted_high = 0.0
    weighted_low = 0.0
    class_weights: dict[str, float] = {}

    for h in holdings:
        try:
            w = float(h.get("weight") or 0.0)
        except (TypeError, ValueError):
            w = 0.0
        if w <= 0:
            continue
        ticker = str(h.get("ticker") or "").upper()
        cls = classify_ticker(ticker, fund_map.get(ticker) or fund_map.get(ticker.lower()))
        high, low = thresholds_for_class(cls)
        weighted_high += w * high
        weighted_low += w * low
        total_w += w
        class_weights[cls] = class_weights.get(cls, 0.0) + w

    if total_w <= 0:
        return _DEFAULT_HIGH, _DEFAULT_LOW, {}
    return (
        weighted_high / total_w,
        weighted_low / total_w,
        {cls: round(wt / total_w, 4) for cls, wt in class_weights.items()},
    )
