"""Quantum portfolio optimisation via QAOA with CVaR objective.

Formulates mean-variance asset selection as a QUBO and solves it on a
quantum sampler (local or IBM Runtime QPU). The selection problem:

    max   mu^T x  -  q * x^T Sigma x
    s.t.  sum(x) = budget,  x_i in {0, 1}

Returns the optimal subset of assets and an equally-weighted portfolio
over the selection. CVaR aggregation (Barkoutsos et al. 2020) improves
convergence on noisy samplers by optimising the tail of the objective
distribution rather than the mean.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.logic.quantum_backend import get_backend

logger = logging.getLogger(__name__)


def _returns_and_cov(data_map: Dict[str, pd.DataFrame], tickers: List[str]) -> tuple[np.ndarray, np.ndarray, List[str]]:
    """Build aligned daily log-return matrix, then annualised mu and Sigma."""
    frames = []
    kept: List[str] = []
    for t in tickers:
        df = data_map.get(t)
        if df is None or df.empty or "price" not in df.columns:
            continue
        s = pd.Series(df["price"].values, index=df.index).sort_index()
        log_ret = np.log(s / s.shift(1)).dropna()
        if len(log_ret) < 60:
            continue
        frames.append(log_ret.rename(t))
        kept.append(t)

    if len(kept) < 2:
        raise ValueError("Need at least 2 assets with sufficient history for quantum optimisation")

    returns_df = pd.concat(frames, axis=1, join="inner").dropna()
    mu = returns_df.mean().values * 252.0
    sigma = returns_df.cov().values * 252.0
    return mu, sigma, kept


def optimise_portfolio(
    data_map: Dict[str, pd.DataFrame],
    tickers: List[str],
    budget: Optional[int] = None,
    risk_factor: float = 0.5,
    reps: int = 3,
    cvar_alpha: float = 0.25,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Run QAOA portfolio selection and return a UI-friendly payload.

    budget       — number of assets to select (defaults to ceil(N/2))
    risk_factor  — q in the mean-variance objective (0 = pure return, 1 = pure risk)
    reps         — QAOA depth (p); higher = more expressive, slower
    cvar_alpha   — CVaR tail fraction for SamplingVQE-style aggregation
    """
    from qiskit_algorithms import QAOA
    from qiskit_algorithms.optimizers import COBYLA
    from qiskit_finance.applications.optimization import PortfolioOptimization
    from qiskit_optimization.algorithms import MinimumEigenOptimizer

    mu, sigma, kept = _returns_and_cov(data_map, tickers)
    n = len(kept)
    if budget is None:
        budget = max(1, (n + 1) // 2)
    budget = int(min(max(1, budget), n))

    backend = get_backend()
    logger.info("Quantum portfolio opt: backend=%s n=%d budget=%d reps=%d", backend.name, n, budget, reps)

    portfolio = PortfolioOptimization(
        expected_returns=mu,
        covariances=sigma,
        risk_factor=float(risk_factor),
        budget=budget,
    )
    qp = portfolio.to_quadratic_program()

    qaoa = QAOA(
        sampler=backend.sampler,
        optimizer=COBYLA(maxiter=250),
        reps=int(reps),
        aggregation=float(cvar_alpha),
    )
    if seed is not None:
        try:
            qaoa.random_seed = int(seed)
        except Exception:
            pass

    t0 = time.time()
    result = MinimumEigenOptimizer(qaoa).solve(qp)
    elapsed_ms = int((time.time() - t0) * 1000)

    selection = [int(round(v)) for v in result.x]
    selected_tickers = [t for t, bit in zip(kept, selection) if bit == 1]
    if not selected_tickers:
        raise RuntimeError("Quantum optimiser returned empty selection")

    weight = 1.0 / len(selected_tickers)
    weights = {t: weight for t in selected_tickers}

    sel_idx = np.array(selection, dtype=float)
    expected_return = float(mu @ sel_idx / max(1, sel_idx.sum()))
    variance = float((sel_idx @ sigma @ sel_idx) / max(1, sel_idx.sum() ** 2))
    volatility = float(np.sqrt(max(variance, 0.0)))
    sharpe = float(expected_return / volatility) if volatility > 1e-9 else None

    return {
        "method": "QAOA + CVaR (Qiskit Finance)",
        "backend": {
            "kind": backend.kind,
            "name": backend.name,
            "shots": backend.shots,
            "hardware": backend.hardware,
        },
        "universe": kept,
        "budget": budget,
        "risk_factor": float(risk_factor),
        "cvar_alpha": float(cvar_alpha),
        "qaoa_reps": int(reps),
        "selected_tickers": selected_tickers,
        "weights": weights,
        "expected_annual_return": expected_return,
        "expected_annual_volatility": volatility,
        "sharpe_estimate": sharpe,
        "objective_value": float(result.fval),
        "runtime_ms": elapsed_ms,
    }
