"""As-of replay harness: turn Qsight's risk models into a backtestable
predicted-VaR series, then score it with app.logic.var_backtest.

No stored historical VaR vector exists, so we *replay* the model: at each
historical as-of date we refit on prices strictly before that date, predict
the h-day VaR 95, and line it up against the subsequently-realized portfolio
return. This is look-ahead-free by construction — every fit sees only past
data — which is what makes the resulting Kupiec / Christoffersen coverage
tests meaningful.

Methods:
  - "mps_fan"    : refit the MPS-copula joint-return sampler each day and take
                   the 5th percentile of the simulated portfolio return.
  - "historical" : empirical 5th percentile of the trailing portfolio returns
                   (a cheap, fat-tailed cross-check — the natural baseline for
                   "which model actually passes VaR 95").

Caveats encoded here:
  - Position weights are current-only (no history), so today's weights are
    applied across the whole window (standard but lossy — documented).
  - horizon_days > 1 uses overlapping forward windows; the coverage tests
    assume independence, so ``overlapping_windows`` is flagged in the result.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.logic.tensor_network_risk import sample_standardised_joint_returns
from app.logic.var_backtest import extract_var_from_paths, run_var_backtest
from app.services.market_store import get_price_series_cached

logger = logging.getLogger(__name__)

MIN_BACKTEST_OBS = 30          # below this the coverage tests are meaningless
MIN_TRAILING_FOR_HIST = 30     # min trailing returns for a historical VaR


def _fetch_data_map(tickers: List[str], period: str = "5y") -> Dict[str, pd.DataFrame]:
    """Per-ticker price history as date-indexed frames (mirrors
    PortfolioManager._fetch_batch_data but with a configurable, longer period
    so the backtest window has enough history)."""
    data_map: Dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            raw = get_price_series_cached(t, period=period)
        except Exception as e:  # pragma: no cover - network/vendor failure
            logger.warning("var_backtest: price fetch failed for %s: %s", t, e)
            continue
        df = pd.DataFrame(raw)
        if df.empty or "date" not in df.columns or "price" not in df.columns:
            continue
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        data_map[t] = df
    return data_map


def _portfolio_returns(data_map: Dict[str, pd.DataFrame],
                       weights: Dict[str, float]) -> pd.Series:
    """Weighted daily portfolio return over the common (intersected) date index."""
    common: Optional[pd.Index] = None
    for df in data_map.values():
        common = df.index if common is None else common.intersection(df.index)
    if common is None or len(common) == 0:
        return pd.Series(dtype=float)
    total_w = sum(weights.get(t, 0.0) for t in data_map) or 1.0
    port = pd.Series(0.0, index=common)
    for t, df in data_map.items():
        w = weights.get(t, 0.0) / total_w
        ret = df.loc[common, "price"].pct_change().fillna(0.0)
        port = port + ret * w
    return port.sort_index()


def _predict_var_mps(
    data_map_trunc: Dict[str, pd.DataFrame],
    tickers_order: List[str],
    weights: Dict[str, float],
    horizon_days: int,
    confidence: float,
    n_sims: int,
    d: int,
    chi: int,
    seed: Optional[int],
) -> float:
    """One as-of MPS-copula VaR (signed simple return). Mirrors the marginal
    reconstruction in portfolio_logic._fan_from_mps with scale=1, drift=0."""
    sample = sample_standardised_joint_returns(
        data_map=data_map_trunc,
        tickers_order=tickers_order,
        n_steps=horizon_days,
        n_simulations=n_sims,
        d=d,
        chi=chi,
        random_seed=seed,
    )
    z = sample["z_samples"]              # (T, S, N)
    mu = sample["asset_mu"]
    sd = sample["asset_sigma"]
    kept = sample["tickers"]
    w = np.array([weights.get(t, 0.0) for t in kept], dtype=float)
    if w.sum() <= 0:
        raise ValueError("no positive weight among kept tickers")
    w = w / w.sum()
    r = mu + sd * z                              # (T, S, N) log returns
    port_r = np.einsum("tsn,n->ts", r, w)        # (T, S)
    paths = np.exp(np.cumsum(port_r, axis=0))    # (T, S), base 1.0
    var = extract_var_from_paths(paths, base=1.0, confidence=confidence)
    return float(var[-1])  # cumulative VaR to the horizon end (1-day when h=1)


def _predict_var_historical(trailing_returns: np.ndarray, confidence: float,
                            horizon_days: int) -> float:
    """Empirical VaR from the trailing 1-day return percentile, sqrt-time
    scaled for multi-day horizons."""
    q = (1.0 - confidence) * 100.0
    var_1d = float(np.percentile(trailing_returns, q))
    return var_1d * float(np.sqrt(horizon_days)) if horizon_days > 1 else var_1d


def run_portfolio_var_backtest(
    *,
    assets: List[dict],
    confidence: float = 0.95,
    horizon_days: int = 1,
    est_window: int = 252,
    n_backtest: int = 250,
    method: str = "mps_fan",
    n_simulations: int = 500,
    physical_dim: int = 4,
    bond_dim: int = 8,
    random_seed: Optional[int] = 42,
    alpha: float = 0.05,
    period: str = "5y",
) -> Dict[str, Any]:
    """Replay-backtest a portfolio's VaR and score it with the coverage tests.

    ``assets`` is ``[{"ticker": ..., "weight": ...}, ...]``. Returns the
    ``run_var_backtest`` dict augmented with method, params, and data window.
    """
    if method not in ("mps_fan", "historical"):
        raise ValueError(f"unknown method: {method}")
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")

    weights = {str(a["ticker"]): float(a.get("weight", 0.0) or 0.0) for a in assets}
    tickers = list(weights.keys())
    data_map = _fetch_data_map(tickers, period=period)
    if not data_map:
        raise ValueError("no price history for any portfolio ticker")
    if method == "mps_fan" and len(data_map) < 2:
        raise ValueError("mps_fan backtest needs >= 2 assets with price history")

    port_ret = _portfolio_returns(data_map, weights)
    if port_ret.empty:
        raise ValueError("no overlapping price history across tickers")

    dates = port_ret.index
    n = len(port_ret)
    min_needed = est_window + horizon_days
    if n < min_needed + MIN_BACKTEST_OBS:
        raise ValueError(
            f"insufficient history: have {n} return obs, need >= {min_needed + MIN_BACKTEST_OBS} "
            f"(est_window={est_window} + horizon={horizon_days} + {MIN_BACKTEST_OBS} test days)"
        )

    start_i = max(est_window, n - n_backtest)
    realized: List[float] = []
    predicted: List[float] = []
    used_dates: List[str] = []
    skipped = 0

    for i in range(start_i, n - (horizon_days - 1)):
        d_date = dates[i]
        fwd = port_ret.iloc[i:i + horizon_days]
        realized_ret = float((1.0 + fwd).prod() - 1.0)

        try:
            if method == "mps_fan":
                trunc = {
                    t: df[df.index < d_date].tail(est_window + 5)
                    for t, df in data_map.items()
                }
                var = _predict_var_mps(
                    trunc, tickers, weights, horizon_days, confidence,
                    n_simulations, physical_dim, bond_dim, random_seed,
                )
            else:  # historical
                trailing = port_ret.iloc[max(0, i - est_window):i].to_numpy()
                if len(trailing) < MIN_TRAILING_FOR_HIST:
                    skipped += 1
                    continue
                var = _predict_var_historical(trailing, confidence, horizon_days)
        except Exception as e:
            logger.warning("var_backtest %s predict failed at %s: %s",
                           method, d_date.date(), e)
            skipped += 1
            continue

        realized.append(realized_ret)
        predicted.append(var)
        used_dates.append(str(d_date.date()))

    if len(realized) < MIN_BACKTEST_OBS:
        raise ValueError(
            f"too few backtest observations ({len(realized)}); widen the window or add history"
        )

    result = run_var_backtest(
        realized, predicted, confidence=confidence, alpha=alpha, dates=used_dates
    )
    result["method"] = method
    result["horizon_days"] = horizon_days
    result["overlapping_windows"] = bool(horizon_days > 1)
    result["skipped_days"] = skipped
    result["params"] = {
        "est_window": est_window,
        "n_backtest": n_backtest,
        "n_simulations": n_simulations,
        "physical_dim": physical_dim,
        "bond_dim": bond_dim,
        "random_seed": random_seed,
        "period": period,
        "tickers": list(data_map.keys()),
        "weights_note": "current position weights applied across the whole window (no weight history)",
    }
    result["data_window"] = {
        "start": str(dates[0].date()),
        "end": str(dates[-1].date()),
        "n_return_obs": n,
    }
    return result
