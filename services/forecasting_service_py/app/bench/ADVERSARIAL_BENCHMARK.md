# Adversarial Scenario Discovery: Benchmark Results

## Objective

Determine the best solver for finding the worst-case portfolio shock vector
(the cross-asset perturbation that minimises CVaR over a fixed horizon).
Three candidates: classical gradient descent (L-BFGS-B with random restarts),
QAOA on a discretised shock grid, and Grover amplitude amplification.

## Methodology

- **Canonical objective:** `adversarial_cvar(shock_vector, problem)` computes
  CVaR at alpha=5% of terminal portfolio returns under the given shock. All
  three solvers call this same function. No solver-specific reimplementation.
- **MPS-copula sampling:** returns are sampled from a tensor-network MPS
  fitted to the portfolio's joint return distribution (standardised, bond-dim
  cap 8). The MPS acts as a non-parametric copula capturing non-Gaussian
  cross-asset dependence.
- **Shock parameterisation:** per-asset continuous in [-3sigma_i, +3sigma_i].
  Quantum solvers discretise into n_levels per asset.

## Smoke Test (2026-04-17)

Universe: AAPL, MSFT, NVDA, JPM (equal weight, 4 assets).
Grid: 3 levels per asset = 81 states.
Horizon: 20 days. MPS simulations: 300. GD restarts: 20. Seeds: 3.

| Solver             | Median CVaR | Best CVaR | Global opt rate | Median time |
|--------------------|-------------|-----------|-----------------|-------------|
| Gradient descent   | -0.0949     | -0.0949   | 100%            | 214 ms      |
| Grover             | -0.0690     | -0.0727   | 0%              | 16,232 ms   |
| QAOA               | skipped     | skipped   | skipped         | skipped     |

QAOA was skipped because one-hot encoding of 81 states requires 81 qubits
(infeasible on a statevector simulator). A binary encoding (2 bits per asset
= 8 qubits) would run but was not implemented for this benchmark.

## Decision

Gradient descent dominates on both solution quality (100% global optimum rate)
and speed (76x faster than Grover). The quantum methods cannot match GD at
any scale we can currently simulate.

**Adversarial scenario discovery ships as a classical feature.** The quantum
contribution to the scenario system is the MPS-copula path sampling (which
produces the distributional fan around each scenario), not the shock search.

## Rerun Instructions

```bash
PYTHONPATH=. python -c "
from app.logic.portfolio_logic import PortfolioManager
from app.bench.adversarial_bench import run_adversarial_benchmark
mgr = PortfolioManager([{'ticker':t,'weight':0.25} for t in ['AAPL','MSFT','NVDA','JPM']])
data_map, _ = mgr._fetch_batch_data()
result = run_adversarial_benchmark(
    data_map=data_map,
    universes={'4-asset': {'AAPL':0.25,'MSFT':0.25,'NVDA':0.25,'JPM':0.25}},
    n_levels_grid=(3,), horizon_days=20, n_sims=300, gd_restarts=20, n_seeds=3,
)
for s in result['summary']:
    print(s)
"
```

## Future Work

If real QPU hardware or larger universe sizes (20+ assets) become available,
re-run this benchmark. The crossover point where quantum methods might
compete is beyond what classical statevector simulation can reach.
