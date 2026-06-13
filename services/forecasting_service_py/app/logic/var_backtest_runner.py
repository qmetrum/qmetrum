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
  - "historical" : empirical 5th percentile of the trailing portfolio returns.
  - "parametric" : normal VaR from the trailing mean/vol (mu + z*sigma) — the
                   classic "volatility level -> VaR" model.

The comparison harness (``run_portfolio_var_backtest_comparison``) runs several
methods — and an MPS physical-dimension sweep — over the *same* realized series
and date set, so their Kupiec/Christoffersen coverage is directly comparable.
This answers "which volatility model actually passes VaR 95", and the MPS d-sweep
shows whether finer return binning fixes the known anti-conservative d=4 tails.

Caveats encoded here:
  - Position weights are current-only (no history), so today's weights are
    applied across the whole window (standard but lossy — documented).
  - horizon_days > 1 uses overlapping forward windows; the coverage tests
    assume independence, so ``overlapping_windows`` is flagged in the result.
  - The MPS sampler builds a dense d^N joint tensor, so high physical_dim is
    infeasible for many assets; such sweep points are reported as skipped.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

from app.logic.tensor_network_risk import sample_standardised_joint_returns
from app.logic.var_backtest import extract_var_from_paths, run_var_backtest
from app.services.market_store import get_price_series_cached

logger = logging.getLogger(__name__)

MIN_BACKTEST_OBS = 30          # below this the coverage tests are meaningless
MIN_TRAILING = 30              # min trailing returns for an empirical/parametric VaR
MAX_JOINT_TENSOR = 2_000_000   # d^N cap for the dense MPS joint tensor

DEFAULT_COMPARISON_SPECS: List[Dict[str, Any]] = [
    {"key": "historical", "label": "Historical", "method": "historical"},
    {"key": "parametric", "label": "Parametric (normal)", "method": "parametric"},
    {"key": "mps_d4", "label": "MPS fan (d=4)", "method": "mps_fan", "physical_dim": 4},
    {"key": "mps_d8", "label": "MPS fan (d=8)", "method": "mps_fan", "physical_dim": 8},
]


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Per-as-of-date VaR predictors (signed simple return)
# --------------------------------------------------------------------------- #
def _predict_var_mps(data_map_trunc, tickers_order, weights, horizon_days,
                     confidence, n_sims, d, chi, seed) -> float:
    """One as-of MPS-copula VaR. Mirrors the marginal reconstruction in
    portfolio_logic._fan_from_mps with scale=1, drift=0."""
    sample = sample_standardised_joint_returns(
        data_map=data_map_trunc, tickers_order=tickers_order, n_steps=horizon_days,
        n_simulations=n_sims, d=d, chi=chi, random_seed=seed,
    )
    z = sample["z_samples"]
    mu, sd, kept = sample["asset_mu"], sample["asset_sigma"], sample["tickers"]
    w = np.array([weights.get(t, 0.0) for t in kept], dtype=float)
    if w.sum() <= 0:
        raise ValueError("no positive weight among kept tickers")
    w = w / w.sum()
    r = mu + sd * z
    port_r = np.einsum("tsn,n->ts", r, w)
    paths = np.exp(np.cumsum(port_r, axis=0))
    return float(extract_var_from_paths(paths, base=1.0, confidence=confidence)[-1])


def _predict_var_historical(trailing_returns, confidence, horizon_days) -> float:
    q = (1.0 - confidence) * 100.0
    var_1d = float(np.percentile(trailing_returns, q))
    return var_1d * float(np.sqrt(horizon_days)) if horizon_days > 1 else var_1d


def _predict_var_parametric(trailing_returns, confidence, horizon_days) -> float:
    """Normal VaR: mu + z*sigma from the trailing window (z<0). sqrt-time scaled."""
    mu = float(np.mean(trailing_returns))
    sd = float(np.std(trailing_returns))
    z = float(norm.ppf(1.0 - confidence))
    if horizon_days > 1:
        return float(mu * horizon_days + sd * np.sqrt(horizon_days) * z)
    return float(mu + sd * z)


# --------------------------------------------------------------------------- #
# Window context (method-independent) + per-method series
# --------------------------------------------------------------------------- #
def _window_context(assets, period, est_window, n_backtest, horizon_days) -> Dict[str, Any]:
    weights = {str(a["ticker"]): float(a.get("weight", 0.0) or 0.0) for a in assets}
    tickers = list(weights.keys())
    data_map = _fetch_data_map(tickers, period=period)
    if not data_map:
        raise ValueError("no price history for any portfolio ticker")
    port_ret = _portfolio_returns(data_map, weights)
    if port_ret.empty:
        raise ValueError("no overlapping price history across tickers")
    dates = port_ret.index
    n = len(port_ret)
    if n < est_window + horizon_days + MIN_BACKTEST_OBS:
        raise ValueError(
            f"insufficient history: have {n} return obs, need >= "
            f"{est_window + horizon_days + MIN_BACKTEST_OBS} "
            f"(est_window={est_window} + horizon={horizon_days} + {MIN_BACKTEST_OBS} test days)"
        )
    start_i = max(est_window, n - n_backtest)
    indices = list(range(start_i, n - (horizon_days - 1)))
    realized = [float((1.0 + port_ret.iloc[i:i + horizon_days]).prod() - 1.0) for i in indices]
    used_dates = [str(dates[i].date()) for i in indices]
    return {
        "weights": weights, "tickers": tickers, "data_map": data_map,
        "port_ret": port_ret, "dates": dates, "n": n, "indices": indices,
        "realized": realized, "used_dates": used_dates, "est_window": est_window,
    }


