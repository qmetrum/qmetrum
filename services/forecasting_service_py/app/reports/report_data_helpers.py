"""
report_data_helpers.py — Centralized functions replacing all np.random data in reports.

Every function here returns real data computed from MarketData / AssetVolatilitySnapshot
tables. If data is unavailable, functions return sensible fallbacks (zeros, empty lists)
rather than random noise.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlmodel import Session, select

from app.db.models import (
    AssetReturn,
    AssetVolatilitySnapshot,
    BenchmarkReturn,
    MarketData,
)

logger = logging.getLogger(__name__)

# Default benchmark for S&P 500
DEFAULT_BENCHMARK = "^GSPC"
FALLBACK_BENCHMARKS = ["SPY", "VOO"]


# ──────────────────────────────────────────────────────────────
# Benchmark series
# ──────────────────────────────────────────────────────────────

def get_benchmark_series(
    symbol: str,
    start: datetime,
    end: datetime,
    session: Session,
) -> pd.DataFrame:
    """
    Fetch daily close prices for a benchmark from MarketData.
    Returns DataFrame with columns ['date', 'close'] sorted by date.
    Falls back to alternative benchmark symbols if primary has no data.
    """
    candidates = [symbol] + [s for s in FALLBACK_BENCHMARKS if s != symbol]

    for candidate in candidates:
        rows = session.exec(
            select(MarketData)
            .where(MarketData.symbol == candidate)
            .where(MarketData.date >= start)
            .where(MarketData.date <= end)
            .order_by(MarketData.date.asc())
        ).all()
        if rows:
            df = pd.DataFrame([{"date": r.date, "close": r.close} for r in rows])
            df["date"] = pd.to_datetime(df["date"])
            return df

    # No data found — return empty DataFrame
    return pd.DataFrame(columns=["date", "close"])


def get_benchmark_returns(
    symbol: str,
    start: datetime,
    end: datetime,
    session: Session,
    period: str = "daily",
) -> pd.DataFrame:
    """
    Fetch pre-computed benchmark returns from BenchmarkReturn table.
    Returns DataFrame with columns ['date', 'return_pct', 'cumulative_return'].
    """
    rows = session.exec(
        select(BenchmarkReturn)
        .where(BenchmarkReturn.benchmark_symbol == symbol)
        .where(BenchmarkReturn.period == period)
        .where(BenchmarkReturn.date >= start)
        .where(BenchmarkReturn.date <= end)
        .order_by(BenchmarkReturn.date.asc())
    ).all()

    if rows:
        return pd.DataFrame([
            {"date": r.date, "return_pct": r.return_pct, "cumulative_return": r.cumulative_return}
            for r in rows
        ])

    # Fallback: compute from MarketData on-the-fly
    bench_df = get_benchmark_series(symbol, start, end, session)
    if bench_df.empty:
        return pd.DataFrame(columns=["date", "return_pct", "cumulative_return"])

    bench_df = bench_df.sort_values("date").reset_index(drop=True)
    bench_df["return_pct"] = bench_df["close"].pct_change().fillna(0.0)
    bench_df["cumulative_return"] = (1 + bench_df["return_pct"]).cumprod() - 1
    return bench_df[["date", "return_pct", "cumulative_return"]]


# ──────────────────────────────────────────────────────────────
# Monthly returns
# ──────────────────────────────────────────────────────────────

def compute_monthly_returns(daily_prices: pd.Series, year: int) -> np.ndarray:
    """
    Compute 12 monthly returns from a daily price series for a given year.
    daily_prices: pd.Series indexed by datetime with close prices.
    Returns np.ndarray of length 12 (one return per month, 0.0 if data missing).
    """
    monthly = np.zeros(12)
    for month in range(1, 13):
        mask = (daily_prices.index.year == year) & (daily_prices.index.month == month)
        month_prices = daily_prices[mask]
        if len(month_prices) >= 2:
            monthly[month - 1] = (month_prices.iloc[-1] / month_prices.iloc[0]) - 1
    return monthly


def compute_monthly_benchmark_returns(
    benchmark_symbol: str,
    year: int,
    session: Session,
) -> np.ndarray:
    """
    Compute 12 monthly returns for a benchmark.
    """
    start = datetime(year, 1, 1)
    end = datetime(year, 12, 31)
    bench_df = get_benchmark_series(benchmark_symbol, start, end, session)

    if bench_df.empty:
        return np.zeros(12)

    bench_df = bench_df.set_index("date").sort_index()
    return compute_monthly_returns(bench_df["close"], year)


# ──────────────────────────────────────────────────────────────
# Asset contributions
# ──────────────────────────────────────────────────────────────

def compute_asset_contributions(
    price_data: Dict[str, pd.DataFrame],
    weights: Dict[str, float],
    start: datetime,
    end: datetime,
) -> List[Dict]:
    """
    Compute actual return and weighted contribution for each asset over [start, end].
    price_data: {ticker: DataFrame with 'date' and 'price' columns}
    Returns list of dicts: [{"ticker", "return", "contribution"}, ...]
    """
    results = []
    for ticker, df in price_data.items():
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        mask = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
        period_df = df[mask].sort_values("date")

        if len(period_df) >= 2:
            asset_return = (period_df["price"].iloc[-1] / period_df["price"].iloc[0]) - 1
        else:
            asset_return = 0.0

        weight = weights.get(ticker, 0.0)
        results.append({
            "ticker": ticker,
            "return": float(asset_return),
            "contribution": float(asset_return * weight),
        })

    # Sort by contribution descending
    results.sort(key=lambda x: x["contribution"], reverse=True)
    return results


# ──────────────────────────────────────────────────────────────
# Volatility
# ──────────────────────────────────────────────────────────────

def compute_monthly_vol(daily_prices: pd.Series, year: int) -> List[float]:
    """
    Compute monthly realized volatility from daily prices for a given year.
    Uses rolling 21-day realized vol, resampled to monthly.
    Returns list of 12 floats (annualized vol % per month).
    """
    monthly_vols = []
    returns = daily_prices.pct_change().dropna()

    for month in range(1, 13):
        mask = (returns.index.year == year) & (returns.index.month == month)
        month_returns = returns[mask]
        if len(month_returns) >= 5:
            vol = float(month_returns.std() * np.sqrt(252) * 100)
        else:
            vol = 0.0
        monthly_vols.append(vol)

    return monthly_vols


def compute_monthly_fragility(
    session: Session,
    tickers: List[str],
    weights: Dict[str, float],
    year: int,
) -> List[float]:
    """
    Compute monthly portfolio-weighted fragility from AssetVolatilitySnapshot.
    Returns list of 12 floats.
    """
    monthly_fragility = []

    for month in range(1, 13):
        month_start = datetime(year, month, 1)
        if month == 12:
            month_end = datetime(year + 1, 1, 1)
        else:
            month_end = datetime(year, month + 1, 1)

        weighted_fragility = 0.0
        total_weight = 0.0

        for ticker in tickers:
            weight = weights.get(ticker, 0.0)
            if weight <= 0:
                continue

            snapshot = session.exec(
                select(AssetVolatilitySnapshot)
                .where(AssetVolatilitySnapshot.symbol == ticker)
                .where(AssetVolatilitySnapshot.as_of >= month_start)
                .where(AssetVolatilitySnapshot.as_of < month_end)
                .order_by(AssetVolatilitySnapshot.as_of.desc())
            ).first()

            if snapshot and snapshot.fragility_score_latest is not None:
                weighted_fragility += snapshot.fragility_score_latest * weight
                total_weight += weight

        if total_weight > 0:
            monthly_fragility.append(weighted_fragility / total_weight)
        else:
            monthly_fragility.append(1.0)  # neutral default

    return monthly_fragility


# ──────────────────────────────────────────────────────────────
# Portfolio beta
# ──────────────────────────────────────────────────────────────

def compute_portfolio_beta(
    port_returns: pd.Series,
    bench_returns: pd.Series,
) -> float:
    """
    Compute portfolio beta as cov(portfolio, benchmark) / var(benchmark).
    Both inputs should be daily return series aligned on the same dates.
    """
    # Align the two series on common dates
    combined = pd.DataFrame({"port": port_returns, "bench": bench_returns}).dropna()

    if len(combined) < 30:
        return 1.0  # not enough data, assume market beta

    cov = combined["port"].cov(combined["bench"])
    var = combined["bench"].var()

    if var == 0:
        return 1.0

    return float(cov / var)


# ──────────────────────────────────────────────────────────────
# Benchmark index series (for event reports)
# ──────────────────────────────────────────────────────────────

def get_benchmark_index_series(
    symbol: str,
    start: datetime,
    end: datetime,
    session: Session,
    base: float = 100.0,
) -> Tuple[np.ndarray, List[datetime]]:
    """
    Fetch benchmark prices and return as indexed series (base=100).
    Returns (index_values, dates).
    """
    bench_df = get_benchmark_series(symbol, start, end, session)
    if bench_df.empty:
        return np.array([base]), [start]

    bench_df = bench_df.sort_values("date").reset_index(drop=True)
    prices = bench_df["close"].values
    index_values = (prices / prices[0]) * base
    dates = bench_df["date"].tolist()
    return index_values, dates


# ──────────────────────────────────────────────────────────────
# Portfolio daily price series from DB
# ──────────────────────────────────────────────────────────────

def build_portfolio_daily_prices(
    tickers: List[str],
    weights: Dict[str, float],
    start: datetime,
    end: datetime,
    session: Session,
) -> Tuple[pd.Series, pd.DatetimeIndex]:
    """
    Build a synthetic daily portfolio price series from MarketData.
    Returns (prices indexed to 100, DatetimeIndex of dates).
    """
    all_series = {}
    for ticker in tickers:
        rows = session.exec(
            select(MarketData)
            .where(MarketData.symbol == ticker)
            .where(MarketData.date >= start)
            .where(MarketData.date <= end)
            .order_by(MarketData.date.asc())
        ).all()
        if rows:
            s = pd.Series(
                [r.close for r in rows],
                index=pd.DatetimeIndex([r.date for r in rows]),
                name=ticker,
            )
            all_series[ticker] = s

    if not all_series:
        idx = pd.DatetimeIndex([start])
        return pd.Series([100.0], index=idx), idx

    # Union of all dates, forward-fill
    all_dates = sorted(set().union(*[set(s.index) for s in all_series.values()]))
    date_idx = pd.DatetimeIndex(all_dates)

    port_returns = pd.Series(0.0, index=date_idx)
    for ticker, s in all_series.items():
        aligned = s.reindex(date_idx, method="ffill")
        ret = aligned.pct_change().fillna(0)
        port_returns += ret * weights.get(ticker, 0)

    port_prices = (1 + port_returns).cumprod() * 100
    return port_prices, date_idx
