"""Drawdown-managed allocation: suggested portfolio weights from several
risk-based methods, each shown with its HONEST backtested profile.

Methods
  - equal          : 1/N.
  - inverse_vol    : weight proportional to 1 / trailing volatility.
  - risk_parity    : equal-risk-contribution (cyclical coordinate descent).
  - drawdown_mgd   : the CDaR-based sizing -- weight proportional to
                     1 / CDaR_depth, scaled by a regime x vol-of-vol multiplier
                     and a modest recovery tilt.

Honesty (established by the offline sweep across 33 survivorship-free baskets,
see scripts/sweep_cdar.py): the drawdown-managed method does NOT beat inverse-
vol / risk-parity on risk-adjusted return; it robustly delivers a LOWER max
drawdown, at the cost of a slightly lower Sharpe and higher turnover. The
profile returned here makes that tradeoff visible so the choice is informed --
this is a risk-preference tool, not an alpha claim, and there is nothing
"quantum" about it (it is classical convex sizing).

Everything is point-in-time: suggested weights use only the trailing window,
and the profile is a walk-forward backtest net of turnover costs.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

TRADING_DAYS = 252

METHOD_META = {
    "equal": {
        "label": "Equal weight",
        "note": "Naive 1/N baseline. No risk adjustment.",
    },
    "inverse_vol": {
        "label": "Inverse volatility",
        "note": "Down-weights volatile holdings. Strong, low-turnover risk-adjusted baseline.",
    },
    "risk_parity": {
        "label": "Risk parity",
        "note": "Equalizes each holding's contribution to portfolio risk.",
    },
    "drawdown_mgd": {
        "label": "Drawdown-managed (CDaR)",
        "note": ("Sizes by conditional drawdown and a vol/regime tilt. Historically "
                 "delivers LOWER max drawdown, but a slightly lower Sharpe and higher "
                 "turnover than inverse-vol. A drawdown-control preference, not higher return."),
    },
}
DEFAULT_METHODS = ["equal", "inverse_vol", "risk_parity", "drawdown_mgd"]


# ------------------------------ risk primitives --------------------------- #
def drawdown_series(prices: np.ndarray) -> np.ndarray:
    prices = np.asarray(prices, dtype=float)
    peak = np.maximum.accumulate(prices)
    return 1.0 - prices / peak


def empirical_cdar(prices: np.ndarray, alpha: float = 0.95) -> float:
    dd = drawdown_series(prices)
    if dd.size == 0:
        return 1e-4
    q = np.quantile(dd, alpha)
    tail = dd[dd >= q]
    val = float(tail.mean()) if tail.size else float(dd.max())
    return max(val, 1e-4)


def _rolling_std(x: np.ndarray, w: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    if x.size < w:
        return np.array([])
    c1 = np.concatenate([[0.0], np.cumsum(x)])
    c2 = np.concatenate([[0.0], np.cumsum(x * x)])
    s1 = c1[w:] - c1[:-w]
    s2 = c2[w:] - c2[:-w]
    mean = s1 / w
    var = np.maximum(s2 / w - mean * mean, 0.0)
    return np.sqrt(var)


def vol_of_vol(returns: np.ndarray, short: int = 21, look: int = 63) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < short + 5:
        return 0.0
    vols = _rolling_std(r, short)
    tail = vols[-look:] if vols.size >= look else vols
    return float(tail.std(ddof=0)) if tail.size else 0.0


def recovery_strength(prices: np.ndarray) -> float:
    dd = drawdown_series(prices)
    if dd.size == 0:
        return 0.5
    return float((dd < 0.02).mean())


def regime_multiplier(returns: np.ndarray, look: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 42:
        return 1.0
    hist = _rolling_std(r, 21)
    if hist.size < 5:
        return 1.0
    cur = float(hist[-1])
    hist = hist[-look:] if hist.size >= look else hist
    if hist.std(ddof=0) == 0:
        return 1.0
    pct = float((hist < cur).mean())
    return float(np.clip(1.15 - 0.5 * pct, 0.6, 1.15))


# ------------------------------- weighting -------------------------------- #
def _normalize_long_only(w: np.ndarray, cap: float = 1.0) -> np.ndarray:
    w = np.clip(np.asarray(w, dtype=float), 0.0, None)
    if w.sum() <= 0:
        return np.full(len(w), 1.0 / len(w))
    cap = max(cap, 1.0 / len(w))
    w = w / w.sum()
    for _ in range(8):
        over = w > cap
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        room = ~over
        if not room.any():
            break
        w[room] += excess * w[room] / w[room].sum()
    return w / w.sum()


def w_equal(n: int) -> np.ndarray:
    return np.full(n, 1.0 / n)


def w_inverse_vol(window_rets: np.ndarray) -> np.ndarray:
    vol = window_rets.std(axis=0, ddof=0)
    vol = np.where(vol <= 0, np.nan, vol)
    inv = np.nan_to_num(1.0 / vol, nan=0.0)
    return _normalize_long_only(inv)


def w_risk_parity(window_rets: np.ndarray, iters: int = 80) -> np.ndarray:
    cov = np.cov(window_rets, rowvar=False)
    n = cov.shape[0]
    if n == 0 or not np.all(np.isfinite(cov)):
        return w_inverse_vol(window_rets)
    w = 1.0 / (np.sqrt(np.diag(cov)) + 1e-12)
    w = w / w.sum()
    for _ in range(iters):
        mrc = cov @ w
        rc = w * mrc
        target = rc.mean()
        step = np.where(mrc > 0, target / (mrc + 1e-12), w)
        w = 0.5 * w + 0.5 * np.clip(step, 1e-6, None)
        w = w / w.sum()
    return _normalize_long_only(w)


def w_drawdown_mgd(window_prices: np.ndarray, window_rets: np.ndarray,
                   alpha: float = 0.95) -> np.ndarray:
    n = window_prices.shape[1]
    raw = np.zeros(n)
    volvol = np.array([vol_of_vol(window_rets[:, j]) for j in range(n)])
    med = np.median(volvol)
    vv_norm = volvol / (med + 1e-12) if med > 0 else np.zeros(n)
    for j in range(n):
        cdar = empirical_cdar(window_prices[:, j], alpha=alpha)
        regime = regime_multiplier(window_rets[:, j])
        vv_mult = 1.0 / (1.0 + 0.5 * vv_norm[j])
        rec = recovery_strength(window_prices[:, j])
        rec_mult = 1.0 + 0.2 * (rec - 0.5)
        raw[j] = (1.0 / cdar) * regime * vv_mult * rec_mult
    return _normalize_long_only(raw)


def _round_weights(wv: np.ndarray, tickers: List[str], nd: int = 4) -> Dict[str, float]:
    """Round to nd decimals and push the residual onto the largest weight so the
    displayed/applied weights sum to exactly 1.0 (clean for 'Apply weights')."""
    r = [round(float(x), nd) for x in wv]
    resid = round(1.0 - sum(r), nd)
    if r:
        j = int(np.argmax(wv))
        r[j] = round(r[j] + resid, nd)
    return {t: r[i] for i, t in enumerate(tickers)}


def _weights_for(method: str, wp: np.ndarray, wr: np.ndarray, alpha: float) -> np.ndarray:
    if method == "equal":
        return w_equal(wp.shape[1])
    if method == "inverse_vol":
        return w_inverse_vol(wr)
    if method == "risk_parity":
        return w_risk_parity(wr)
    if method == "drawdown_mgd":
        return w_drawdown_mgd(wp, wr, alpha=alpha)
    raise ValueError(f"unknown method: {method}")


# ------------------------------- profile ---------------------------------- #
def _profile(daily: np.ndarray, total_turnover: float, years: float) -> Dict[str, float]:
    daily = np.asarray(daily, dtype=float)
    equity = np.concatenate([[1.0], np.cumprod(1.0 + daily)])
    total = float(equity[-1])
    cagr = total ** (1.0 / years) - 1.0 if years > 0 and total > 0 else 0.0
    ann_vol = float(daily.std(ddof=0) * math.sqrt(TRADING_DAYS))
    mean_ann = float(daily.mean() * TRADING_DAYS)
    sharpe = mean_ann / ann_vol if ann_vol > 0 else 0.0
    peak = np.maximum.accumulate(equity)
    dd = 1.0 - equity / peak
    max_dd = -float(dd.max())     # negative, matches the perf-metrics convention
    q = np.quantile(dd, 0.95)
    cdar95 = -(float(dd[dd >= q].mean()) if (dd >= q).any() else float(dd.max()))
    turnover_yr = (total_turnover / years) if years > 0 else 0.0
    return {
        "cagr": round(cagr, 4), "ann_vol": round(ann_vol, 4), "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_dd, 4), "cdar95": round(cdar95, 4),
        "turnover_per_yr": round(turnover_yr, 2),
    }


def _backtest(prices: np.ndarray, methods: List[str], window: int, rebalance: int,
              cost_bps: float, alpha: float) -> Dict[str, Dict[str, float]]:
    rets = prices[1:] / prices[:-1] - 1.0
    n_days, n_assets = rets.shape
    cost = cost_bps / 10_000.0
    rebal_days = [t for t in range(window, n_days) if (t - window) % rebalance == 0]
    if len(rebal_days) < 4:
        return {}
    out = {}
    years = (n_days - rebal_days[0]) / TRADING_DAYS
    for m in methods:
        port_ret, turnover = [], 0.0
        w = np.zeros(n_assets)
        for t in range(rebal_days[0], n_days):
            if t in rebal_days:
                wp = prices[t - window:t + 1]
                wr = rets[t - window:t]
                target = _weights_for(m, wp, wr, alpha)
                traded = 0.5 * np.abs(target - w).sum()
                turnover += traded
                w = target
                port_ret.append(float(w @ rets[t]) - traded * cost)
            else:
                port_ret.append(float(w @ rets[t]))
                grown = w * (1.0 + rets[t])
                w = grown / grown.sum()
        out[m] = _profile(np.asarray(port_ret), turnover, years)
    return out


# ------------------------------ public entry ------------------------------ #
def compute_drawdown_allocation(
    price_frame: pd.DataFrame,
    current_weights: Optional[Dict[str, float]] = None,
    methods: Optional[List[str]] = None,
    window: int = 252,
    rebalance: int = 21,
    cost_bps: float = 10.0,
    alpha: float = 0.95,
) -> Dict[str, Any]:
    """price_frame: date-indexed close prices (cols=tickers). Returns suggested
    as-of weights per method plus each method's walk-forward backtested profile."""
    methods = methods or DEFAULT_METHODS
    frame = price_frame.dropna(how="any").sort_index()
    tickers = list(frame.columns)
    n_assets = len(tickers)
    if n_assets < 2:
        raise ValueError("need >= 2 holdings with overlapping price history")
    prices = frame.to_numpy(dtype=float)
    n_obs = prices.shape[0]
    if n_obs < window + 5:
        raise ValueError(f"need >= {window + 5} trading days of history, have {n_obs}")

    # as-of suggested weights: use the most recent `window` days (point-in-time)
    wp = prices[-(window + 1):]
    wr = wp[1:] / wp[:-1] - 1.0
    profiles = _backtest(prices, methods, window, rebalance, cost_bps, alpha)

    out_methods = []
    for m in methods:
        wv = _weights_for(m, wp, wr, alpha)
        out_methods.append({
            "key": m,
            "label": METHOD_META[m]["label"],
            "note": METHOD_META[m]["note"],
            "weights": _round_weights(wv, tickers),
            "profile": profiles.get(m),
        })

    cur = None
    if current_weights:
        s = sum(max(0.0, float(v)) for v in current_weights.values()) or 1.0
        cur = {t: round(max(0.0, float(current_weights.get(t, 0.0))) / s, 4) for t in tickers}

    return {
        "as_of": str(frame.index[-1].date()),
        "tickers": tickers,
        "n_assets": n_assets,
        "params": {"window": window, "rebalance": rebalance, "cost_bps": cost_bps, "alpha": alpha},
        "data_window": {"start": str(frame.index[0].date()), "end": str(frame.index[-1].date()),
                        "n_obs": int(n_obs), "years": round(n_obs / TRADING_DAYS, 2)},
        "current_weights": cur,
        "methods": out_methods,
        "note": ("Suggested weights are point-in-time (trailing window only); profiles are a "
                 "walk-forward backtest net of turnover cost. Drawdown-managed targets lower "
                 "drawdown, not higher return -- pick it only if drawdown control is the priority."),
    }
