"""Adversarial scenario discovery via gradient descent on smoothed CVaR.

Finds the worst-case per-asset shock vector within +-k*sigma bounds that
minimises portfolio CVaR, using L-BFGS-B with multiple random restarts.
The discovered shock is returned as a scenario definition compatible with
the MPS-copula fan pipeline in portfolio_logic.

The search is classical (gradient descent won the benchmark against QAOA
and Grover at all testable scales; see app/bench/ADVERSARIAL_BENCHMARK.md).
The quantum contribution enters when the discovered scenario is visualised
as a distributional fan via MPS-copula sampling.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.logic.tensor_network_risk import sample_standardised_joint_returns

logger = logging.getLogger(__name__)


def _portfolio_cvar(
    shock_vector: np.ndarray,
    z_samples: np.ndarray,
    asset_mu: np.ndarray,
    asset_sigma: np.ndarray,
    weights: np.ndarray,
    last_price: float,
    alpha: float = 0.05,
    smoothing: float = 0.01,
) -> float:
    """Smoothed CVaR of terminal portfolio return under per-asset shocks.

    shock_vector: (N,) in sigma units.
    smoothing > 0 uses softplus relaxation for L-BFGS-B finite differences.
    """
    sd = asset_sigma
    shock_returns = np.exp(shock_vector * sd) - 1.0
    shock_port = float(np.dot(shock_returns, weights))
    base = last_price * (1.0 + shock_port)

    log_rets = asset_mu + sd * z_samples               # (T, S, N)
    port_log_rets = np.einsum("tsn,n->ts", log_rets, weights)
    terminal = base * np.exp(np.sum(port_log_rets, axis=0))
    total_return = terminal / last_price - 1.0

    if smoothing > 0:
        var_level = float(np.percentile(total_return, alpha * 100))
        excess = var_level - total_return
        soft = smoothing * np.log1p(np.exp(excess / smoothing))
        return float(var_level - np.mean(soft) / alpha)
    else:
        cutoff = int(max(1, math.floor(alpha * len(total_return))))
        return float(np.mean(np.sort(total_return)[:cutoff]))


def discover_worst_case(
    data_map: Dict[str, pd.DataFrame],
    weights: Dict[str, float],
    horizon_days: int = 30,
    n_sims: int = 500,
    shock_sigma: float = 3.0,
    n_restarts: int = 50,
    mps_d: int = 4,
    mps_chi: int = 8,
) -> Dict[str, Any]:
    """Find the worst-case cross-asset shock vector and return it as a scenario.

    Returns a dict with:
      scenario_def:  {name, initial_shock_pct, return_scale, drift_shift} compatible
                     with the MPS-copula fan pipeline.
      shock_vector:  per-asset shocks in sigma units (for audit).
      shock_pcts:    per-asset shock as % price change (for display).
      cvar:          the CVaR at the discovered worst case.
      runtime_ms:    wall-clock.
    """
    from scipy.optimize import minimize

    tickers = list(weights.keys())
    sample = sample_standardised_joint_returns(
        data_map, tickers, n_steps=horizon_days, n_simulations=n_sims,
        d=mps_d, chi=mps_chi, random_seed=42,
    )
    kept = sample["tickers"]
    w = np.array([float(weights.get(t, 0.0)) for t in kept], dtype=float)
    w = w / w.sum()
    mu = sample["asset_mu"]
    sd = sample["asset_sigma"]
    z = sample["z_samples"]

    last_prices = {t: float(data_map[t]["price"].iloc[-1]) for t in kept}
    port_last = sum(last_prices[t] * w[i] for i, t in enumerate(kept))

    bounds_arr = np.full(len(kept), shock_sigma)
    bounds = [(-float(b), float(b)) for b in bounds_arr]
    rng = np.random.default_rng(42)

    t0 = time.time()
    best_val = float("inf")
    best_x = np.zeros(len(kept))
    n_evals = 0

    def obj(x):
        nonlocal n_evals
        n_evals += 1
        return _portfolio_cvar(x, z, mu, sd, w, port_last)

    for _ in range(n_restarts):
        x0 = rng.uniform(-bounds_arr, bounds_arr)
        res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 100, "ftol": 1e-8})
        if res.fun < best_val:
            best_val = res.fun
            best_x = res.x.copy()

    # Recompute exact (non-smoothed) CVaR at the optimum
    exact_cvar = _portfolio_cvar(best_x, z, mu, sd, w, port_last, smoothing=0.0)
    elapsed_ms = int((time.time() - t0) * 1000)

    # Convert sigma-unit shocks to price-percentage shocks
    shock_pcts = {t: float(np.exp(best_x[i] * sd[i]) - 1.0) for i, t in enumerate(kept)}
    # Aggregate portfolio-level initial shock
    agg_shock_pct = float(sum(shock_pcts[t] * w[i] for i, t in enumerate(kept)))

    return {
        "scenario_def": {
            "name": "worst_case_cvar",
            "initial_shock_pct": agg_shock_pct,
            "return_scale": 1.0,
            "drift_shift": 0.0,
        },
        "tickers": kept,
        "shock_vector_sigma": best_x.tolist(),
        "shock_pcts": shock_pcts,
        "agg_shock_pct": agg_shock_pct,
        "cvar": exact_cvar,
        "n_evaluations": n_evals,
        "runtime_ms": elapsed_ms,
        "mps": sample["mps"],
    }
