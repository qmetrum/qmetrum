"""Quantum-information systemic-risk metrics.

Two complementary entropies, both classically computable but grounded in
quantum-information theory:

1. **Correlation-matrix von Neumann entropy.** Normalise the portfolio
   correlation (or covariance) matrix as a density operator rho = C / tr(C)
   and compute S(rho) = -sum(lambda_i log lambda_i). High entropy means
   risk eigenstructure is spread across many modes (diversified);
   low entropy means one or two factors dominate (systemic concentration).
   This is a spectral-diversity analogue of the participation ratio,
   expressed as a genuine quantum entropy.

2. **Portfolio entanglement entropy.** Amplitude-encode the weight vector
   onto log2(N) qubits, treat it as a pure state, and compute the von
   Neumann entropy of the reduced density matrix over a bipartition of
   the qubits. This measures how "entangled" the weights are across a
   partition of the asset register — a genuinely quantum metric with no
   classical analogue.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _von_neumann_entropy(eigvals: np.ndarray) -> float:
    """Shannon entropy of eigenvalues, in nats, clamped for numerical safety."""
    w = np.clip(eigvals.real, 1e-12, 1.0)
    w = w / w.sum()
    return float(-np.sum(w * np.log(w)))


def correlation_entropy(data_map: Dict[str, pd.DataFrame], tickers: List[str]) -> Dict[str, Any]:
    """Von Neumann entropy of the asset correlation matrix as a density operator."""
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
        raise ValueError("Need at least 2 assets with sufficient history for correlation entropy")

    returns_df = pd.concat(frames, axis=1, join="inner").dropna()
    corr = returns_df.corr().values
    # Normalise correlation matrix as a density operator: trace = N, so divide by N.
    rho = corr / np.trace(corr)
    eigvals = np.linalg.eigvalsh(rho)
    S = _von_neumann_entropy(eigvals)
    N = len(kept)
    S_max = math.log(N)  # maximum entropy = uniform eigenvalues = fully diversified
    diversification_ratio = S / S_max if S_max > 0 else 0.0

    # Concentration eigenvalue — dominant factor share (classical "systemic risk" sanity check)
    dominant = float(np.max(eigvals).real)

    return {
        "metric": "correlation_von_neumann_entropy",
        "n_assets": N,
        "tickers": kept,
        "entropy_nats": S,
        "entropy_max": S_max,
        "diversification_ratio": float(diversification_ratio),
        "dominant_eigenvalue": dominant,
        "interpretation": (
            "High ratio → risk spread across many independent modes (diversified). "
            "Low ratio → one factor dominates (systemic concentration)."
        ),
    }


def _pad_to_power_of_two(weights: np.ndarray) -> np.ndarray:
    """Zero-pad weights so length is a power of two for amplitude encoding."""
    n = len(weights)
    m = 1 << max(1, (n - 1).bit_length())
    if m == n:
        return weights
    padded = np.zeros(m, dtype=float)
    padded[:n] = weights
    return padded


def portfolio_entanglement_entropy(weights: Dict[str, float]) -> Dict[str, Any]:
    """Entanglement entropy of an amplitude-encoded weight state across a balanced bipartition."""
    tickers = list(weights.keys())
    w = np.array([float(weights[t]) for t in tickers], dtype=float)
    w = np.clip(w, 0.0, None)
    if w.sum() <= 0:
        raise ValueError("Weights must be non-negative and sum to a positive number")
    w = w / w.sum()

    # Amplitude encoding: psi_i = sqrt(w_i)
    amplitudes = np.sqrt(_pad_to_power_of_two(w))
    dim = len(amplitudes)
    n_qubits = int(math.log2(dim))
    # Balanced bipartition: first half vs second half of qubits
    nA = n_qubits // 2
    nB = n_qubits - nA
    dA, dB = 1 << nA, 1 << nB

    psi = amplitudes.reshape(dA, dB)
    # Reduced density matrix on subsystem A: rho_A = psi psi^\dagger traced over B
    rho_A = psi @ psi.conj().T
    eigvals = np.linalg.eigvalsh(rho_A)
    S = _von_neumann_entropy(eigvals)
    S_max = math.log(min(dA, dB))

    return {
        "metric": "portfolio_entanglement_entropy",
        "tickers": tickers,
        "n_qubits": n_qubits,
        "bipartition": {"qubits_A": nA, "qubits_B": nB},
        "entropy_nats": S,
        "entropy_max": S_max,
        "entanglement_ratio": float(S / S_max) if S_max > 0 else 0.0,
        "interpretation": (
            "High ratio → weights highly entangled across the asset bipartition (spread). "
            "Low ratio → concentrated in few eigenmodes of the bipartition."
        ),
    }


def systemic_risk_report(data_map: Dict[str, pd.DataFrame], weights: Dict[str, float]) -> Dict[str, Any]:
    """Bundle both metrics plus a composite systemic-risk score."""
    tickers = list(weights.keys())
    corr = correlation_entropy(data_map, tickers)
    ent = portfolio_entanglement_entropy(weights)

    # Composite: higher = more diversified (less systemic risk)
    composite = 0.5 * corr["diversification_ratio"] + 0.5 * ent["entanglement_ratio"]
    return {
        "composite_score": float(composite),
        "composite_interpretation": (
            "Composite of spectral diversification and weight-state entanglement. "
            "Range 0..1; lower values indicate higher systemic concentration."
        ),
        "correlation_entropy": corr,
        "portfolio_entanglement_entropy": ent,
    }