def _predict_series(spec, ctx, confidence, horizon_days, n_simulations, bond_dim, seed):
    """Predicted VaR aligned to ctx['indices']; np.nan where a fit failed."""
    method = spec["method"]
    d = int(spec.get("physical_dim", 4))
    chi = int(spec.get("bond_dim", bond_dim))
    est_window = ctx["est_window"]
    port_ret, data_map, dates = ctx["port_ret"], ctx["data_map"], ctx["dates"]
    tickers, weights = ctx["tickers"], ctx["weights"]
    preds = np.full(len(ctx["indices"]), np.nan)
    for pos, i in enumerate(ctx["indices"]):
        d_date = dates[i]
        try:
            if method == "mps_fan":
                trunc = {t: df[df.index < d_date].tail(est_window + 5) for t, df in data_map.items()}
                preds[pos] = _predict_var_mps(trunc, tickers, weights, horizon_days,
                                              confidence, n_simulations, d, chi, seed)
            else:
                trailing = port_ret.iloc[max(0, i - est_window):i].to_numpy()
                if len(trailing) < MIN_TRAILING:
                    continue
                if method == "historical":
                    preds[pos] = _predict_var_historical(trailing, confidence, horizon_days)
                elif method == "parametric":
                    preds[pos] = _predict_var_parametric(trailing, confidence, horizon_days)
                else:
                    raise ValueError(f"unknown method: {method}")
        except Exception as e:
            logger.warning("var_backtest %s predict failed at %s: %s", method, d_date.date(), e)
    return preds


# --------------------------------------------------------------------------- #
# Single-method backtest (used by /var_backtest)
# --------------------------------------------------------------------------- #
def run_portfolio_var_backtest(
    *, assets, confidence=0.95, horizon_days=1, est_window=252, n_backtest=250,
    method="mps_fan", n_simulations=500, physical_dim=4, bond_dim=8,
    random_seed=42, alpha=0.05, period="5y",
) -> Dict[str, Any]:
    """Replay-backtest a portfolio's VaR for one method and score it."""
    if method not in ("mps_fan", "historical", "parametric"):
        raise ValueError(f"unknown method: {method}")
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    ctx = _window_context(assets, period, est_window, n_backtest, horizon_days)
    if method == "mps_fan" and len(ctx["data_map"]) < 2:
        raise ValueError("mps_fan backtest needs >= 2 assets with price history")

    spec = {"method": method, "physical_dim": physical_dim, "bond_dim": bond_dim}
    preds = _predict_series(spec, ctx, confidence, horizon_days, n_simulations, bond_dim, random_seed)
    finite = np.isfinite(preds)
    skipped = int((~finite).sum())
    realized = np.array(ctx["realized"])[finite]
    predicted = preds[finite]
    used_dates = [d for d, ok in zip(ctx["used_dates"], finite) if ok]
    if len(realized) < MIN_BACKTEST_OBS:
        raise ValueError(
            f"too few backtest observations ({len(realized)}); widen the window or add history"
        )

    result = run_var_backtest(realized, predicted, confidence=confidence, alpha=alpha, dates=used_dates)
    result["method"] = method
    result["horizon_days"] = horizon_days
    result["overlapping_windows"] = bool(horizon_days > 1)
    result["skipped_days"] = skipped
    result["params"] = {
        "est_window": est_window, "n_backtest": n_backtest, "n_simulations": n_simulations,
        "physical_dim": physical_dim, "bond_dim": bond_dim, "random_seed": random_seed,
        "period": period, "tickers": list(ctx["data_map"].keys()),
        "weights_note": "current position weights applied across the whole window (no weight history)",
    }
    result["data_window"] = {
        "start": str(ctx["dates"][0].date()), "end": str(ctx["dates"][-1].date()),
        "n_return_obs": ctx["n"],
    }
    return result


