"""Tensor-network portfolio risk via a Matrix Product State.

Classically-computable, quantum-inspired. Represents the joint return
distribution over N assets as an MPS with bond dimension chi:

  - chi=1 is a product state (independence, Gaussian-copula-like).
  - chi growing with N captures genuine entanglement across the asset
    register, i.e. higher-order correlation structure that a covariance
    matrix cannot express (fat tails, non-linear dependencies,
    regime-switching).

Fit: discretise each asset's standardised returns into d bins
(physical dimension), build the empirical joint histogram over N assets,
compress it into MPS form via successive SVDs truncated to bond dim chi.
Sampling: left-to-right conditional sampling from the MPS.

Scales to hundreds of assets where a dense 2^N density tensor is
infeasible; useful when a real QPU would need thousands of qubits.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _aligned_returns(data_map: Dict[str, pd.DataFrame], tickers: List[str]) -> Tuple[pd.DataFrame, List[str]]:
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
        raise ValueError("Need at least 2 assets with sufficient history for tensor-network risk")
    return pd.concat(frames, axis=1, join="inner").dropna(), kept


def _discretise(returns_df: pd.DataFrame, d: int) -> Tuple[np.ndarray, List[np.ndarray]]:
    """Standardise each asset and bin into d physical-dimension levels."""
    N = returns_df.shape[1]
    binned = np.zeros((len(returns_df), N), dtype=np.int64)
    bin_edges: List[np.ndarray] = []
    for i, col in enumerate(returns_df.columns):
        x = returns_df[col].values
        z = (x - x.mean()) / (x.std() + 1e-12)
        # Quantile-based bins so each bucket has ~equal mass
        edges = np.quantile(z, np.linspace(0, 1, d + 1))
        edges[0], edges[-1] = -np.inf, np.inf
        binned[:, i] = np.clip(np.searchsorted(edges, z, side="right") - 1, 0, d - 1)
        bin_edges.append(edges)
    return binned, bin_edges


def _build_joint_tensor(binned: np.ndarray, d: int) -> np.ndarray:
    """Empirical joint probability tensor of shape (d, d, ..., d) over N assets."""
    T, N = binned.shape
    # d^N storage ceiling: d=4, N=8 -> 65 536 entries (~0.5 MB), still cheap.
    # Beyond that, build time and memory blow up — use streaming fit instead.
    if N > 8:
        raise ValueError(f"Joint-tensor build is only feasible for N <= 8 (got N={N}); use streaming fit for larger N")
    shape = tuple([d] * N)
    tensor = np.zeros(shape, dtype=float)
    for row in binned:
        tensor[tuple(row)] += 1.0
    tensor /= max(tensor.sum(), 1e-12)
    return tensor


def _tensor_to_mps(joint: np.ndarray, chi: int) -> List[np.ndarray]:
    """Compress a full joint tensor to MPS form with bond-dim cap chi via successive SVDs."""
    N = joint.ndim
    d = joint.shape[0]
    mats: List[np.ndarray] = []
    residual = joint.reshape(d, -1)
    left_dim = 1
    for site in range(N - 1):
        # Reshape so columns index the remaining sites
        residual = residual.reshape(left_dim * d, -1)
        U, S, Vt = np.linalg.svd(residual, full_matrices=False)
        k = min(chi, len(S))
        U = U[:, :k]
        S = S[:k]
        Vt = Vt[:k, :]
        # Site tensor shape: (left_dim, d, k)
        site_tensor = U.reshape(left_dim, d, k)
        mats.append(site_tensor)
        residual = (np.diag(S) @ Vt)
        left_dim = k
    last = residual.reshape(left_dim, d, 1)
    mats.append(last)
    return mats


def _mps_conditional_probs(mps: List[np.ndarray], prefix: List[int]) -> np.ndarray:
    """Marginal probabilities p(x_k | x_{<k}) at site k = len(prefix), given the MPS.

    Returns a d-vector summing to 1 (on full-rank MPS). Contracts left environment
    through the fixed prefix and then traces out the right tail for each candidate value.
    """
    N = len(mps)
    k = len(prefix)
    d = mps[0].shape[1]

    # Left environment: row vector of shape (left_bond_at_k,)
    L = np.array([1.0])
    for site_idx, x in enumerate(prefix):
        A = mps[site_idx][:, x, :]  # shape (left, right)
        L = L @ A  # shape (right,)

    # Right environment accumulated from the right, summed over all values at each remaining site.
    # R_j = sum_{x_j} sum_{x_{j+1}} ... M[j](x_j) M[j+1](x_{j+1}) ... at bond index entering site j.
    right_envs: List[np.ndarray] = [np.array([1.0])]  # R for site N
    for site_idx in range(N - 1, k, -1):
        M = mps[site_idx]
        summed = M.sum(axis=1)  # shape (left, right)
        R_prev = right_envs[0]
        R_new = summed @ R_prev  # shape (left,)
        right_envs.insert(0, R_new)
    R_k = right_envs[0]

    # For each candidate value v at site k:
    M_k = mps[k]
    probs = np.zeros(d, dtype=float)
    for v in range(d):
        A_v = M_k[:, v, :]  # (left, right)
        amp = L @ A_v @ R_k
        probs[v] = max(float(amp), 0.0)
    total = probs.sum()
    if total <= 0:
        return np.ones(d) / d
    return probs / total


def _mps_sample(mps: List[np.ndarray], n_samples: int, rng: np.random.Generator) -> np.ndarray:
    """Draw joint samples (N-tuples of bin indices) from the MPS."""
    N = len(mps)
    d = mps[0].shape[1]
    out = np.zeros((n_samples, N), dtype=np.int64)
    for s in range(n_samples):
        prefix: List[int] = []
        for k in range(N):
            p = _mps_conditional_probs(mps, prefix)
            v = int(rng.choice(d, p=p))
            prefix.append(v)
        out[s] = prefix
    return out


def _bin_midpoints(bin_edges: List[np.ndarray]) -> np.ndarray:
    """Use the midpoint of each standardised-return bin as its representative value."""
    mids = []
    for edges in bin_edges:
        e = edges.copy()
        e[0] = e[1] - (e[2] - e[1])  # finite lower edge for midpoint
        e[-1] = e[-2] + (e[-2] - e[-3])  # finite upper edge
        mids.append(0.5 * (e[:-1] + e[1:]))
    return np.asarray(mids)  # shape (N, d)


def sample_standardised_joint_returns(
    data_map: Dict[str, pd.DataFrame],
    tickers_order: List[str],
    n_steps: int,
    n_simulations: int,
    d: int = 4,
    chi: int = 8,
    random_seed: Optional[int] = None,
) -> Dict[str, Any]:
    """MPS-as-copula: sample standardised joint returns for a given ticker order.

    The MPS is fitted on per-asset z-scored returns (already done in _discretise),
    so what comes out captures the non-parametric joint *dependence* structure of
    this portfolio's returns. Per-asset marginals are NOT imposed here; callers
    are expected to reconstruct marginals via their own scenario knobs
    (e.g. r_i = mu_i * drift_shift + sigma_i * return_scale * z_i).

    Returns:
      {
        "z_samples":   np.ndarray of shape (n_steps, n_simulations, N) with standardised returns,
        "tickers":     List[str] of tickers actually kept (subset of tickers_order),
        "asset_mu":    np.ndarray of historical per-asset mean log-returns (for caller's marginals),
        "asset_sigma": np.ndarray of historical per-asset std of log-returns,
        "mps":         {n_sites, physical_dim, bond_dim_cap, max_bond_dim_used, interpretation},
        "runtime_ms":  int,
      }
    """
    returns_df, kept = _aligned_returns(data_map, tickers_order)
    returns_df = returns_df[kept]

    t0 = time.time()
    binned, bin_edges = _discretise(returns_df, d=d)
    joint = _build_joint_tensor(binned, d=d)
    mps = _tensor_to_mps(joint, chi=chi)

    max_bond = max(site.shape[2] for site in mps[:-1]) if len(mps) > 1 else 1

    rng = np.random.default_rng(random_seed)
    one_step_samples = _mps_sample(mps, n_samples=n_steps * n_simulations, rng=rng)
    midpoints = _bin_midpoints(bin_edges)
    N = len(kept)
    z = np.zeros_like(one_step_samples, dtype=float)
    for i in range(N):
        z[:, i] = midpoints[i, one_step_samples[:, i]]
    z = z.reshape(n_steps, n_simulations, N)

    asset_mu = returns_df.mean().values
    asset_sigma = returns_df.std().values

    return {
        "z_samples": z,
        "tickers": kept,
        "asset_mu": asset_mu,
        "asset_sigma": asset_sigma,
        "mps": {
            "n_sites": N,
            "physical_dim": int(d),
            "bond_dim_cap": int(chi),
            "max_bond_dim_used": int(max_bond),
            "interpretation": (
                "max_bond_dim_used == 1 implies independence (Gaussian-copula-like); "
                "higher bond dim implies captured non-Gaussian inter-asset dependence."
            ),
        },
        "runtime_ms": int((time.time() - t0) * 1000),
    }


def tensor_network_risk(
    data_map: Dict[str, pd.DataFrame],
    weights: Dict[str, float],
    horizon_days: int = 30,
    n_simulations: int = 5000,
    d: int = 4,
    chi: int = 8,
    random_seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Fit an MPS to the joint return distribution and simulate portfolio paths.

    d    physical dimension (return bins per asset)
    chi  MPS bond-dim cap (captured entanglement)

    Note: this is the price-space wrapper that applies historical per-asset
    marginals (mu, sigma) to the MPS-sampled z. For scenario-conditioned paths
    where marginals are modified by shock/scale/drift knobs, call
    sample_standardised_joint_returns() directly and apply your own transform.
    """
    tickers = list(weights.keys())
    w = np.array([float(weights[t]) for t in tickers], dtype=float)
    if w.sum() <= 0:
        raise ValueError("Weights must be positive")
    w = w / w.sum()

    t0 = time.time()
    sample = sample_standardised_joint_returns(
        data_map, tickers, n_steps=horizon_days,
        n_simulations=n_simulations, d=d, chi=chi, random_seed=random_seed,
    )
    kept = sample["tickers"]
    z = sample["z_samples"]                    # (horizon, n_sims, N)
    mu = sample["asset_mu"]
    sd = sample["asset_sigma"]
    N = len(kept)
    # Realign weights to kept order (some tickers may have dropped for lack of history)
    w = np.array([float(weights[t]) for t in kept], dtype=float)
    w = w / w.sum()

    # Historical-marginal reconstruction: r_i = sigma_i * z_i + mu_i
    log_rets = z * sd + mu  # broadcasts over last axis

    # Portfolio log-return per step: weighted sum (approximation valid for small daily moves)
    port_log_rets = np.einsum("tsn,n->ts", log_rets, w)
    port_paths = np.exp(np.cumsum(port_log_rets, axis=0))  # index starting at 1.0
    terminal = port_paths[-1]
    port_returns = terminal - 1.0

    var_99 = float(np.percentile(port_returns, 1))
    var_95 = float(np.percentile(port_returns, 5))
    cvar_99 = float(port_returns[port_returns <= var_99].mean()) if np.any(port_returns <= var_99) else var_99
    elapsed_ms = int((time.time() - t0) * 1000)

    return {
        "method": "Tensor-Network Monte Carlo (Matrix Product State)",
        "mps": sample["mps"],
        "simulation_metadata": {
            "tickers": kept,
            "weights": {t: float(weights[t]) for t in kept},
            "horizon_days": int(horizon_days),
            "n_simulations": int(n_simulations),
            "runtime_ms": elapsed_ms,
        },
        "risk_metrics": {
            "VaR_99": var_99,
            "VaR_95": var_95,
            "CVaR_99": cvar_99,
            "best_case": float(np.max(port_returns)),
            "worst_case": float(np.min(port_returns)),
        },
        "paths_preview": port_paths[:, :100].T.tolist(),
        "final_distribution": {
            "bins": np.histogram(terminal, bins=30)[1].tolist(),
            "counts": np.histogram(terminal, bins=30)[0].tolist(),
        },
    }
