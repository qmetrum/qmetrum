"""Tests for app.logic.var_backtest_runner.

The price fetch is monkeypatched with deterministic synthetic series, so these
run offline and fast. The MPS path uses a small window to stay quick.

Run from the service root:  python -m pytest tests/test_var_backtest_runner.py -q
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import app.logic.var_backtest_runner as runner


def _synthetic_series(n_days=900, seed=0):
    rng = np.random.default_rng(seed)
    biz = pd.bdate_range("2021-01-01", periods=n_days)
    mkt = rng.standard_normal(n_days) * 0.01  # shared market factor

    def make(vol, beta, s):
        g = np.random.default_rng(s)
        rets = beta * mkt + g.standard_normal(n_days) * vol
        price = 100 * np.exp(np.cumsum(rets))
        return [{"date": d.strftime("%Y-%m-%d"), "price": float(p)}
                for d, p in zip(biz, price)]

    return {"AAA": make(0.012, 1.0, 1), "BBB": make(0.018, 1.2, 2),
            "CCC": make(0.009, 0.6, 3), "DDD": make(0.025, 0.8, 4)}


@pytest.fixture
def patched_prices(monkeypatch):
    series = _synthetic_series()
    monkeypatch.setattr(runner, "get_price_series_cached",
                        lambda t, period="5y": series.get(t, []))
    return series


ASSETS = [{"ticker": "AAA", "weight": 0.4}, {"ticker": "BBB", "weight": 0.3},
          {"ticker": "CCC", "weight": 0.2}, {"ticker": "DDD", "weight": 0.1}]

EXPECTED_KEYS = {"confidence", "exceptions", "kupiec", "christoffersen",
                 "basel_traffic_light", "model_passes", "series", "method",
                 "params", "data_window", "overlapping_windows"}


def test_historical_well_calibrated(patched_prices):
    res = runner.run_portfolio_var_backtest(
        assets=ASSETS, method="historical", n_backtest=250, est_window=252)
    assert EXPECTED_KEYS <= set(res.keys())
    assert res["method"] == "historical"
    assert res["n_observations"] >= 200
    # roughly-iid synthetic returns -> empirical VaR should be well calibrated
    assert 0.02 <= res["breach_rate"] <= 0.09
    assert res["kupiec"]["reject"] is False
    assert res["overlapping_windows"] is False
    assert len(res["series"]["realized_return"]) == res["n_observations"]


def test_mps_fan_runs_end_to_end(patched_prices):
    res = runner.run_portfolio_var_backtest(
        assets=ASSETS, method="mps_fan", n_backtest=30, est_window=120,
        n_simulations=300)
    assert EXPECTED_KEYS <= set(res.keys())
    assert res["method"] == "mps_fan"
    assert res["n_observations"] >= 30
    assert res["params"]["tickers"] == ["AAA", "BBB", "CCC", "DDD"]
    assert res["data_window"]["n_return_obs"] > 0
    # every predicted VaR is a negative (signed) return
    assert all(v < 0 for v in res["series"]["var_threshold"])


def test_mps_fan_deterministic(patched_prices):
    kw = dict(assets=ASSETS, method="mps_fan", n_backtest=30, est_window=120,
              n_simulations=300, random_seed=7)
    a = runner.run_portfolio_var_backtest(**kw)
    b = runner.run_portfolio_var_backtest(**kw)
    assert a["series"]["var_threshold"] == b["series"]["var_threshold"]
    assert a["exceptions"] == b["exceptions"]


def test_horizon_gt_one_flags_overlap(patched_prices):
    res = runner.run_portfolio_var_backtest(
        assets=ASSETS, method="historical", n_backtest=100, est_window=252,
        horizon_days=5)
    assert res["overlapping_windows"] is True
    assert res["horizon_days"] == 5


def test_mps_requires_two_assets(patched_prices):
    with pytest.raises(ValueError, match=r">= 2 assets"):
        runner.run_portfolio_var_backtest(
            assets=[{"ticker": "AAA", "weight": 1.0}], method="mps_fan",
            n_backtest=30, est_window=120)


def test_unknown_method_raises(patched_prices):
    with pytest.raises(ValueError, match="unknown method"):
        runner.run_portfolio_var_backtest(assets=ASSETS, method="quantum_woo")


def test_insufficient_history_raises(monkeypatch):
    short = _synthetic_series(n_days=120)
    monkeypatch.setattr(runner, "get_price_series_cached",
                        lambda t, period="5y": short.get(t, []))
    with pytest.raises(ValueError, match="insufficient history"):
        runner.run_portfolio_var_backtest(
            assets=ASSETS, method="historical", est_window=252, n_backtest=250)


def test_no_data_raises(monkeypatch):
    monkeypatch.setattr(runner, "get_price_series_cached", lambda t, period="5y": [])
    with pytest.raises(ValueError, match="no price history"):
        runner.run_portfolio_var_backtest(assets=ASSETS, method="historical")


# --------------------------------------------------------------------------- #
# Phase 3: parametric method + multi-method comparison
# --------------------------------------------------------------------------- #
def test_parametric_method_runs(patched_prices):
    res = runner.run_portfolio_var_backtest(
        assets=ASSETS, method="parametric", n_backtest=200, est_window=252)
    assert res["method"] == "parametric"
    assert res["n_observations"] >= 150
    assert all(v < 0 for v in res["series"]["var_threshold"])


def test_comparison_runs_all_methods_on_identical_sample(patched_prices):
    res = runner.run_portfolio_var_backtest_comparison(
        assets=ASSETS, n_backtest=30, est_window=120, n_simulations=200)
    keys = {m["key"] for m in res["methods"]}
    assert {"historical", "parametric", "mps_d4", "mps_d8"} <= keys
    ok = [m for m in res["methods"] if m["status"] == "ok"]
    assert len(ok) == 4  # 4 assets -> d=4 (256) and d=8 (4096) both feasible
    # Every method scored on the IDENTICAL sample (fair comparison)
    assert len({m["n_observations"] for m in ok}) == 1
    assert ok[0]["n_observations"] == len(res["shared"]["realized_return"])
    assert len(res["shared"]["dates"]) == ok[0]["n_observations"]
    # each method carries a per-day var_threshold of the right length
    for m in ok:
        assert len(m["var_threshold"]) == m["n_observations"]
        assert all(v < 0 for v in m["var_threshold"])
    # recommended is either None or one of the passing methods
    if res["recommended"] is not None:
        passers = {m["key"] for m in ok if m["model_passes"]}
        assert res["recommended"]["key"] in passers


def test_comparison_skips_infeasible_physical_dim(patched_prices):
    res = runner.run_portfolio_var_backtest_comparison(
        assets=ASSETS, n_backtest=30, est_window=120, n_simulations=200,
        methods=[{"key": "historical", "label": "Historical", "method": "historical"},
                 {"key": "mps_big", "label": "MPS d=64", "method": "mps_fan", "physical_dim": 64}])
    by_key = {m["key"]: m for m in res["methods"]}
    assert by_key["historical"]["status"] == "ok"
    assert by_key["mps_big"]["status"] == "skipped"
    assert "exceeds" in by_key["mps_big"]["reason"]


def test_comparison_single_asset_skips_mps(patched_prices):
    res = runner.run_portfolio_var_backtest_comparison(
        assets=[{"ticker": "AAA", "weight": 1.0}], n_backtest=30, est_window=120)
    by_key = {m["key"]: m for m in res["methods"]}
    assert by_key["historical"]["status"] == "ok"
    assert by_key["parametric"]["status"] == "ok"
    assert by_key["mps_d4"]["status"] == "skipped"
    assert "2 assets" in by_key["mps_d4"]["reason"]
