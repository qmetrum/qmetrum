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


# ── Portfolio-level Regime Watch (measurement, not prediction) ─────────────────
# Runs the SAME compute on an advisor's real book: classify holdings into coarse
# sleeves, build a synthetic per-sleeve price series, and measure the realized
# equity-vs-bond correlation now versus the portfolio's OWN long-run baseline.
# The "assumed" number is the book's own history — never an invented figure.

BASELINE_WINDOW = 252            # trailing trading days for the "assumed" baseline
MIN_SLEEVE_WEIGHT = 0.05         # a sleeve must carry >= this weight to count

_EQUITY_TICKERS = {
    "SPY", "VOO", "IVV", "VTI", "QQQ", "IWM", "DIA", "VEA", "VWO", "EFA", "EEM",
    "SCHD", "VUG", "VTV", "VNQ", "ARKK", "XLK", "XLF", "XLV", "XLE", "XLI", "XLP", "XLY", "XLU",
}
_BOND_TICKERS = {
    "AGG", "BND", "BNDX", "TLT", "IEF", "SHY", "LQD", "HYG", "BIL", "TIP", "MUB",
    "VCIT", "VCSH", "SHV", "GOVT",
}
_COMMODITY_TICKERS = {"GLD", "IAU", "SLV", "DBC", "USO", "PDBC", "GC=F", "SI=F", "CL=F"}


def classify_sleeve(ticker: str, asset_class: Optional[str] = None) -> str:
    """Coarse sleeve for a holding: equity | bond | commodity | crypto | other.

    Heuristic: curated tickers first, then the Asset.asset_class hint. Anything
    unclassifiable stays 'other' and is excluded from the measurement with
    disclosure — we never guess a sleeve to force a number."""
    t = (ticker or "").strip().upper()
    if t in _BOND_TICKERS:
        return "bond"
    if t in _EQUITY_TICKERS:
        return "equity"
    if t in _COMMODITY_TICKERS:
        return "commodity"
    if t.endswith("-USD"):
        return "crypto"
    ac = (asset_class or "").strip().upper()
    if ac == "BOND_ETF":
        return "bond"
    if ac == "COMMODITY":
        return "commodity"
    if ac == "CRYPTO":
        return "crypto"
    if ac in ("US_EQUITY", "INTL_INDEX", "INDEX", "ETF"):
        return "equity"
    return "other"


def _synthetic_sleeve_prices(holdings: List[Dict], data_map: Dict[str, List[Dict]]) -> List[Dict]:
    """One synthetic price series for a sleeve: within-sleeve weight-renormalized
    daily returns compounded to a price index. holdings: [{ticker, weight}]."""
    series = {}
    weights = {}
    for h in holdings:
        s = _price_series(data_map.get(h["ticker"]) or [])
        if not s.empty:
            series[h["ticker"]] = s
            weights[h["ticker"]] = float(h.get("weight", 0.0) or 0.0)
    if not series:
        return []
    df = pd.concat(series, axis=1).dropna()
    if len(df) < 2:
        return []
    rets = df.pct_change().dropna()
    total = sum(weights.values()) or 1.0
    weighted = None
    for tk in series:
        contrib = rets[tk] * (weights[tk] / total)
        weighted = contrib if weighted is None else (weighted + contrib)
    synth = (1.0 + weighted).cumprod() * 100.0
    return [{"date": idx.strftime("%Y-%m-%d"), "price": float(v)} for idx, v in synth.items()]


def compute_portfolio_regime(
    holdings: List[Dict],
    data_map: Dict[str, List[Dict]],
    short_window: int = 60,
    baseline_window: int = BASELINE_WINDOW,
    min_sleeve_weight: float = MIN_SLEEVE_WEIGHT,
) -> Dict:
    """Realized equity-vs-bond correlation on a portfolio's real sleeves, versus
    the portfolio's OWN long-run baseline. holdings: [{ticker, weight, sleeve}].

    Returns an 'ok' dict or an honest 'na' status (with a reason) — never a
    guessed number when the book can't support the measurement."""
    from collections import defaultdict

    by_sleeve: Dict[str, List[Dict]] = defaultdict(list)
    sleeve_w: Dict[str, float] = defaultdict(float)
    for h in holdings:
        sl = h.get("sleeve") or "other"
        by_sleeve[sl].append(h)
        sleeve_w[sl] += float(h.get("weight", 0.0) or 0.0)
    sleeve_weights = {k: round(v, 4) for k, v in sleeve_w.items()}

    if sleeve_w.get("equity", 0.0) < min_sleeve_weight or sleeve_w.get("bond", 0.0) < min_sleeve_weight:
        return {
            "status": "na",
            "reason": "Needs both an equity and a bond sleeve above the weight floor to measure diversification.",
            "sleeve_weights": sleeve_weights,
        }

    eq = _synthetic_sleeve_prices(by_sleeve["equity"], data_map)
    bd = _synthetic_sleeve_prices(by_sleeve["bond"], data_map)
    short = compute_pair_window(eq, bd, short_window)
    if short is None:
        return {
            "status": "na",
            "reason": "Insufficient aligned price history to measure correlation.",
            "sleeve_weights": sleeve_weights,
        }

    base = compute_pair_window(eq, bd, baseline_window)
    baseline_corr = base["pearson"] if base else None
    delta = round(short["pearson"] - baseline_corr, 4) if baseline_corr is not None else None
    return {
        "status": "ok",
        "pair": "equity_vs_bond",
        "short_window": short_window,
        "baseline_window": baseline_window,
        "short_corr": short["pearson"],
        "baseline_corr": baseline_corr,   # the book's own long-run realized corr
        "delta": delta,
        "n_obs": short["n_obs"],
        "as_of": short["as_of"],
        "series": short["series"],
        "sleeve_weights": sleeve_weights,
        "method": RETURN_METHOD,
    }
