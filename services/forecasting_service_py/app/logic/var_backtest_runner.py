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

Weight modes (composition basis for the realized series + MPS weights):
  - "constant" : today's portfolio weights applied across the whole window.
                 This is a VaR *model-validation* backtest (isolates model
                 calibration from composition drift) — the standard choice.
  - "drift"    : buy-and-hold value weights from shares x price, gated by
                 purchase_date. For a held (non-traded) book this IS the real
                 book — weights drift as prices move. Requires every position
                 to carry quantity; otherwise it falls back to "constant".
                 (Full trade-history versioning would need a holdings/trade
                 ledger Qsight does not yet ingest.)

The comparison harness (``run_portfolio_var_backtest_comparison``) runs several
methods — and an MPS physical-dimension sweep — over the *same* realized series
and date set, so their Kupiec/Christoffersen coverage is directly comparable.

Caveats encoded here:
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


def effective_weight_mode(requested: str, assets: List[dict]) -> str:
    """Resolve the requested weight mode against the data actually available.

    Drift needs a share count on *every* position; otherwise the value
    weighting is undefined, so we fall back to constant. Kept public so the
    API layer can derive the same cache key the runner will compute against.
    """
    if requested == "drift" and assets and all(float(a.get("quantity") or 0) > 0 for a in assets):
        return "drift"
    return "constant"


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


def _price_frame(data_map: Dict[str, pd.DataFrame], tickers: List[str]) -> pd.DataFrame:
    """Aligned close-price frame (rows=common dates, cols=tickers)."""
    common: Optional[pd.Index] = None
    for t in tickers:
        df = data_map.get(t)
        if df is None:
            continue
        common = df.index if common is None else common.intersection(df.index)
    if common is None or len(common) == 0:
        return pd.DataFrame()
    cols = {t: data_map[t].loc[common, "price"] for t in tickers if t in data_map}
    return pd.DataFrame(cols, index=common).sort_index()


def _portfolio_returns(data_map: Dict[str, pd.DataFrame],
                       weights: Dict[str, float]) -> pd.Series:
    """CONSTANT-weight daily portfolio return over the common date index."""
    P = _price_frame(data_map, list(data_map.keys()))
    if P.empty:
        return pd.Series(dtype=float)
    total_w = sum(weights.get(t, 0.0) for t in P.columns) or 1.0
    rets = P.pct_change().fillna(0.0)
    w = np.array([weights.get(t, 0.0) / total_w for t in P.columns])
    return pd.Series(rets.values @ w, index=P.index).sort_index()


def _portfolio_returns_drift(data_map: Dict[str, pd.DataFrame],
                             quantities: Dict[str, float],
                             purchase_dates: Dict[str, Any]) -> pd.Series:
    """DRIFT (buy-and-hold) daily portfolio return: value-weighted by
    shares x price, using the holdings held at the start of each day. A
    position only contributes once purchase_date <= the day (None = held
    from the start). Weights drift naturally as prices move."""
    tickers = [t for t in quantities if t in data_map]
    P = _price_frame(data_map, tickers)
    if P.empty:
        return pd.Series(dtype=float)
    idx = P.index
    q = np.array([float(quantities[t]) for t in P.columns])
    val = P.values * q                                   # (T, N) position $ value
    pmask = np.ones(P.shape, dtype=bool)                 # held-by-day mask
    for j, t in enumerate(P.columns):
        pdt = purchase_dates.get(t)
        if pdt is not None:
            pmask[:, j] = idx >= pd.to_datetime(pdt)
    m_prev = pmask[:-1]                                   # held at start of each return day
    v_prev = np.where(m_prev, val[:-1], 0.0).sum(axis=1)
    v_cur = np.where(m_prev, val[1:], 0.0).sum(axis=1)
    ratio = np.divide(v_cur, v_prev, out=np.ones_like(v_cur), where=v_prev > 0)
    return pd.Series(np.concatenate([[0.0], ratio - 1.0]), index=idx).sort_index()


def _asof_value_weights(data_map_trunc: Dict[str, pd.DataFrame],
                        quantities: Dict[str, float], purchase_dates: Dict[str, Any],
                        kept: List[str], asof_date) -> Dict[str, float]:
    """As-of value weights (shares x last available price) for the MPS combine
    under drift mode. Positions not yet purchased at asof_date get weight 0."""
    w: Dict[str, float] = {}
    for t in kept:
        pdt = purchase_dates.get(t)
        if pdt is not None and pd.to_datetime(pdt) > asof_date:
            w[t] = 0.0
            continue
        df = data_map_trunc.get(t)
        if df is None or df.empty:
            w[t] = 0.0
            continue
        w[t] = float(quantities.get(t, 0.0)) * float(df["price"].iloc[-1])
    return w


# --------------------------------------------------------------------------- #
# Per-as-of-date VaR predictors (signed simple return)
# --------------------------------------------------------------------------- #
def _predict_var_mps(data_map_trunc, tickers_order, weights, horizon_days,
                     confidence, n_sims, d, chi, seed) -> float:
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
    mu = float(np.mean(trailing_returns))
    sd = float(np.std(trailing_returns))
    z = float(norm.ppf(1.0 - confidence))
    if horizon_days > 1:
        return float(mu * horizon_days + sd * np.sqrt(horizon_days) * z)
    return float(mu + sd * z)


