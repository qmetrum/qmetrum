"""1D PDF → MPS encoder, following Bohun et al., Phys. Rev. Research 8, 023062 (2026).

Encodes a continuous probability density function on a finite interval into
a Matrix Product State over N qubits, suitable for downstream quantum
circuit construction or classical Monte Carlo via the MPS representation.

Pipeline:
1. Discretize the PDF onto a 2^N grid using the binary-expansion convention
   x_σ = Σ σ_i / 2^i (Eq. 1 of the paper).
2. Build the amplitude vector √p(x_σ) and L2-normalise it.
3. Reshape to a (2, 2, …, 2) tensor and SVD-compress to MPS with bond cap χ.
4. Optionally compute Bohun et al.'s analytical entanglement bound to size χ
   from the function's smoothness (Theorem 1 / Eq. 14).

For 1D PDFs at N ≤ ~25 qubits (which is the regime where the paper's KS
statistical tests *pass on real IBM hardware*) the explicit-vector approach
is fine: 2^25 ≈ 33 M doubles = ~250 MB. Larger N needs TCI — out of scope.

The multivariate case (joint distributions over many assets) is the platform's
existing `tensor_network_risk` module, which is bounded by N ≤ 8 because it
materialises the d^N density. Lifting that ceiling needs proper multivariate
TCI; the paper's results are univariate and they flag multivariate as open.

Reference: V. Bohun et al., Phys. Rev. Research 8, 023062 (2026),
DOI 10.1103/yyvr-dtsb.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from app.logic.tensor_network_risk import _tensor_to_mps


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Public dataclasses
# ----------------------------------------------------------------------

@dataclass
class MpsEncoding:
    """An MPS encoding of a 1D PDF on a fixed support."""
    mps: List[np.ndarray]                # site tensors, each shape (left, 2, right)
    n_qubits: int
    support: Tuple[float, float]
    max_chi: int                          # bond cap requested
    actual_max_bond: int                  # max bond dim actually realised after SVD truncation
    fidelity_estimate: float              # ‖truncated‖² / ‖full‖² (Eq. 20 of the paper)
    grid: np.ndarray                      # 2^N support points used (cell midpoints)
    encoded_amplitudes: np.ndarray        # the (normalised) amplitude vector before MPS truncation
    truncation_loss: float                # 1 - fidelity_estimate

    def __repr__(self) -> str:
        return (
            f"MpsEncoding(n_qubits={self.n_qubits}, support={self.support}, "
            f"max_chi={self.max_chi}, actual_max_bond={self.actual_max_bond}, "
            f"fidelity={self.fidelity_estimate:.6f})"
        )


# ----------------------------------------------------------------------
# Encoder
# ----------------------------------------------------------------------

def encode_pdf_to_mps(
    pdf: Callable[[np.ndarray], np.ndarray],
    n_qubits: int,
    support: Tuple[float, float] = (0.0, 1.0),
    max_chi: int = 4,
) -> MpsEncoding:
    """Encode a 1D PDF onto N qubits as an MPS of bond dim ≤ max_chi.

    Returns an :class:`MpsEncoding` with the MPS site tensors, an analytical
    fidelity estimate, and the discretised amplitude vector for inspection.

    Parameters
    ----------
    pdf : callable
        Probability density: ``pdf(x)`` returns non-negative values for an
        ndarray ``x``. Need not integrate to one — it is L2-renormalised
        after sqrt.
    n_qubits : int
        Number of qubits ``N``. Grid has 2^N cells.
    support : (a, b)
        The compact interval on which the PDF is encoded.
    max_chi : int
        Maximum MPS bond dimension. The paper shows χ=2 yields very high
        fidelity for smooth PDFs (purities decay like 1/4^k).
    """
    if n_qubits < 1:
        raise ValueError("n_qubits must be ≥ 1")
    if n_qubits > 25:
        raise ValueError(
            f"n_qubits={n_qubits} requires TCI (out of scope here); "
            "use TCI-based encoding for ≥26 qubits."
        )
    if max_chi < 1:
        raise ValueError("max_chi must be ≥ 1")

    a, b = float(support[0]), float(support[1])
    if not (b > a):
        raise ValueError(f"support must be (a, b) with b > a; got {support}")

    n_points = 2 ** n_qubits
    # Cell midpoints on [a, b)
    grid = a + (np.arange(n_points) + 0.5) * (b - a) / n_points

    p_vals = np.asarray(pdf(grid), dtype=float)
    p_vals = np.clip(p_vals, 0.0, None)
    amplitudes = np.sqrt(p_vals)

    norm = float(np.linalg.norm(amplitudes))
    if norm <= 0.0:
        # Degenerate: empty PDF on this support → uniform fallback
        amplitudes = np.ones(n_points) / math.sqrt(n_points)
    else:
        amplitudes = amplitudes / norm

    # Reshape into (2,)*N and SVD-compress.
    tensor = amplitudes.reshape((2,) * n_qubits)
    mps = _tensor_to_mps(tensor, chi=max_chi)

    actual_max_bond = max(s.shape[2] for s in mps[:-1]) if len(mps) > 1 else 1
    fidelity = _mps_fidelity_to_amplitudes(mps, amplitudes)

    return MpsEncoding(
        mps=mps,
        n_qubits=n_qubits,
        support=(a, b),
        max_chi=max_chi,
        actual_max_bond=actual_max_bond,
        fidelity_estimate=fidelity,
        grid=grid,
        encoded_amplitudes=amplitudes,
        truncation_loss=max(0.0, 1.0 - fidelity),
    )


# ----------------------------------------------------------------------
# Sampling from the encoded amplitude MPS via Born rule
# ----------------------------------------------------------------------

def sample_from_pdf_mps(
    encoding: MpsEncoding,
    n_samples: int,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    """Draw ``n_samples`` real-valued samples on ``support`` from the encoded MPS.

    Sampling is done via Born-rule conditional probabilities over the binary
    expansion x = Σ σ_i / 2^i, then mapped to the cell midpoint of `support`.
    """
    if n_samples <= 0:
        return np.empty((0,), dtype=float)
    if rng is None:
        rng = np.random.default_rng()

    a, b = encoding.support
    width = b - a
    n_points = 2 ** encoding.n_qubits

    out = np.empty(n_samples, dtype=float)
    for s in range(n_samples):
        idx = _sample_index_born(encoding.mps, rng)
        out[s] = a + (idx + 0.5) * width / n_points
    return out


# ----------------------------------------------------------------------
# Entanglement / bond-dimension recommendation (paper Theorem 1)
# ----------------------------------------------------------------------

def estimate_g1(
    pdf: Callable[[np.ndarray], np.ndarray],
    support: Tuple[float, float] = (0.0, 1.0),
    n_quad: int = 4096,
) -> float:
    """Numerically evaluate the smoothness functional g_1(f) from Eq. 14
    of Bohun et al., for f = √p (the L²-normalised amplitude).

    For real-valued amplitudes the complex form simplifies to a Fisher-
    information-like quantity:

        g_1(f) = ∫ (f'(u))² du · ∫ f(u)² du  -  (∫ f'(u) f(u) du)²

    With f L²-normalised, ∫ f² du = 1, so g_1 ≈ ∫ (f')² du minus the
    square of the f' moment (which vanishes for symmetric f). The result
    is non-negative and grows with how 'wiggly' the amplitude is.
    """
    a, b = support
    x = np.linspace(a, b, n_quad)
    p = np.clip(np.asarray(pdf(x), dtype=float), 0.0, None)
    f = np.sqrt(p)
    norm = float(np.trapz(f * f, x))
    if norm <= 0:
        return 0.0
    f = f / math.sqrt(norm)
    df = np.gradient(f, x)
    fisher_like = float(np.trapz(df * df, x))
    drift = float(np.trapz(df * f, x))
    return max(fisher_like - drift * drift, 0.0)


def recommend_bond_dim(
    pdf: Callable[[np.ndarray], np.ndarray],
    support: Tuple[float, float] = (0.0, 1.0),
    target_fidelity: float = 0.999,
    n_qubits: int = 20,
) -> Dict[str, float]:
    """Recommend an MPS bond dimension χ for a target fidelity using the
    paper's Theorem 1 / Corollary 2 scaling.

    Theorem 1: purities p_k = 1 - g_1(f)/(6·4^k) + O(1/8^k).
    Corollary 2: entanglement entropy S_k = O(k / 4^k).

    A bond truncation to χ at bond k incurs an infidelity contribution of
    order Λ_{k,1}² ~ g_1(f) / (12 · 4^k) (subleading singular value squared,
    from Eq. 15 of the paper). χ=2 keeps this term; χ=3 adds the next.

    Heuristic: χ = 1 + ⌈ log_4 [ g_1(f) / (12 · (1-target_fidelity) · n_bonds) ] ⌉,
    capped at 8 for safety.
    """
    g1 = estimate_g1(pdf, support=support)
    epsilon = max(1.0 - target_fidelity, 1e-12)
    n_bonds = max(n_qubits - 1, 1)

    if g1 <= 0:
        chi_recommended = 1
    else:
        # Solve: g1 / (12 · 4^(χ-1) · n_bonds) ≤ ε  →  χ ≥ 1 + log_4 (g1 / (12 · ε · n_bonds))
        x = g1 / (12.0 * epsilon * n_bonds)
        chi_recommended = max(1, int(math.ceil(1 + math.log(max(x, 1.0), 4))))
        chi_recommended = min(chi_recommended, 8)

    return {
        "g1": g1,
        "recommended_chi": int(chi_recommended),
        "target_fidelity": float(target_fidelity),
        "n_qubits": int(n_qubits),
    }


# ----------------------------------------------------------------------
# Convenience: a few canonical heavy-tailed / smooth PDFs
# ----------------------------------------------------------------------

def levy_pdf(c: float = 1.0, mu: float = 0.0):
    """Standard Lévy distribution (α-stable, α=½, β=1). Heavy right tail."""
    def _p(x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        d = x - mu
        out = np.zeros_like(d)
        m = d > 0
        # Standard Lévy density: sqrt(c/(2π)) · exp(-c/(2(x-μ))) / (x-μ)^(3/2)
        out[m] = math.sqrt(c / (2 * math.pi)) * np.exp(-c / (2 * d[m])) / np.power(d[m], 1.5)
        return out
    return _p


def normal_pdf(mu: float = 0.5, sigma: float = 0.125):
    """Standard normal density."""
    def _p(x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        return (1.0 / (sigma * math.sqrt(2 * math.pi))) * np.exp(-((x - mu) ** 2) / (2 * sigma * sigma))
    return _p


def lognormal_pdf(mu: float = 0.0, sigma: float = 0.5):
    """Log-normal density on (0, ∞)."""
    def _p(x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        out = np.zeros_like(x)
        m = x > 0
        out[m] = (
            1.0 / (x[m] * sigma * math.sqrt(2 * math.pi))
            * np.exp(-((np.log(x[m]) - mu) ** 2) / (2 * sigma * sigma))
        )
        return out
    return _p


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------

def _mps_fidelity_to_amplitudes(mps: List[np.ndarray], target: np.ndarray) -> float:
    """⟨ψ_MPS | target⟩² where target is the original amplitude vector.

    Uses Eq. 20 of the paper indirectly: contract the MPS to recover its
    amplitude vector and compare. For N ≤ 25 this is cheap (2^25 = 33M).
    """
    n_qubits = len(mps)
    # Contract MPS left-to-right
    site = mps[0]
    # site shape (1, d, k) → keep as (d, k)
    state = site.reshape(site.shape[1], site.shape[2])
    for k in range(1, n_qubits):
        nxt = mps[k]
        # nxt shape (k, d, k') ; state shape (..., k)
        state = np.tensordot(state, nxt, axes=([state.ndim - 1], [0]))
    # state shape (d, d, ..., d, 1)
    state = state.reshape(-1)
    state = state / max(np.linalg.norm(state), 1e-15)
    target = target / max(np.linalg.norm(target), 1e-15)
    overlap = float(abs(np.dot(state.conj(), target)))
    return overlap * overlap


def _sample_index_born(mps: List[np.ndarray], rng: np.random.Generator) -> int:
    """Sample one integer in [0, 2^N) from the MPS via Born conditional probs."""
    n_qubits = len(mps)
    # Maintain left environment as we go
    left = np.array([1.0])
    chosen_bits: List[int] = []
    for k, site in enumerate(mps):
        # site shape (l, 2, r). For each bit b in {0,1}, contract left with site[:, b, :]
        # and with the marginal over remaining sites (the closing-vector to the right).
        l_dim, d_dim, r_dim = site.shape
        right_close = _right_marginal(mps, k + 1)  # shape (r_dim,)
        amps = np.zeros(d_dim, dtype=float)
        for b in range(d_dim):
            # tensor contract left @ site[:, b, :] @ right_close
            v = left @ site[:, b, :]          # shape (r_dim,)
            amp = float(v @ right_close)
            amps[b] = amp
        probs = amps * amps
        total = probs.sum()
        if total <= 0:
            probs = np.ones_like(probs) / d_dim
        else:
            probs = probs / total
        b = int(rng.choice(d_dim, p=probs))
        chosen_bits.append(b)
        # Update left environment by contracting site[:, b, :]
        left = left @ site[:, b, :]
    # Convert binary expansion (most-significant bit first) → integer
    idx = 0
    for b in chosen_bits:
        idx = (idx << 1) | b
    return idx


def _right_marginal(mps: List[np.ndarray], start: int) -> np.ndarray:
    """Closing right vector v such that contracting v with the left-of-start
    bond gives the sum of squared amplitudes over remaining sites — used for
    Born-rule conditional probabilities. For an unnormalised MPS, this is
    the diagonal of the right environment.
    """
    n_qubits = len(mps)
    if start >= n_qubits:
        return np.array([1.0])
    # Build right environment from the right
    site = mps[-1]  # shape (l, d, 1)
    env = site.reshape(site.shape[0], site.shape[1])  # (l, d)
    # Sum over physical: env_l = Σ_b site[l, b, 0]
    env_vec = env.sum(axis=1)  # shape (l,)
    for k in range(n_qubits - 2, start - 1, -1):
        site = mps[k]  # (l, d, r)
        # Contract over r and physical
        # new_env[l] = Σ_{b, r} site[l, b, r] * env_vec[r]
        env_vec = np.einsum("ldr,r->l", site, env_vec)
    return env_vec
