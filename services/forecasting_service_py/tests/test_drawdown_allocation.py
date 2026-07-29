"""Drawdown-managed allocation module + CDaR performance metric."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.logic.drawdown_allocation import compute_drawdown_allocation


def _frame(n=600, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    cols = {}
    for i, t in enumerate(["AAA", "BBB", "CCC"]):
        r = rng.normal(0.0004, 0.01 + 0.004 * i, n)
        cols[t] = 100 * np.exp(np.cumsum(r))
    return pd.DataFrame(cols, index=dates)


def test_methods_weights_and_profiles():
    res = compute_drawdown_allocation(
        _frame(), current_weights={"AAA": 0.34, "BBB": 0.33, "CCC": 0.33}
    )
    keys = {m["key"] for m in res["methods"]}
    assert {"equal", "inverse_vol", "risk_parity", "drawdown_mgd"} <= keys
    for m in res["methods"]:
        assert set(m["weights"]) == {"AAA", "BBB", "CCC"}
        assert abs(sum(m["weights"].values()) - 1.0) < 1e-6       # normalized, long-only
        assert all(w >= 0 for w in m["weights"].values())
        p = m["profile"]
        assert p is not None and {"sharpe", "max_drawdown", "cdar95", "turnover_per_yr"} <= set(p)
        assert p["max_drawdown"] <= 0 and p["cdar95"] <= 0        # negative convention
    assert res["current_weights"] and abs(sum(res["current_weights"].values()) - 1.0) < 1e-6


def test_requires_two_assets():
    one = _frame()[["AAA"]]
    try:
        compute_drawdown_allocation(one)
        assert False, "should have raised"
    except ValueError:
        pass


def test_perf_metrics_include_cdar():
    from app.logic.forecasting_logic import HybridForecaster
    prices = (100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.012, 400)))).tolist()
    pm = HybridForecaster()._calculate_performance_metrics(prices)
    assert "cdar_95" in pm
    assert pm["cdar_95"] <= 0                                     # negative, like max_drawdown
    assert pm["cdar_95"] >= pm["max_drawdown"] - 1e-9            # avg-of-worst >= single worst