# --------------------------------------------------------------------------- #
# Window context (method-independent) + per-method series
# --------------------------------------------------------------------------- #
def _window_context(assets, period, est_window, n_backtest, horizon_days,
                    weight_mode="constant") -> Dict[str, Any]:
    weights = {str(a["ticker"]): float(a.get("weight", 0.0) or 0.0) for a in assets}
    quantities = {str(a["ticker"]): float(a.get("quantity") or 0.0) for a in assets}
    purchase_dates = {str(a["ticker"]): a.get("purchase_date") for a in assets}
    tickers = list(weights.keys())
    eff_mode = effective_weight_mode(weight_mode, assets)

    data_map = _fetch_data_map(tickers, period=period)
    if not data_map:
        raise ValueError("no price history for any portfolio ticker")
    if eff_mode == "drift":
        port_ret = _portfolio_returns_drift(data_map, quantities, purchase_dates)
    else:
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
        "weights": weights, "quantities": quantities, "purchase_dates": purchase_dates,
        "tickers": tickers, "data_map": data_map, "port_ret": port_ret, "dates": dates,
        "n": n, "indices": indices, "realized": realized, "used_dates": used_dates,
        "est_window": est_window, "weight_mode": eff_mode, "weight_mode_requested": weight_mode,
    }


def _predict_series(spec, ctx, confidence, horizon_days, n_simulations, bond_dim, seed):
    """Predicted VaR aligned to ctx['indices']; np.nan where a fit failed."""
    method = spec["method"]
    d = int(spec.get("physical_dim", 4))
    chi = int(spec.get("bond_dim", bond_dim))
    est_window = ctx["est_window"]
    drift = ctx["weight_mode"] == "drift"
    port_ret, data_map, dates = ctx["port_ret"], ctx["data_map"], ctx["dates"]
    tickers, weights = ctx["tickers"], ctx["weights"]
    preds = np.full(len(ctx["indices"]), np.nan)
    for pos, i in enumerate(ctx["indices"]):
        d_date = dates[i]
        try:
            if method == "mps_fan":
                trunc = {t: df[df.index < d_date].tail(est_window + 5) for t, df in data_map.items()}
                w_mps = (_asof_value_weights(trunc, ctx["quantities"], ctx["purchase_dates"], tickers, d_date)
                         if drift else weights)
                preds[pos] = _predict_var_mps(trunc, tickers, w_mps, horizon_days,
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


def _weight_mode_note(eff_mode: str, requested: str) -> str:
    if eff_mode == "drift":
        return ("buy-and-hold value weights (shares x price, gated by purchase_date); "
                "for a non-traded book this is the realized composition")
    if requested == "drift":
        return ("requested drift but positions lack share quantities; fell back to constant "
                "current weights (VaR model-validation backtest)")
    return "current weights held constant across the window (VaR model-validation backtest)"


# --------------------------------------------------------------------------- #
# Single-method backtest (used by /var_backtest)
# --------------------------------------------------------------------------- #
def run_portfolio_var_backtest(
    *, assets, confidence=0.95, horizon_days=1, est_window=252, n_backtest=250,
    method="mps_fan", n_simulations=500, physical_dim=4, bond_dim=8,
    random_seed=42, alpha=0.05, period="5y", weight_mode="constant",
) -> Dict[str, Any]:
    """Replay-backtest a portfolio's VaR for one method and score it."""
    if method not in ("mps_fan", "historical", "parametric"):
        raise ValueError(f"unknown method: {method}")
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    ctx = _window_context(assets, period, est_window, n_backtest, horizon_days, weight_mode)
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
    result["weight_mode"] = ctx["weight_mode"]
    result["weight_mode_requested"] = weight_mode
    result["weight_mode_note"] = _weight_mode_note(ctx["weight_mode"], weight_mode)
    result["params"] = {
        "est_window": est_window, "n_backtest": n_backtest, "n_simulations": n_simulations,
        "physical_dim": physical_dim, "bond_dim": bond_dim, "random_seed": random_seed,
        "period": period, "tickers": list(ctx["data_map"].keys()),
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


def _skip(spec) -> Dict[str, Any]:
    return {"key": spec["key"], "label": spec.get("label", spec["key"]),
            "method": spec["method"],
            "physical_dim": int(spec["physical_dim"]) if spec["method"] == "mps_fan" else None,
            "status": "skipped"}


def run_portfolio_var_backtest_comparison(
    *, assets, confidence=0.95, horizon_days=1, est_window=252, n_backtest=120,
    methods: Optional[List[Dict[str, Any]]] = None, n_simulations=400, bond_dim=8,
    random_seed=42, alpha=0.05, period="5y", weight_mode="constant",
) -> Dict[str, Any]:
    """Run several methods (+ an MPS physical-dim sweep) over the SAME realized
    series and date set, so their coverage is directly comparable."""
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    specs = methods or DEFAULT_COMPARISON_SPECS
    ctx = _window_context(assets, period, est_window, n_backtest, horizon_days, weight_mode)
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
        "weight_mode": ctx["weight_mode"],
        "weight_mode_requested": weight_mode,
        "weight_mode_note": _weight_mode_note(ctx["weight_mode"], weight_mode),
        "n_observations": int(len(realized)),
        "shared": {"dates": used_dates, "realized_return": realized.tolist()},
        "methods": method_results,
        "recommended": recommended,
        "params": {
            "est_window": est_window, "n_backtest": n_backtest, "n_simulations": n_simulations,
            "bond_dim": bond_dim, "random_seed": random_seed, "period": period,
            "tickers": list(ctx["data_map"].keys()), "n_assets": n_assets,
        },
        "data_window": {
            "start": str(ctx["dates"][0].date()), "end": str(ctx["dates"][-1].date()),
            "n_return_obs": ctx["n"],
        },
    }
