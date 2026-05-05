"""Trainable Variational Quantum Monte Carlo.

Replaces the hand-set rotations in quantum_risk.py with a parameterised
Qiskit ansatz trained per-ticker against historical log-return moments.

Loss: squared error over the first four standardised moments (mean,
variance, skew, kurtosis) of returns implied by circuit samples vs.
the empirical distribution. SPSA optimiser (few evaluations, noise-tolerant).

Trained parameters are cached as JSON under app/cache/quantum_ansatz/{ticker}.json
so inference is fast; training runs nightly or on demand.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "quantum_ansatz"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_N_QUBITS = 6
_N_LAYERS = 3
_PARAMS_PER_LAYER = 2 * _N_QUBITS  # Ry + Rz per qubit per layer
_N_PARAMS = _N_LAYERS * _PARAMS_PER_LAYER


def _build_ansatz(params: np.ndarray):
    """Hardware-efficient ansatz: alternating Ry/Rz layers with ring entanglement."""
    from qiskit import QuantumCircuit

    assert len(params) == _N_PARAMS, f"expected {_N_PARAMS} params, got {len(params)}"
    qc = QuantumCircuit(_N_QUBITS)
    for q in range(_N_QUBITS):
        qc.h(q)
    idx = 0
    for _layer in range(_N_LAYERS):
        for q in range(_N_QUBITS):
            qc.ry(float(params[idx]), q); idx += 1
            qc.rz(float(params[idx]), q); idx += 1
        for q in range(_N_QUBITS - 1):
            qc.cx(q, q + 1)
        qc.cx(_N_QUBITS - 1, 0)
    qc.measure_all()
    return qc


def _sample_z_scores(params: np.ndarray, sampler, shots: int) -> np.ndarray:
    """Run the ansatz, decode bitstrings to z-scores over [-3, +3]."""
    qc = _build_ansatz(params)
    job = sampler.run([qc], shots=shots) if hasattr(sampler, "options") else sampler.run(qc, shots=shots)
    result = job.result()
    # V1 Sampler returns quasi-distributions per circuit; pick the first.
    try:
        dist = result.quasi_dists[0]
    except AttributeError:
        dist = result[0].data.meas.get_counts()

    max_int = (1 << _N_QUBITS) - 1
    samples = []
    for outcome, weight in dist.items():
        ival = int(outcome) if isinstance(outcome, (int, np.integer)) else int(str(outcome), 2)
        count = int(round(float(weight) * shots)) if isinstance(weight, float) and weight <= 1.0 else int(weight)
        samples.extend([ival] * count)
    if not samples:
        return np.zeros(1)
    arr = np.asarray(samples, dtype=float)
    # Map 0..max_int -> -3..+3 sigma
    z = (arr / max_int) * 6.0 - 3.0
    return z


def _standardised_moments(x: np.ndarray) -> np.ndarray:
    """Return (mean, variance, skew, excess_kurtosis) of the array."""
    m = float(np.mean(x))
    v = float(np.var(x))
    s = float(np.std(x))
    if s < 1e-9:
        return np.array([m, v, 0.0, 0.0])
    z = (x - m) / s
    return np.array([m, v, float(np.mean(z ** 3)), float(np.mean(z ** 4) - 3.0)])


def _empirical_return_moments(log_returns: np.ndarray) -> np.ndarray:
    """Target moments computed on standardised historical log-returns."""
    lr = (log_returns - np.mean(log_returns)) / (np.std(log_returns) + 1e-12)
    return _standardised_moments(lr)


def _loss(params: np.ndarray, target_moments: np.ndarray, sampler, shots: int) -> float:
    samples = _sample_z_scores(params, sampler, shots)
    m = _standardised_moments(samples)
    # Weight higher moments less (noisier to estimate)
    weights = np.array([1.0, 1.0, 0.5, 0.25])
    return float(np.sum(weights * (m - target_moments) ** 2))


def train_ansatz(
    historical_prices: List[float],
    ticker: str,
    maxiter: int = 75,
    shots: int = 2048,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Train PQC parameters to match empirical return moments; persist to cache."""
    from qiskit.primitives import Sampler
    from qiskit_algorithms.optimizers import SPSA

    prices = np.asarray(historical_prices, dtype=float)
    if len(prices) < 60:
        raise ValueError("Need >= 60 historical prices for training")
    log_ret = np.diff(np.log(prices))
    target = _empirical_return_moments(log_ret)

    rng = np.random.default_rng(seed)
    x0 = rng.uniform(-np.pi, np.pi, size=_N_PARAMS)

    sampler = Sampler(options={"shots": int(shots)})
    spsa = SPSA(maxiter=int(maxiter))

    t0 = time.time()
    result = spsa.minimize(fun=lambda p: _loss(p, target, sampler, shots), x0=x0)
    elapsed_ms = int((time.time() - t0) * 1000)

    trained_params = np.asarray(result.x, dtype=float).tolist()
    final_loss = float(result.fun)
    final_samples = _sample_z_scores(np.asarray(trained_params), sampler, shots=shots)
    final_moments = _standardised_moments(final_samples).tolist()

    payload = {
        "ticker": ticker,
        "n_qubits": _N_QUBITS,
        "n_layers": _N_LAYERS,
        "params": trained_params,
        "target_moments": target.tolist(),
        "trained_moments": final_moments,
        "final_loss": final_loss,
        "maxiter": int(maxiter),
        "shots": int(shots),
        "trained_at_ms": int(time.time() * 1000),
        "runtime_ms": elapsed_ms,
    }
    _cache_path(ticker).write_text(json.dumps(payload))
    logger.info("Trained VQMC ansatz for %s: loss=%.4f runtime=%dms", ticker, final_loss, elapsed_ms)
    return payload