# --------------------------------------------------------------------------- #
# Multi-method comparison (used by /var_backtest_compare)
# --------------------------------------------------------------------------- #
def _summarise(spec, bt) -> Dict[str, Any]:
    return {
        "key": spec["key"],
        "label": spec.get("label", spec["key"]),
        "method": spec["method"],
        "physical_dim": int(spec["physical_dim"]) if spec["method"] == "mps_fan" else None,
        "status": "ok",
        "n_observations": bt["n_observations"],
        "exceptions": bt["exceptions"],
        "expected_exceptions": bt["expected_exceptions"],
        "breach_rate": bt["breach_rate"],
        "expected_breach_rate": bt["expected_breach_rate"],
        "kupiec": {"p_value": bt["kupiec"]["p_value"], "reject": bt["kupiec"]["reject"]},
        "christoffersen_cc": {
            "p_value": bt["christoffersen"]["conditional_coverage"]["p_value"],
            "reject": bt["christoffersen"]["conditional_coverage"]["reject"],
        },
        "independence": {
            "p_value": bt["christoffersen"]["independence"]["p_value"],
            "reject": bt["christoffersen"]["independence"]["reject"],
        },
        "basel_zone": bt["basel_traffic_light"]["zone"],
        "observed_expected_shortfall": bt["observed_expected_shortfall"],
        "model_passes": bt["model_passes"],
        "var_threshold": bt["series"]["var_threshold"],
    }


def run_portfolio_var_backtest_comparison(
    *, assets, confidence=0.95, horizon_days=1, est_window=252, n_backtest=120,
    methods: Optional[List[Dict[str, Any]]] = None, n_simulations=400, bond_dim=8,
    random_seed=42, alpha=0.05, period="5y",
) -> Dict[str, Any]:
    """Run several methods (+ an MPS physical-dim sweep) over the SAME realized
    series and date set, so their coverage is directly comparable. Answers
    'which volatility model passes VaR 95'."""
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    specs = methods or DEFAULT_COMPARISON_SPECS
    ctx = _window_context(assets, period, est_window, n_backtest, horizon_days)
    n_assets = len(ctx["data_map"])

    pred_map: Dict[str, np.ndarray] = {}
    skipped_entries: List[Dict[str, Any]] = []
    runnable: List[Dict[str, Any]] = []
    for spec in specs:
        if spec["method"] == "mps_fan":
            d = int(spec.get("physical_dim", 4))
            if n_assets < 2:
                skipped_entries.append({**_skip(spec), "reason": "needs >= 2 assets"})
                continue
            if d ** n_assets > MAX_JOINT_TENSOR:
                skipped_entries.append({**_skip(spec),
                    "reason": f"d^N = {d}^{n_assets} exceeds dense-tensor cap {MAX_JOINT_TENSOR:,}"})
                continue
        pred_map[spec["key"]] = _predict_series(
            spec, ctx, confidence, horizon_days, n_simulations, bond_dim, random_seed)
        runnable.append(spec)

    if not runnable:
        raise ValueError("no feasible methods for this portfolio/window")

    # Common date mask: keep only dates where EVERY runnable method produced a
    # VaR, so all methods are scored on the identical sample (fair comparison).
    mask = np.all([np.isfinite(pred_map[s["key"]]) for s in runnable], axis=0)
    realized = np.array(ctx["realized"])[mask]
    used_dates = [d for d, m in zip(ctx["used_dates"], mask) if m]
    if len(realized) < MIN_BACKTEST_OBS:
        raise ValueError(
            f"too few common backtest observations ({len(realized)}); widen the window or add history"
        )

    method_results: List[Dict[str, Any]] = []
    for spec in runnable:
        bt = run_var_backtest(realized, pred_map[spec["key"]][mask],
                              confidence=confidence, alpha=alpha, dates=used_dates)
        method_results.append(_summarise(spec, bt))
    method_results.extend(skipped_entries)

    # Recommend the passing method whose breach rate is closest to target;
    # ties broken by spec order (simpler methods first).
    passers = [m for m in method_results if m.get("status") == "ok" and m["model_passes"]]
    recommended = None
    if passers:
        order = {s["key"]: i for i, s in enumerate(specs)}
        best = min(passers, key=lambda m: (abs(m["breach_rate"] - m["expected_breach_rate"]),
                                           order.get(m["key"], 99)))
        recommended = {"key": best["key"], "label": best["label"],
                       "why": "passes Kupiec + Christoffersen with breach rate closest to target"}

    return {
        "confidence": confidence,
        "alpha": alpha,
        "horizon_days": horizon_days,
        "overlapping_windows": bool(horizon_days > 1),
        "n_observations": int(len(realized)),
        "shared": {"dates": used_dates, "realized_return": realized.tolist()},
        "methods": method_results,
        "recommended": recommended,
        "params": {
            "est_window": est_window, "n_backtest": n_backtest, "n_simulations": n_simulations,
            "bond_dim": bond_dim, "random_seed": random_seed, "period": period,
            "tickers": list(ctx["data_map"].keys()), "n_assets": n_assets,
            "weights_note": "current position weights applied across the whole window (no weight history)",
        },
        "data_window": {
            "start": str(ctx["dates"][0].date()), "end": str(ctx["dates"][-1].date()),
            "n_return_obs": ctx["n"],
        },
    }


def _skip(spec) -> Dict[str, Any]:
    return {"key": spec["key"], "label": spec.get("label", spec["key"]),
            "method": spec["method"],
            "physical_dim": int(spec["physical_dim"]) if spec["method"] == "mps_fan" else None,
            "status": "skipped"}
