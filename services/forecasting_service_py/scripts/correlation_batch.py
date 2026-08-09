#!/usr/bin/env python3
"""correlation_batch.py — recompute the public Cross-Asset Correlation Monitor.

Force-refreshes EOD closes for the monitored symbols, computes realized rolling
Pearson/Spearman correlations per pair per window, and upserts one
CorrelationSnapshot row per (pair, window). Serves the public /public/correlations
endpoint from precomputed rows so the request path never touches the vendor.

Run daily in prod (EventBridge -> ECS RunTask). Run once on a clean clone to seed
(needs network + valid vendor keys the first time; after that the DB cache serves).

Usage:
  python scripts/correlation_batch.py
  python scripts/correlation_batch.py --no-refresh   # use cached prices only
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime

# Ensure app package is importable
sys.path.insert(0, ".")

from sqlmodel import Session, select

from app.db.database import engine, init_db
from app.db.models import CorrelationSnapshot
from app.logic import correlation_monitor as cm
from app.services.market_store import get_price_series_cached
from app.utils.timeutil import utcnow
from app.vendors import get_vendor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _refresh_portfolio_regime(session, data_source: str) -> int:
    """Per-portfolio Regime Watch: realized equity-vs-bond correlation on real
    holdings vs the book's own baseline. Reads CACHED prices only (no force
    refresh) to stay cheap — holdings are kept fresh by the nightly universe
    refresh. Upserts one PortfolioRegimeSnapshot per portfolio (ok or honest N/A).
    """
    from app.db.models import Asset, PortfolioRegimeSnapshot, Portfolio, Position

    now = utcnow()
    written = 0
    portfolios = session.exec(select(Portfolio)).all()
    for pf in portfolios:
        positions = session.exec(
            select(Position).where(Position.portfolio_id == pf.id)
        ).all()
        if not positions:
            continue
        total_w = sum(float(p.weight or 0.0) for p in positions) or 1.0
        holdings = []
        data_map = {}
        for p in positions:
            tk = (p.ticker or "").upper()
            if not tk:
                continue
            asset = session.get(Asset, tk)
            sleeve = cm.classify_sleeve(tk, asset.asset_class if asset else None)
            holdings.append({"ticker": tk, "weight": float(p.weight or 0.0) / total_w, "sleeve": sleeve})
            if tk not in data_map:
                try:
                    rows = get_price_series_cached(tk, period="2y", force_refresh=False, session=session)
                    data_map[tk] = rows or []
                except Exception as e:  # noqa: BLE001
                    logger.error("  regime: fetch failed for %s: %s", tk, e)
                    data_map[tk] = []

        res = cm.compute_portfolio_regime(holdings, data_map)

        existing = session.exec(
            select(PortfolioRegimeSnapshot)
            .where(PortfolioRegimeSnapshot.portfolio_id == pf.id)
            .where(PortfolioRegimeSnapshot.short_window == 60)
            .where(PortfolioRegimeSnapshot.baseline_window == cm.BASELINE_WINDOW)
        ).first()
        row = existing or PortfolioRegimeSnapshot(
            portfolio_id=pf.id, short_window=60, baseline_window=cm.BASELINE_WINDOW, created_at=now,
        )
        row.status = res["status"]
        row.pair = res.get("pair", "equity_vs_bond")
        row.method = res.get("method", cm.RETURN_METHOD)
        row.data_source = data_source
        row.sleeve_weights_json = json.dumps(res.get("sleeve_weights", {}))
        row.reason = res.get("reason", "")
        row.updated_at = now
        if res["status"] == "ok":
            row.short_corr = res["short_corr"]
            row.baseline_corr = res["baseline_corr"] if res["baseline_corr"] is not None else 0.0
            row.delta = res["delta"] if res["delta"] is not None else 0.0
            row.n_obs = res["n_obs"]
            row.as_of = datetime.strptime(res["as_of"], "%Y-%m-%d")
            row.series_json = json.dumps(res["series"])
        else:
            row.short_corr = 0.0
            row.baseline_corr = 0.0
            row.delta = 0.0
            row.n_obs = 0
            row.as_of = None
            row.series_json = "[]"
        if existing is None:
            session.add(row)
        written += 1
        logger.info("  regime pf=%s: status=%s short=%.3f base=%.3f n=%d",
                    pf.id, row.status, row.short_corr, row.baseline_corr, row.n_obs)
    session.commit()
    return written


def run(force_refresh: bool = True) -> int:
    init_db()
    # Honest data-source label = the vendor actually resolved at compute time.
    try:
        data_source = get_vendor().name
    except Exception:
        data_source = "unknown"

    written = 0
    with Session(engine) as session:
        # Fetch each symbol once.
        prices = {}
        for sym in cm.symbols_needed():
            try:
                rows = get_price_series_cached(
                    sym, period="2y", force_refresh=force_refresh, session=session
                )
                prices[sym] = rows or []
                logger.info("  %s: %d price points", sym, len(prices[sym]))
            except Exception as e:  # noqa: BLE001
                logger.error("  fetch failed for %s: %s", sym, e)
                prices[sym] = []

        now = utcnow()
        for symbol_a, symbol_b, label in cm.PAIRS:
            for window in cm.WINDOWS:
                res = cm.compute_pair_window(
                    prices.get(symbol_a, []), prices.get(symbol_b, []), window
                )
                if res is None:
                    logger.warning(
                        "  %s/%s w%d: insufficient aligned history, skipping",
                        symbol_a, symbol_b, window,
                    )
                    continue

                key = cm.pair_key(symbol_a, symbol_b)
                # as_of is a calendar date -> naive, like MarketData.date.
                as_of_dt = datetime.strptime(res["as_of"], "%Y-%m-%d")
                existing = session.exec(
                    select(CorrelationSnapshot)
                    .where(CorrelationSnapshot.pair_key == key)
                    .where(CorrelationSnapshot.window_days == window)
                ).first()

                if existing:
                    existing.symbol_a = symbol_a
                    existing.symbol_b = symbol_b
                    existing.label = label
                    existing.as_of = as_of_dt
                    existing.corr_pearson = res["pearson"]
                    existing.corr_spearman = res["spearman"] if res["spearman"] is not None else 0.0
                    existing.n_obs = res["n_obs"]
                    existing.method = cm.RETURN_METHOD
                    existing.data_source = data_source
                    existing.series_json = json.dumps(res["series"])
                    existing.updated_at = now
                else:
                    session.add(CorrelationSnapshot(
                        pair_key=key,
                        symbol_a=symbol_a,
                        symbol_b=symbol_b,
                        label=label,
                        window_days=window,
                        as_of=as_of_dt,
                        corr_pearson=res["pearson"],
                        corr_spearman=res["spearman"] if res["spearman"] is not None else 0.0,
                        n_obs=res["n_obs"],
                        method=cm.RETURN_METHOD,
                        data_source=data_source,
                        series_json=json.dumps(res["series"]),
                        created_at=now,
                        updated_at=now,
                    ))
                written += 1
                logger.info(
                    "  %s w%d: pearson=%.3f spearman=%s n=%d source=%s",
                    key, window, res["pearson"], res["spearman"], res["n_obs"], data_source,
                )
        session.commit()

        # ── Portfolio Regime Watch: per-portfolio equity-vs-bond realized corr ──
        regime_written = _refresh_portfolio_regime(session, data_source)

    logger.info(
        "correlation_batch: wrote/updated %d pair snapshots + %d portfolio regime snapshots (source=%s)",
        written, regime_written, data_source,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recompute public cross-asset correlation snapshots"
    )
    parser.add_argument(
        "--no-refresh", action="store_true",
        help="Use cached prices only (no vendor fetch)",
    )
    args = parser.parse_args()

    started = time.time()
    rc = run(force_refresh=not args.no_refresh)
    logger.info("Done in %.1fs", time.time() - started)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