def _cache_path(ticker: str) -> Path:
    safe = "".join(c for c in ticker.upper() if c.isalnum() or c in "._-")
    return _CACHE_DIR / f"{safe or 'UNKNOWN'}.json"


def load_trained_params(ticker: str) -> Optional[Dict[str, Any]]:
    p = _cache_path(ticker)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def simulate_trained_vqmc(
    historical_prices: List[float],
    ticker: str,
    horizon_days: int = 30,
    n_simulations: int = 5000,
    retrain_if_missing: bool = True,
    retrain_maxiter: int = 75,
    random_seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Simulate price paths using trained PQC shocks; return same shape as VQMC."""
    from qiskit.primitives import Sampler

    trained = load_trained_params(ticker)
    trained_just_now = False
    if trained is None:
        if not retrain_if_missing:
            raise RuntimeError(f"No trained ansatz for {ticker}; call train_ansatz first")
        trained = train_ansatz(historical_prices, ticker, maxiter=retrain_maxiter, seed=random_seed)
        trained_just_now = True

    params = np.asarray(trained["params"], dtype=float)
    sampler = Sampler(options={"shots": 4096})
    z_pool = _sample_z_scores(params, sampler, shots=4096)
    if len(z_pool) < 100:
        # Degenerate distribution — pad with Gaussians as safety net
        z_pool = np.concatenate([z_pool, np.random.standard_normal(size=1000)])

    prices = np.asarray(historical_prices, dtype=float)
    log_ret = np.diff(np.log(prices))
    mu_daily = float(np.mean(log_ret))
    sigma_daily = float(np.std(log_ret))
    S0 = float(prices[-1])
    T = int(horizon_days)

    rng = np.random.default_rng(random_seed)
    shocks = rng.choice(z_pool, size=(T, int(n_simulations)))
    # GBM using trained quantum shocks (now genuinely learned, not hand-set rotations)
    drift = mu_daily - 0.5 * sigma_daily ** 2
    diffusion = sigma_daily * shocks
    log_increments = drift + diffusion
    log_paths = np.cumsum(log_increments, axis=0)
    price_paths = np.zeros((T + 1, int(n_simulations)))
    price_paths[0] = S0
    price_paths[1:] = S0 * np.exp(log_paths)

    final_prices = price_paths[-1]
    total_ret = (final_prices - S0) / S0
    var_99 = float(np.percentile(total_ret, 1))
    var_95 = float(np.percentile(total_ret, 5))
    cvar_99 = float(total_ret[total_ret <= var_99].mean()) if np.any(total_ret <= var_99) else var_99

    return {
        "method": "Trained Variational Quantum Monte Carlo",
        "ansatz": {
            "n_qubits": _N_QUBITS,
            "n_layers": _N_LAYERS,
            "n_params": _N_PARAMS,
            "final_training_loss": float(trained["final_loss"]),
            "trained_moments": trained.get("trained_moments"),
            "target_moments": trained.get("target_moments"),
            "trained_at_ms": trained.get("trained_at_ms"),
            "trained_now": bool(trained_just_now),
        },
        "simulation_metadata": {
            "n_simulations": int(n_simulations),
            "horizon_days": T,
            "random_seed": random_seed,
        },
        "risk_metrics": {
            "VaR_99": var_99,
            "VaR_95": var_95,
            "CVaR_99": cvar_99,
            "best_case": float(np.max(total_ret)),
            "worst_case": float(np.min(total_ret)),
        },
        "paths_preview": price_paths[:, :100].T.tolist(),
        "final_distribution": {
            "bins": np.histogram(final_prices, bins=30)[1].tolist(),
            "counts": np.histogram(final_prices, bins=30)[0].tolist(),
        },
    }
