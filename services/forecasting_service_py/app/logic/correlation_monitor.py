"""correlation_monitor.py — realized rolling cross-asset correlation (pure compute).

Single source of truth for the free, no-login Cross-Asset Correlation Monitor.
Everything here is a pure, deterministic function of end-of-day close series, so
the numbers on the public page regenerate exactly from a clean clone (see
scripts/correlation_batch.py). This is MEASUREMENT, not a forecast: it reports
what stock/bond and other cross-asset pairs have actually realized, versus the
diversification a 60/40-style allocation assumes.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

# ── Methodology constants (change here, nowhere else) ──────────────────────────
# Liquid ETF proxies. Close-to-close, NOT dividend-adjusted (vendor returns close
# only) — disclosed in the page methodology panel.
PAIRS: List[Tuple[str, str, str]] = [
    ("SPY", "AGG", "S&P 500 vs U.S. Aggregate Bonds"),        # the 60/40 core
    ("SPY", "TLT", "S&P 500 vs 20+ Year Treasuries"),
    ("SPY", "IEF", "S&P 500 vs 7–10 Year Treasuries"),
    ("SPY", "GLD", "S&P 500 vs Gold"),
    ("SPY", "HYG", "S&P 500 vs High-Yield Credit"),
    ("QQQ", "TLT", "Nasdaq 100 vs Long Treasuries"),
]
WINDOWS: List[int] = [30, 60, 90]           # trailing TRADING days (not calendar)
RETURN_METHOD = "simple close-to-close daily returns of liquid ETF proxies (not dividend-adjusted)"
ROLLING_HISTORY = 252                        # trailing rolling-corr points to retain (~1 trading year)
MIN_OBS = 20                                 # need at least this many aligned observations to report


def symbols_needed() -> List[str]:
    """Distinct symbols across all PAIRS, in first-seen order."""
    seen: List[str] = []
    for a, b, _label in PAIRS:
        for s in (a, b):
            if s not in seen:
                seen.append(s)
    return seen


def pair_key(symbol_a: str, symbol_b: str) -> str:
    return f"{symbol_a.upper()}_{symbol_b.upper()}"


def _price_series(rows: List[Dict]) -> pd.Series:
    """[{date:'YYYY-MM-DD', price: float}] -> float Series indexed by naive date,
    sorted, de-duplicated (last write wins on a duplicate date)."""
    if not rows:
        return pd.Series(dtype="float64")
    df = pd.DataFrame(rows)
    if "date" not in df or "price" not in df:
        return pd.Series(dtype="float64")
    df = df[["date", "price"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna(subset=["price"])
    df = df[df["price"] > 0]
    df = df.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    return df.set_index("date")["price"]


def _aligned_returns(rows_a: List[Dict], rows_b: List[Dict]) -> pd.DataFrame:
    """Inner-join two price series on common trading days, then simple daily
    returns. Inner-join first so returns are between consecutive COMMON days
    (calendar/holiday mismatches shorten the effective window — disclosed via n)."""
    a = _price_series(rows_a)
    b = _price_series(rows_b)
    if a.empty or b.empty:
        return pd.DataFrame(columns=["a", "b"])
    joined = pd.concat({"a": a, "b": b}, axis=1).dropna()
    if len(joined) < 2:
        return pd.DataFrame(columns=["a", "b"])
    return joined.pct_change().dropna()


def compute_pair_window(rows_a: List[Dict], rows_b: List[Dict], window: int) -> Optional[Dict]:
    """Realized correlation for one pair at one trailing window.

    Returns None when there is not enough aligned history to honestly report the
    window. Otherwise: headline Pearson + Spearman over the last `window`
    observations, plus a trailing rolling-Pearson series for the chart.
    """
    rets = _aligned_returns(rows_a, rows_b)
    n = len(rets)
    if n < max(int(window), MIN_OBS):
        return None

    # Rolling Pearson line (trailing ~1y of points).
    roll = rets["a"].rolling(int(window)).corr(rets["b"]).dropna()
    roll_tail = roll.tail(ROLLING_HISTORY)
    series = [
        {"date": idx.strftime("%Y-%m-%d"), "corr": round(float(v), 4)}
        for idx, v in roll_tail.items()
        if pd.notna(v)
    ]

    # Headline over the last `window` aligned observations.
    tail = rets.tail(int(window))
    pearson = tail["a"].corr(tail["b"])
    spearman = tail["a"].corr(tail["b"], method="spearman")
    if pd.isna(pearson):
        return None

    return {
        "pearson": round(float(pearson), 4),
        "spearman": round(float(spearman), 4) if pd.notna(spearman) else None,
        "n_obs": int(len(tail)),
        "as_of": rets.index[-1].strftime("%Y-%m-%d"),
        "series": series,
    }
