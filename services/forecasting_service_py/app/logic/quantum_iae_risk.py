"""Iterative Amplitude Estimation (IAE) for VaR and CVaR.

Implements the Woerner/Egger (IBM, 2019) pipeline:

    1. Load a lognormal terminal-price distribution as an amplitude-encoded
       state on n uncertainty qubits.
    2. Encode a piecewise-linear payoff (indicator or linear ramp) via
       qiskit.circuit.library.LinearAmplitudeFunction on an ancilla.
    3. Estimate the payoff expectation via IterativeAmplitudeEstimation
       with a Sampler primitive, yielding O(1/epsilon) convergence vs.
       the classical O(1/epsilon^2).
    4. VaR_alpha is obtained by bisection over the threshold x; CVaR_alpha
       by a second QAE run with a linear payoff max(VaR - x, 0) / alpha.

IAE currently requires the V1 Sampler interface in qiskit-algorithms.
We construct a local Sampler explicitly here; the IBM V1 SamplerV1 path
can be wired in later if QPU-accelerated IAE is wanted.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def _lognormal_params_from_prices(prices: np.ndarray, horizon_days: int) -> Dict[str, float]:
    """Fit mu, sigma of log-returns and project to the horizon."""
    prices = np.asarray(prices, dtype=float)
    log_returns = np.diff(np.log(prices))
    mu_daily = float(np.mean(log_returns))
    sigma_daily = float(np.std(log_returns, ddof=1))
    T = float(horizon_days)
    mu_T = mu_daily * T
    sigma_T = sigma_daily * math.sqrt(T)
    S0 = float(prices[-1])
    # log(S_T / S_0) ~ Normal(mu_T, sigma_T^2)  =>  S_T is lognormal
    # Qiskit's LogNormalDistribution expects mu (mean of underlying normal)
    # and sigma (VARIANCE of underlying normal, per Qiskit Finance convention).
    return {
        "mu": mu_T + math.log(S0),     # mean of log(S_T)
        "sigma_sq": sigma_T ** 2,      # variance of log(S_T)
        "sigma": sigma_T,
        "S0": S0,
        "mu_daily": mu_daily,
        "sigma_daily": sigma_daily,
        "horizon_days": int(horizon_days),
    }


def _build_distribution(num_qubits: int, params: Dict[str, float]):
    """Instantiate the LogNormalDistribution over a symmetric 3-sigma window."""
    from qiskit_finance.circuit.library import LogNormalDistribution

    # Terminal price statistics (lognormal mean/variance closed form)
    mu, sig2 = params["mu"], params["sigma_sq"]
    mean_S = math.exp(mu + sig2 / 2.0)
    var_S = (math.exp(sig2) - 1.0) * math.exp(2.0 * mu + sig2)
    std_S = math.sqrt(max(var_S, 0.0))
    low = max(0.0, mean_S - 3.0 * std_S)
    high = mean_S + 3.0 * std_S
    dist = LogNormalDistribution(
        num_qubits=num_qubits,
        mu=mu,
        sigma=sig2,
        bounds=(low, high),
    )
    return dist, low, high


def _cdf_at(num_qubits: int, dist, low: float, high: float, x_threshold: float, sampler, epsilon_target: float, alpha: float) -> float:
    """Estimate P(S_T <= x_threshold) via IAE using a step-indicator payoff."""
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import LinearAmplitudeFunction
    from qiskit_algorithms import EstimationProblem, IterativeAmplitudeEstimation

    # Indicator 1[x <= x_threshold] via a piecewise function with flat segments.
    # Two breakpoints: (low, x_threshold) returns 1; (x_threshold, high) returns 0.
    breakpoints = [low, x_threshold]
    slopes = [0.0, 0.0]
    offsets = [1.0, 0.0]
    f_min, f_max = 0.0, 1.0

    objective = LinearAmplitudeFunction(
        num_state_qubits=num_qubits,
        slope=slopes,
        offset=offsets,
        domain=(low, high),
        image=(f_min, f_max),
        breakpoints=breakpoints,
        rescaling_factor=0.25,
    )

    state_prep = QuantumCircuit(objective.num_qubits)
    state_prep.append(dist, range(num_qubits))
    state_prep.append(objective, range(objective.num_qubits))

    problem = EstimationProblem(
        state_preparation=state_prep,
        objective_qubits=[num_qubits],
        post_processing=objective.post_processing,
    )

    iae = IterativeAmplitudeEstimation(
        epsilon_target=epsilon_target,
        alpha=alpha,
        sampler=sampler,
    )
    result = iae.estimate(problem)
    return float(result.estimation_processed)


def _cvar_tail_expectation(num_qubits: int, dist, low: float, high: float, var_level: float, sampler, epsilon_target: float, alpha: float) -> float:
    """Estimate E[(VaR - S_T) * 1{S_T <= VaR}] via IAE using a linear ramp payoff."""
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import LinearAmplitudeFunction
    from qiskit_algorithms import EstimationProblem, IterativeAmplitudeEstimation

    # Payoff f(x) = max(VaR - x, 0). Piecewise linear:
    #   segment [low, VaR]: slope=-1, offset=VaR
    #   segment [VaR, high]: slope=0, offset=0
    breakpoints = [low, var_level]
    slopes = [-1.0, 0.0]
    offsets = [var_level, 0.0]
    f_min = 0.0
    f_max = max(var_level - low, 1e-9)

    objective = LinearAmplitudeFunction(
        num_state_qubits=num_qubits,
        slope=slopes,
        offset=offsets,
        domain=(low, high),
        image=(f_min, f_max),
        breakpoints=breakpoints,
        rescaling_factor=0.25,
    )

    state_prep = QuantumCircuit(objective.num_qubits)
    state_prep.append(dist, range(num_qubits))
    state_prep.append(objective, range(objective.num_qubits))

    problem = EstimationProblem(
        state_preparation=state_prep,
        objective_qubits=[num_qubits],
        post_processing=objective.post_processing,
    )

    iae = IterativeAmplitudeEstimation(
        epsilon_target=epsilon_target,
        alpha=alpha,
        sampler=sampler,
    )
    result = iae.estimate(problem)
    return float(result.estimation_processed)


def estimate_var_cvar_iae(
    historical_prices: List[float],
    horizon_days: int = 30,
    confidence: float = 0.95,
    num_uncertainty_qubits: int = 5,
    epsilon_target: float = 0.005,
    ci_alpha: float = 0.05,
    bisection_iters: int = 12,
    shots: int = 4096,
) -> Dict[str, Any]:
    """Estimate VaR and CVaR at the given confidence level via IAE.

    confidence          e.g. 0.95 => VaR at the 5% lower tail
    num_uncertainty_qubits   state-prep register width (2^n discretisation of prices)
    epsilon_target      IAE absolute error target on the amplitude
    ci_alpha            IAE confidence-interval tail probability (not the VaR level)
    bisection_iters     bisection steps to locate the VaR quantile
    """
    from qiskit.primitives import Sampler

    assert 0.0 < confidence < 1.0, "confidence must be in (0, 1)"
    tail = 1.0 - confidence  # e.g. 0.05

    params = _lognormal_params_from_prices(np.asarray(historical_prices, dtype=float), horizon_days)
    dist, low, high = _build_distribution(num_uncertainty_qubits, params)

    sampler = Sampler(options={"shots": int(shots)})

    # --- Bisect over threshold x to find VaR: smallest x with P(S_T <= x) >= tail ---
    t0 = time.time()
    lo, hi = low, high
    cdf_probe_count = 0
    for _ in range(bisection_iters):
        mid = 0.5 * (lo + hi)
        p = _cdf_at(num_uncertainty_qubits, dist, low, high, mid, sampler, epsilon_target, ci_alpha)
        cdf_probe_count += 1
        if p < tail:
            lo = mid
        else:
            hi = mid
    var_price = 0.5 * (lo + hi)
    var_cdf = _cdf_at(num_uncertainty_qubits, dist, low, high, var_price, sampler, epsilon_target, ci_alpha)
    cdf_probe_count += 1

    # --- CVaR: expectation over the tail, divided by the tail probability ---
    # The CVaR signal (a conditional-mean integrand scaled by ~alpha) is small,
    # so we tighten IAE precision for this call vs. the bisection CDF calls.
    cvar_epsilon = max(epsilon_target / 5.0, 5e-4)
    tail_integral = _cvar_tail_expectation(
        num_uncertainty_qubits, dist, low, high, var_price, sampler, cvar_epsilon, ci_alpha
    )
    # E[S_T | S_T <= VaR] = VaR - E[max(VaR - S_T, 0)] / P(S_T <= VaR).
    # Divide by the *design* tail probability (1 - confidence) rather than the
    # estimated var_cdf to avoid noise amplification when var_cdf is close to alpha.
    tail_prob = 1.0 - confidence
    cvar_price = var_price - (tail_integral / tail_prob)
    elapsed_ms = int((time.time() - t0) * 1000)

    S0 = params["S0"]
    var_return = (var_price / S0) - 1.0
    cvar_quantum_return = (cvar_price / S0) - 1.0

    # Classical closed-form CVaR for a lognormal terminal price. Used as a fallback
    # when quantum CVaR violates the monotonicity invariant (CVaR must be at least
    # as extreme as VaR on the loss side). Known fidelity limit of the current IAE
    # payoff encoding at practical qubit counts; see Woerner & Egger 2019.
    from scipy.stats import norm
    mu_T = params["mu_daily"] * params["horizon_days"]
    sig_T = params["sigma_daily"] * math.sqrt(params["horizon_days"])
    z_alpha = norm.ppf(1.0 - confidence)
    cvar_classical_return = float(
        math.exp(mu_T + 0.5 * sig_T ** 2) * norm.cdf(z_alpha - sig_T) / (1.0 - confidence) - 1.0
    )

    monotonicity_ok = bool(cvar_quantum_return <= var_return + 1e-9)
    if monotonicity_ok:
        cvar_return = cvar_quantum_return
        cvar_provenance = "quantum_iae"
    else:
        logger.warning(
            "IAE monotonicity violated: raw quantum CVaR=%.6f > VaR=%.6f. "
            "Falling back to classical lognormal CVaR=%.6f (Woerner 2019 fidelity limit "
            "at %d uncertainty qubits).",
            cvar_quantum_return, var_return, cvar_classical_return, num_uncertainty_qubits,
        )
        cvar_return = cvar_classical_return
        cvar_price = S0 * (1.0 + cvar_return)
        cvar_provenance = "classical_lognormal_fallback"

    return {
        "method": "Iterative Amplitude Estimation (IAE)",
        "backend": {
            "kind": "local",
            "name": "qiskit.primitives.Sampler (V1)",
            "shots": int(shots),
            "hardware": False,
        },
        "simulation_metadata": {
            "num_uncertainty_qubits": int(num_uncertainty_qubits),
            "epsilon_target": float(epsilon_target),
            "ci_alpha": float(ci_alpha),
            "bisection_iters": int(bisection_iters),
            "cdf_probes": int(cdf_probe_count),
            "horizon_days": int(horizon_days),
            "confidence": float(confidence),
            "tail_probability": float(tail),
            "S0": S0,
            "price_window": {"low": float(low), "high": float(high)},
            "runtime_ms": elapsed_ms,
        },
        "risk_metrics": {
            f"VaR_{int(confidence * 100)}": float(var_return),
            f"CVaR_{int(confidence * 100)}": float(cvar_return),
            "VaR_price": float(var_price),
            "CVaR_price": float(cvar_price),
            "estimated_tail_prob_at_VaR": float(var_cdf),
            "monotonicity_ok": monotonicity_ok,
            "VaR_provenance": "quantum_iae",
            "CVaR_provenance": cvar_provenance,
            "CVaR_quantum_raw": float(cvar_quantum_return),
            "CVaR_classical_lognormal": float(cvar_classical_return),
        },
    }
