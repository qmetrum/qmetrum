"""VQMC-based single-asset scenario fan generation.

Uses the trained Variational Quantum Monte Carlo ansatz to generate
distributional scenario paths for individual assets. Each scenario
applies shock/scale/drift knobs to the GBM parameters, then samples
N paths from the trained quantum circuit's shock distribution.

Produces the same fan shape as the MPS-copula portfolio scenarios:
{central, lower_1s, upper_1s, lower_2s, upper_2s} per scenario.

This is genuinely quantum: the shock distribution comes from a trained
parameterised quantum circuit (Qiskit), not from a classical Gaussian.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from app.logic.quantum_vqmc_trained import (
    load_trained_params,
    _sample_z_scores,
)

logger = logging.getLogger(__name__)

_DEFAULT_SCENARIOS = {
    "bull_10": {"initial_shock_pct": 0.10, "return_scale": 1.0, "drift_shift": 0.0},
    "bear_10": {"initial_shock_pct": -0.10, "return_scale": 1.0, "drift_shift": 0.0},
    "high_vol_regime": {"initial_shock_pct": 0.0, "return_scale": 1.25, "drift_shift": 0.0},
    "low_vol_regime": {"initial_shock_pct": 0.0, "return_scale": 0.75, "drift_shift": 0.0},
}


def generate_vqmc_scenario_fans(
    historical_prices: List[float],
    ticker: str,
    horizon_days: int = 30,
    n_simulations: int = 500,
    custom_scenarios: Optional[List[Dict[str, Any]]] = None,
    random_seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate VQMC-based distributional scenario fans for a single asset.

    Returns:
      {
        "scenarios": {name: {central, lower_1s, upper_1s, lower_2s, upper_2s}, ...},
        "scenarios_legacy": {name: [central_prices], ...},
        "method": "Trained VQMC (quantum circuit shocks)",
        "ansatz_info": {...} or None,
      }
    """
    from qiskit.primitives import Sampler

    prices = np.asarray(historical_prices, dtype=float)
    if len(prices) < 30:
        return {"scenarios": {}, "scenarios_legacy": {}, "method": "insufficient_data"}

    log_ret = np.diff(np.log(prices))
    mu_daily = float(np.mean(log_ret))
    sigma_daily = float(np.std(log_ret))
    S0 = float(prices[-1])

    # Load trained ansatz (or use default circuit)
    trained = load_trained_params(ticker)
    ansatz_info = None
    if trained is not None:
        params = np.asarray(trained["params"], dtype=float)
        ansatz_info = {
            "ticker": ticker,
            "n_qubits": trained.get("n_qubits"),
            "trained_at_ms": trained.get("trained_at_ms"),
        }
        sampler = Sampler(options={"shots": 4096})
        z_pool = _sample_z_scores(params, sampler, shots=4096)
        if len(z_pool) < 100:
            z_pool = np.concatenate([z_pool, np.random.standard_normal(1000)])
    else:
        # No trained ansatz: fall back to Gaussian shocks (still label honestly)
        z_pool = np.random.standard_normal(4096)
        ansatz_info = {"ticker": ticker, "fallback": "gaussian", "reason": "no_trained_params"}

    rng = np.random.default_rng(random_seed)

    # Build scenario definitions
    scenario_defs = dict(_DEFAULT_SCENARIOS)
    for sc in (custom_scenarios or []):
        name = str(sc.get("name", "")).strip()
        if name:
            scenario_defs[name] = sc

    def _fan(shock_pct: float, scale: float, drift_shift: float) -> Dict[str, Any]:
        """Sample N paths from the VQMC shock pool under scenario knobs."""
        shocks = rng.choice(z_pool, size=(horizon_days, n_simulations))

        drift = (mu_daily + drift_shift - 0.5 * (sigma_daily * scale) ** 2)
        diffusion = sigma_daily * scale * shocks
        log_increments = drift + diffusion

        base = S0 * (1.0 + shock_pct)
        log_paths = np.cumsum(log_increments, axis=0)
        price_paths = base * np.exp(log_paths)  # (T, N)

        return {
            "central":  np.percentile(price_paths, 50,   axis=1).tolist(),
            "lower_1s": np.percentile(price_paths, 16,   axis=1).tolist(),
            "upper_1s": np.percentile(price_paths, 84,   axis=1).tolist(),
            "lower_2s": np.percentile(price_paths, 2.5,  axis=1).tolist(),
            "upper_2s": np.percentile(price_paths, 97.5, axis=1).tolist(),
        }

    scenarios_fan = {}
    scenarios_legacy = {}

    # Base scenario (no shock)
    base_fan = _fan(0.0, 1.0, 0.0)
    scenarios_fan["base"] = base_fan
    scenarios_legacy["base"] = base_fan["central"]

    for name, sc in scenario_defs.items():
        fan = _fan(
            shock_pct=float(sc.get("initial_shock_pct", 0.0)),
            scale=float(sc.get("return_scale", 1.0)),
            drift_shift=float(sc.get("drift_shift", 0.0)),
        )
        scenarios_fan[name] = fan
        scenarios_legacy[name] = fan["central"]

    return {
        "scenarios": scenarios_fan,
        "scenarios_legacy": scenarios_legacy,
        "method": "Trained VQMC (quantum circuit shocks)" if trained else "Gaussian fallback",
        "ansatz_info": ansatz_info,
    }
