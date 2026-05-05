"""Adversarial scenario discovery benchmark.

Compares three approaches for finding the worst-case shock vector that
minimises portfolio CVaR over a fixed horizon:

  1. Classical gradient descent (L-BFGS-B with finite differences, 50
     restarts per trial). Note: a Gumbel-softmax differentiable path
     through the MPS sampler would be a stronger classical baseline;
     if results are ambiguous, that should be implemented as a tiebreaker.
  2. QAOA on a discretised shock-grid QUBO.
  3. Grover amplitude amplification on the same discrete grid.

All three solvers call the same canonical objective function
`adversarial_cvar(shock_vector, problem)`. QAOA and Grover wrap it via
pre-evaluation on the discrete grid; GD calls it directly on continuous
shock vectors.

Benchmark matrix:
  (3 solvers) x (universe sizes: 4, 6 assets) x (shock-grid resolutions: 3, 5)
  x 20 random seeds per cell.

Per trial: solver, universe, grid resolution, wall-clock, n_evaluations,
best CVaR (canonical), shock vector, global-optimum flag.

Decision rule: quantum ships as quantum only if it finds strictly lower
terminal CVaR than GD-50-restarts, beyond the 1% tolerance, at some
universe size with non-trivial frequency across seeds.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from itertools import product as iterproduct
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.logic.tensor_network_risk import (
    sample_standardised_joint_returns,
    _aligned_returns,
)

logger = logging.getLogger(__name__)


# =========================================================================
# Shared problem + canonical objective
# =========================================================================

@dataclass
class AdversarialProblem:
    tickers: List[str]
    weights: np.ndarray          # (N,)
    asset_mu: np.ndarray         # (N,)
    asset_sigma: np.ndarray      # (N,)
    z_samples: np.ndarray        # (T, S, N) pre-sampled MPS z-scores
    horizon: int
    n_sims: int
    last_price: float
    shock_bounds: np.ndarray     # (N,) max |shock| in sigma units per asset


def build_problem(
    data_map: Dict[str, pd.DataFrame],
    weights: Dict[str, float],
    horizon_days: int = 30,
    n_sims: int = 500,
    shock_sigma: float = 3.0,
    mps_d: int = 4,
    mps_chi: int = 8,
) -> AdversarialProblem:
    tickers = list(weights.keys())

    sample = sample_standardised_joint_returns(
        data_map, tickers, n_steps=horizon_days, n_simulations=n_sims,
        d=mps_d, chi=mps_chi, random_seed=42,
    )
    kept = sample["tickers"]
    w = np.array([float(weights.get(t, 0.0)) for t in kept], dtype=float)
    w = w / w.sum()

    last_prices = {t: float(data_map[t]["price"].iloc[-1]) for t in kept}
    port_last = sum(last_prices[t] * w[i] for i, t in enumerate(kept))

    return AdversarialProblem(
        tickers=kept,
        weights=w,
        asset_mu=sample["asset_mu"],
        asset_sigma=sample["asset_sigma"],
        z_samples=sample["z_samples"],
        horizon=horizon_days,
        n_sims=n_sims,
        last_price=port_last,
        shock_bounds=np.full(len(kept), shock_sigma),
    )


def adversarial_cvar(
    shock_vector: np.ndarray,
    problem: AdversarialProblem,
    alpha: float = 0.05,
) -> float:
    """Canonical objective: CVaR_alpha of terminal portfolio return under shock.

    shock_vector: (N,) in sigma units. Day-0 per-asset price change = exp(s_i * sigma_i) - 1.
    Returns a scalar (negative = loss). Lower is worse.

    This is THE function all solvers optimise. No solver-specific CVaR reimplementation.
    """
    z = problem.z_samples
    mu, sd, w = problem.asset_mu, problem.asset_sigma, problem.weights

    shock_returns = np.exp(shock_vector * sd) - 1.0
    shock_port = float(np.dot(shock_returns, w))
    base = problem.last_price * (1.0 + shock_port)

    log_rets = mu + sd * z
    port_log_rets = np.einsum("tsn,n->ts", log_rets, w)
    terminal = base * np.exp(np.sum(port_log_rets, axis=0))
    total_return = terminal / problem.last_price - 1.0

    cutoff = int(max(1, math.floor(alpha * len(total_return))))
    return float(np.mean(np.sort(total_return)[:cutoff]))


def _smoothed_cvar(
    shock_vector: np.ndarray,
    problem: AdversarialProblem,
    alpha: float = 0.05,
    tau: float = 0.01,
) -> float:
    """Softplus-smoothed CVaR for GD optimisation. Converges to true CVaR as tau -> 0."""
    z = problem.z_samples
    mu, sd, w = problem.asset_mu, problem.asset_sigma, problem.weights

    shock_returns = np.exp(shock_vector * sd) - 1.0
    shock_port = float(np.dot(shock_returns, w))
    base = problem.last_price * (1.0 + shock_port)

    log_rets = mu + sd * z
    port_log_rets = np.einsum("tsn,n->ts", log_rets, w)
    terminal = base * np.exp(np.sum(port_log_rets, axis=0))
    total_return = terminal / problem.last_price - 1.0

    var_level = float(np.percentile(total_return, alpha * 100))
    excess = var_level - total_return
    soft = tau * np.log1p(np.exp(excess / tau))
    return float(var_level - np.mean(soft) / alpha)


# =========================================================================
# Discrete grid utilities (shared by QAOA + Grover)
# =========================================================================

def _build_grid(problem: AdversarialProblem, n_levels: int) -> Tuple[List[Tuple[int, ...]], np.ndarray, np.ndarray]:
    """Return (grid_indices, levels_per_asset, costs).

    grid_indices: list of N-tuples of level indices.
    levels_per_asset: (N, n_levels) shock values in sigma units.
    costs: (n_states,) canonical CVaR for each grid point.
    """
    N = len(problem.tickers)
    levels_per_asset = np.linspace(
        -problem.shock_bounds, problem.shock_bounds, n_levels,
    ).T  # (N, n_levels)

    grid_indices = list(iterproduct(range(n_levels), repeat=N))
    costs = np.zeros(len(grid_indices))
    for idx, combo in enumerate(grid_indices):
        shock = np.array([levels_per_asset[i, combo[i]] for i in range(N)])
        costs[idx] = adversarial_cvar(shock, problem)
    return grid_indices, levels_per_asset, costs


def _shock_from_combo(combo: Tuple[int, ...], levels_per_asset: np.ndarray) -> np.ndarray:
    return np.array([levels_per_asset[i, combo[i]] for i in range(len(combo))])


# =========================================================================
# Solver 1: gradient descent (classical baseline)
# =========================================================================

def solve_gd(
    problem: AdversarialProblem,
    n_restarts: int = 50,
    maxiter: int = 100,
    seed: int = 42,
) -> Dict[str, Any]:
    from scipy.optimize import minimize

    N = len(problem.tickers)
    bounds = [(-float(b), float(b)) for b in problem.shock_bounds]
    rng = np.random.default_rng(seed)
    evals = 0

    def obj(x):
        nonlocal evals
        evals += 1
        return _smoothed_cvar(x, problem)

    best_val = float("inf")
    best_x = np.zeros(N)
    all_vals: List[float] = []
    t0 = time.time()

    for _ in range(n_restarts):
        x0 = rng.uniform(-problem.shock_bounds, problem.shock_bounds)
        res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": maxiter, "ftol": 1e-8})
        val = float(res.fun)
        all_vals.append(val)
        if val < best_val:
            best_val = val
            best_x = res.x.copy()

    elapsed_ms = int((time.time() - t0) * 1000)
    exact = adversarial_cvar(best_x, problem)
    return {
        "method": "gradient_descent",
        "best_cvar": exact,
        "best_shock": best_x.tolist(),
        "n_restarts": n_restarts,
        "n_evaluations": evals,
        "best_of_n": float(min(all_vals)),
        "median_of_n": float(np.median(all_vals)),
        "std_of_n": float(np.std(all_vals)),
        "runtime_ms": elapsed_ms,
        "seed": seed,
    }


# =========================================================================
# Solver 2: QAOA
# =========================================================================

def solve_qaoa(
    problem: AdversarialProblem,
    n_levels: int = 3,
    reps: int = 2,
    seed: int = 42,
) -> Dict[str, Any]:
    from qiskit_algorithms import QAOA
    from qiskit_algorithms.optimizers import COBYLA
    from qiskit.primitives import Sampler
    from qiskit_optimization import QuadraticProgram
    from qiskit_optimization.algorithms import MinimumEigenOptimizer

    grid_indices, levels, costs = _build_grid(problem, n_levels)
    n_states = len(grid_indices)
    N = len(problem.tickers)

    t0 = time.time()
    qp = QuadraticProgram()
    for i in range(n_states):
        qp.binary_var(f"s{i}")
    qp.minimize(linear={f"s{i}": float(costs[i]) for i in range(n_states)})
    qp.linear_constraint(
        linear={f"s{i}": 1 for i in range(n_states)},
        sense="==", rhs=1, name="one_hot",
    )

    sampler = Sampler(options={"shots": 2048})
    qaoa = QAOA(sampler=sampler, optimizer=COBYLA(maxiter=200), reps=reps)
    try:
        qaoa.random_seed = int(seed)
    except Exception:
        pass
    result = MinimumEigenOptimizer(qaoa).solve(qp)

    selected_idx = int(np.argmax([round(v) for v in result.x]))
    best_shock = _shock_from_combo(grid_indices[selected_idx], levels)
    best_cvar = adversarial_cvar(best_shock, problem)

    brute_idx = int(np.argmin(costs))
    brute_cvar = float(costs[brute_idx])

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "method": "qaoa",
        "best_cvar": best_cvar,
        "best_shock": best_shock.tolist(),
        "n_levels": n_levels,
        "n_states": n_states,
        "n_evaluations": n_states,
        "brute_force_cvar": brute_cvar,
        "found_global": bool(abs(best_cvar - brute_cvar) < abs(brute_cvar) * 0.01),
        "runtime_ms": elapsed_ms,
        "seed": seed,
    }


# =========================================================================
# Solver 3: Grover
# =========================================================================

def solve_grover(
    problem: AdversarialProblem,
    n_levels: int = 3,
    bisection_steps: int = 8,
    seed: int = 42,
) -> Dict[str, Any]:
    from qiskit import QuantumCircuit
    from qiskit.primitives import Sampler
    from qiskit_algorithms import AmplificationProblem, Grover

    grid_indices, levels, costs = _build_grid(problem, n_levels)
    n_states = len(grid_indices)
    n_qubits = max(1, int(np.ceil(np.log2(max(n_states, 2)))))
    N = len(problem.tickers)

    t0 = time.time()
    lo, hi = float(costs.min()), float(costs.max())
    best_idx = int(np.argmin(costs))  # fallback
    sampler = Sampler(options={"shots": 1024})
    grover_calls = 0

    for step in range(bisection_steps):
        threshold = (lo + hi) / 2.0
        good = [i for i, c in enumerate(costs) if c <= threshold]
        if not good:
            lo = threshold
            continue

        oracle = QuantumCircuit(n_qubits)
        for state_idx in good:
            bits = format(state_idx, f"0{n_qubits}b")
            for i, b in enumerate(bits):
                if b == "0":
                    oracle.x(i)
            if n_qubits == 1:
                oracle.z(0)
            else:
                oracle.h(n_qubits - 1)
                oracle.mcx(list(range(n_qubits - 1)), n_qubits - 1)
                oracle.h(n_qubits - 1)
            for i, b in enumerate(bits):
                if b == "0":
                    oracle.x(i)

        try:
            prob = AmplificationProblem(
                oracle=oracle,
                is_good_state=lambda bs: int(bs, 2) < n_states and costs[int(bs, 2)] <= threshold,
            )
            grover = Grover(sampler=sampler, iterations=1)
            res = grover.amplify(prob)
            grover_calls += 1
            if res.top_measurement is not None:
                measured = int(res.top_measurement, 2)
                if measured < n_states and costs[measured] <= threshold:
                    best_idx = measured
                    hi = threshold
                else:
                    lo = threshold
            else:
                lo = threshold
        except Exception as e:
            logger.debug("Grover step %d: %s", step, e)
            lo = threshold

    best_shock = _shock_from_combo(grid_indices[best_idx], levels)
    best_cvar = adversarial_cvar(best_shock, problem)
    brute_idx = int(np.argmin(costs))
    brute_cvar = float(costs[brute_idx])

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "method": "grover",
        "best_cvar": best_cvar,
        "best_shock": best_shock.tolist(),
        "n_levels": n_levels,
        "n_states": n_states,
        "n_evaluations": n_states + grover_calls,
        "grover_calls": grover_calls,
        "brute_force_cvar": brute_cvar,
        "found_global": bool(abs(best_cvar - brute_cvar) < abs(brute_cvar) * 0.01),
        "runtime_ms": elapsed_ms,
        "seed": seed,
    }


# =========================================================================
# Benchmark runner
# =========================================================================

@dataclass
class BenchmarkCell:
    solver: str
    universe: str
    n_assets: int
    n_levels: int
    seed: int
    best_cvar: float
    best_shock: List[float]
    n_evaluations: int
    runtime_ms: int
    found_global: bool = False
    extra: Dict[str, Any] = None  # type: ignore[assignment]

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "solver": self.solver,
            "universe": self.universe,
            "n_assets": self.n_assets,
            "n_levels": self.n_levels,
            "seed": self.seed,
            "best_cvar": self.best_cvar,
            "best_shock": self.best_shock,
            "n_evaluations": self.n_evaluations,
            "runtime_ms": self.runtime_ms,
            "found_global": self.found_global,
        }
        if self.extra:
            d["extra"] = self.extra
        return d


def run_adversarial_benchmark(
    data_map: Dict[str, pd.DataFrame],
    universes: Dict[str, Dict[str, float]],
    n_levels_grid: Sequence[int] = (3, 5),
    horizon_days: int = 30,
    n_sims: int = 500,
    gd_restarts: int = 50,
    n_seeds: int = 20,
    base_seed: int = 100,
) -> Dict[str, Any]:
    t0_total = time.time()
    trials: List[Dict[str, Any]] = []

    for univ_name, weights in universes.items():
        N = len(weights)
        logger.info("Adversarial bench: %s (%d assets)", univ_name, N)

        try:
            problem = build_problem(data_map, weights, horizon_days=horizon_days, n_sims=n_sims)
        except Exception as e:
            logger.warning("Problem build failed for %s: %s", univ_name, e)
            trials.append({"universe": univ_name, "error": str(e)})
            continue

        for n_levels in n_levels_grid:
            n_states = n_levels ** N
            logger.info("  grid n_levels=%d (%d states)", n_levels, n_states)

            # Pre-build grid costs once (reused by QAOA + Grover across seeds)
            grid_indices, levels, costs = _build_grid(problem, n_levels)
            brute_idx = int(np.argmin(costs))
            brute_cvar = float(costs[brute_idx])

            for seed_offset in range(n_seeds):
                seed = base_seed + seed_offset

                # GD (continuous, uses smoothed CVaR + finite differences)
                try:
                    gd = solve_gd(problem, n_restarts=gd_restarts, seed=seed)
                    gd_global = bool(abs(gd["best_cvar"] - brute_cvar) < abs(brute_cvar) * 0.01) if brute_cvar != 0 else True
                    trials.append(BenchmarkCell(
                        solver="gradient_descent", universe=univ_name, n_assets=N,
                        n_levels=n_levels, seed=seed,
                        best_cvar=gd["best_cvar"], best_shock=gd["best_shock"],
                        n_evaluations=gd["n_evaluations"], runtime_ms=gd["runtime_ms"],
                        found_global=gd_global,
                        extra={"best_of_n": gd["best_of_n"], "median_of_n": gd["median_of_n"], "std_of_n": gd["std_of_n"]},
                    ).to_dict())
                except Exception as e:
                    trials.append({"solver": "gradient_descent", "universe": univ_name, "seed": seed, "error": str(e)})

                # QAOA (skip if grid too large)
                if n_states <= 64:
                    try:
                        qa = solve_qaoa(problem, n_levels=n_levels, seed=seed)
                        trials.append(BenchmarkCell(
                            solver="qaoa", universe=univ_name, n_assets=N,
                            n_levels=n_levels, seed=seed,
                            best_cvar=qa["best_cvar"], best_shock=qa["best_shock"],
                            n_evaluations=qa["n_evaluations"], runtime_ms=qa["runtime_ms"],
                            found_global=qa["found_global"],
                        ).to_dict())
                    except Exception as e:
                        trials.append({"solver": "qaoa", "universe": univ_name, "seed": seed, "error": str(e)})
                else:
                    trials.append({"solver": "qaoa", "universe": univ_name, "seed": seed, "n_levels": n_levels,
                                   "skipped": f"grid too large ({n_states} states)"})

                # Grover (skip if grid too large)
                if n_states <= 256:
                    try:
                        gr = solve_grover(problem, n_levels=n_levels, seed=seed)
                        trials.append(BenchmarkCell(
                            solver="grover", universe=univ_name, n_assets=N,
                            n_levels=n_levels, seed=seed,
                            best_cvar=gr["best_cvar"], best_shock=gr["best_shock"],
                            n_evaluations=gr["n_evaluations"], runtime_ms=gr["runtime_ms"],
                            found_global=gr["found_global"],
                        ).to_dict())
                    except Exception as e:
                        trials.append({"solver": "grover", "universe": univ_name, "seed": seed, "error": str(e)})
                else:
                    trials.append({"solver": "grover", "universe": univ_name, "seed": seed, "n_levels": n_levels,
                                   "skipped": f"grid too large ({n_states} states)"})

    # Aggregate summary per (solver, universe, n_levels)
    summary = _aggregate(trials)

    return {
        "benchmark": "adversarial_scenario_discovery",
        "total_runtime_ms": int((time.time() - t0_total) * 1000),
        "config": {
            "n_levels_grid": list(n_levels_grid),
            "horizon_days": horizon_days,
            "n_sims": n_sims,
            "gd_restarts": gd_restarts,
            "n_seeds": n_seeds,
        },
        "summary": summary,
        "trials": trials,
    }


def _aggregate(trials: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from collections import defaultdict
    groups: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = defaultdict(list)
    for t in trials:
        if "error" in t or "skipped" in t:
            continue
        key = (t.get("solver", "?"), t.get("universe", "?"), t.get("n_levels", 0))
        groups[key].append(t)

    out = []
    for (solver, univ, nlev), rows in sorted(groups.items()):
        cvars = [r["best_cvar"] for r in rows]
        times = [r["runtime_ms"] for r in rows]
        globals_found = [r.get("found_global", False) for r in rows]
        out.append({
            "solver": solver,
            "universe": univ,
            "n_levels": nlev,
            "n_trials": len(rows),
            "median_cvar": float(np.median(cvars)),
            "best_cvar": float(min(cvars)),
            "worst_cvar": float(max(cvars)),
            "std_cvar": float(np.std(cvars)),
            "median_runtime_ms": int(np.median(times)),
            "global_optimum_rate": float(np.mean(globals_found)),
        })
    return out
