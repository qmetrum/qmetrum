#!/usr/bin/env python3
"""Calibrate per-asset-class regime thresholds from historical price data.

For each class we download a representative basket of tickers, compute the
daily vol_21d/vol_126d ratio time series, pool the results within the class,
and store the 10th / 90th percentiles as the Low_Vol / High_Vol thresholds.

Inserts a fresh active row per class into the `regimethreshold` table and
deactivates the previous active row for the same class. Run regularly (e.g.
monthly cron) — runtime picks up the new values via cache invalidation.

Usage:
    python scripts/calibrate_regime_thresholds.py
    python scripts/calibrate_regime_thresholds.py --years 7
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import yfinance as yf
from sqlmodel import Session, select


REPO_ROOT = Path(__file__).resolve().parent.parent


# Representative baskets per class. Curated, not exhaustive — change to taste.
BASKETS: Dict[str, List[str]] = {
    "equity_us": [
        "AAPL", "MSFT", "JPM", "JNJ", "PG", "WMT", "XOM", "V", "MA", "HD",
        "KO", "PEP", "UNH", "DIS", "MRK", "BAC", "CSCO", "INTC", "VZ", "T",
    ],
    "equity_intl": [
        "EFA", "VEA", "VWO", "IEMG", "IEFA", "ACWX", "EWJ", "EWG", "EWU", "FXI",
    ],
    "etf_broad": [
        "SPY", "VOO", "VTI", "QQQ", "DIA", "IWM", "RSP", "ACWI", "VT", "IVV",
    ],
    "etf_sector": [
        "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "XLU", "XLRE", "XLB", "XLC",
    ],
    "bond_treasury": [
        "TLT", "IEF", "SHY", "GOVT", "VGIT", "VGSH", "TIP",
    ],
    "bond_credit": [
        "LQD", "HYG", "JNK", "AGG", "BND", "VCIT", "VCSH",
    ],
    "crypto": [
        "BTC-USD", "ETH-USD",
    ],
    "commodity": [
        "GLD", "SLV", "USO", "UNG", "DBC", "PALL", "DBA",
    ],
}


def compute_ratios(prices: pd.Series, recent: int = 21, long: int = 126) -> pd.Series:
    """Daily vol(recent)/vol(long) ratio. Drops the warmup period."""
    rets = np.log(prices / prices.shift(1)).dropna()
    rolling_recent = rets.rolling(window=recent).std()
    rolling_long = rets.rolling(window=long).std()
    ratio = (rolling_recent / rolling_long).replace([np.inf, -np.inf], np.nan).dropna()
    return ratio


def calibrate(years: int = 5) -> dict:
    end = datetime.now(timezone.utc)
    start = end.replace(year=end.year - years)
    classes_out: dict[str, dict[str, float]] = {}

    for cls, tickers in BASKETS.items():
        all_ratios: list[float] = []
        n_with_data = 0
        for ticker in tickers:
            try:
                df = yf.download(
                    ticker,
                    start=start.strftime("%Y-%m-%d"),
                    end=end.strftime("%Y-%m-%d"),
                    progress=False,
                    auto_adjust=True,
                )
                if df is None or df.empty:
                    print(f"  [{cls}] {ticker}: no data, skipping")
                    continue
                # yfinance v0.2+ may return a multi-index column df
                if isinstance(df.columns, pd.MultiIndex):
                    if ("Close", ticker) in df.columns:
                        prices = df[("Close", ticker)].dropna()
                    else:
                        prices = df["Close"].iloc[:, 0].dropna()
                else:
                    prices = df["Close"].dropna()
                if len(prices) < 200:
                    print(f"  [{cls}] {ticker}: only {len(prices)} bars, skipping")
                    continue
                ratios = compute_ratios(prices)
                if not ratios.empty:
                    all_ratios.extend(ratios.tolist())
                    n_with_data += 1
            except Exception as exc:
                print(f"  [{cls}] {ticker}: error {exc}, skipping")

        if not all_ratios:
            print(f"  [{cls}] WARN: no usable data, leaving previous threshold (or default)")
            continue

        arr = np.asarray(all_ratios, dtype=float)
        low = float(np.percentile(arr, 10))
        high = float(np.percentile(arr, 90))
        classes_out[cls] = {"high": round(high, 3), "low": round(low, 3)}
        print(
            f"  [{cls}] n={n_with_data} tickers, {len(arr)} ratios → "
            f"low={low:.3f}, high={high:.3f}"
        )

    # Always include a default fallback
    classes_out.setdefault("default", {"high": 1.50, "low": 0.80})
    return classes_out


def write_to_db(classes: dict, years: int) -> int:
    """Insert new active rows, deactivate previous active rows for the same class."""
    # Late imports so `--help` works without installed deps / DB
    sys.path.insert(0, str(REPO_ROOT))
    from app.db.database import engine  # noqa: WPS433
    from app.db.models import RegimeThreshold  # noqa: WPS433
    from app.logic.regime import invalidate_cache  # noqa: WPS433

    inserted = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(engine) as session:
        for cls, vals in classes.items():
            # Deactivate the prior active row(s) for this class
            prior = session.exec(
                select(RegimeThreshold)
                .where(RegimeThreshold.asset_class == cls)
                .where(RegimeThreshold.is_active == True)  # noqa: E712
            ).all()
            for row in prior:
                row.is_active = False
                session.add(row)

            session.add(
                RegimeThreshold(
                    asset_class=cls,
                    high=float(vals["high"]),
                    low=float(vals["low"]),
                    is_active=True,
                    source="scripts/calibrate_regime_thresholds.py",
                    years_of_history=years,
                    calibrated_at=now,
                    created_at=now,
                )
            )
            inserted += 1
        session.commit()
    invalidate_cache()
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=5, help="Years of history (default 5)")
    args = parser.parse_args()

    print(f"Calibrating regime thresholds from {args.years}y of yfinance data…")
    classes = calibrate(years=args.years)
    if not classes:
        print("No usable data computed — leaving DB unchanged.")
        return 1

    inserted = write_to_db(classes, years=args.years)
    print(f"Inserted {inserted} active threshold row(s) into regimethreshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
