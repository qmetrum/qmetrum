"""Unit tests for app.logic.var_backtest.

Run from the service root:  python -m pytest tests/test_var_backtest.py -q

The numeric reference values for the Kupiec statistic and the Basel zones are
computed by hand / from the published Basel table, so these lock the formulas
rather than merely re-deriving them with the same code.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.logic.var_backtest import (
    basel_traffic_light,
    christoffersen,
    expected_shortfall,
    extract_var_from_paths,
    kupiec_pof,
    run_var_backtest,
)


# --------------------------------------------------------------------------- #
# Kupiec POF — known-answer values
# --------------------------------------------------------------------------- #
def test_kupiec_known_value_overbreach():
    # n=1000, x=100, p=0.05 -> LR_POF = 41.31 (hand-computed)
    res = kupiec_pof(1000, 100, confidence=0.95)
    assert res["statistic"] == pytest.approx(41.31, abs=0.05)
    assert res["reject"] is True
    assert res["observed_rate"] == pytest.approx(0.10)
    assert res["expected_rate"] == pytest.approx(0.05)


def test_kupiec_zero_breaches_rejects_too_conservative():
    # n=250, x=0, p=0.05 -> LR_POF = -2*250*ln(0.95) = 25.65; no NaN despite x=0
    res = kupiec_pof(250, 0, confidence=0.95)
    assert res["statistic"] == pytest.approx(25.65, abs=0.05)
    assert res["reject"] is True


def test_kupiec_perfect_calibration_not_rejected():
    res = kupiec_pof(1000, 50, confidence=0.95)  # observed rate == p exactly
    assert res["statistic"] == pytest.approx(0.0, abs=1e-9)
    assert res["p_value"] == pytest.approx(1.0, abs=1e-9)
    assert res["reject"] is False


def test_kupiec_all_breaches_no_nan():
    res = kupiec_pof(100, 100, confidence=0.95)  # x == n boundary
    assert np.isfinite(res["statistic"])
    assert res["reject"] is True


def test_kupiec_input_validation():
    with pytest.raises(ValueError):
        kupiec_pof(0, 0)
    with pytest.raises(ValueError):
        kupiec_pof(100, 101)


# --------------------------------------------------------------------------- #
# Basel traffic light — reproduce the published 250-day / 99% table
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "x,expected",
    [(0, "green"), (4, "green"), (5, "yellow"), (9, "yellow"), (10, "red"), (15, "red")],
)
def test_basel_zones_250d_99pct(x, expected):
    assert basel_traffic_light(250, x, confidence=0.99)["zone"] == expected


# --------------------------------------------------------------------------- #
# Christoffersen — transitions, identity, clustering
# --------------------------------------------------------------------------- #
def test_christoffersen_transition_counts():
    b = [False, True, True, False, False, True]
    # pairs: (F,T)(T,T)(T,F)(F,F)(F,T) -> n00=1 n01=2 n10=1 n11=1
    t = christoffersen(b)["transitions"]
    assert (t["n00"], t["n01"], t["n10"], t["n11"]) == (1, 2, 1, 1)


def test_christoffersen_cc_equals_pof_plus_ind():
    rng = np.random.default_rng(7)
    breaches = rng.random(500) < 0.08
    chris = christoffersen(breaches, confidence=0.95)
    pof = kupiec_pof(breaches.size, int(breaches.sum()), confidence=0.95)
    cc = chris["conditional_coverage"]["statistic"]
    ind = chris["independence"]["statistic"]
    assert cc == pytest.approx(pof["statistic"] + ind, abs=1e-9)
    assert chris["conditional_coverage"]["df"] == 2
    assert chris["independence"]["df"] == 1


def test_christoffersen_detects_clustering():
    # 10 breaches over 200 days, all consecutive -> strong clustering
    clustered = np.zeros(200, dtype=bool)
    clustered[50:60] = True
    res_clustered = christoffersen(clustered)
    assert res_clustered["independence"]["reject"] is True

    # 10 breaches evenly spaced -> independence should not reject
    spread = np.zeros(200, dtype=bool)
    spread[::20] = True
    res_spread = christoffersen(spread)
    assert res_spread["independence"]["reject"] is False


def test_christoffersen_zero_breaches_is_well_defined():
    res = christoffersen(np.zeros(250, dtype=bool))
    assert res["independence"]["statistic"] == pytest.approx(0.0)
    assert res["independence"]["p_value"] == pytest.approx(1.0)
    assert res["independence"]["reject"] is False


# --------------------------------------------------------------------------- #
# extract_var_from_paths
# --------------------------------------------------------------------------- #
def test_extract_var_known_percentile():
    # row of 5 prices; np.percentile(., 5) with linear interp = 0.91 -> -0.09 return
    paths = np.array([[0.90, 0.95, 1.00, 1.05, 1.10]])
    var = extract_var_from_paths(paths, base=1.0, confidence=0.95)
    assert var.shape == (1,)
    assert var[0] == pytest.approx(-0.09, abs=1e-9)


def test_extract_var_multi_horizon_and_sign():
    rng = np.random.default_rng(1)
    # two horizons, tighter then wider dispersion -> deeper VaR at horizon 2
    paths = np.vstack([1 + 0.01 * rng.standard_normal(5000),
                       1 + 0.03 * rng.standard_normal(5000)])
    var = extract_var_from_paths(paths, base=1.0, confidence=0.95)
    assert var.shape == (2,)
    assert var[0] < 0 and var[1] < 0
    assert var[1] < var[0]  # wider dispersion -> more negative VaR


def test_extract_var_validation():
    with pytest.raises(ValueError):
        extract_var_from_paths(np.array([1.0, 2.0]))  # 1-D
    with pytest.raises(ValueError):
        extract_var_from_paths(np.ones((1, 3)), confidence=1.5)


# --------------------------------------------------------------------------- #
# expected_shortfall
# --------------------------------------------------------------------------- #
def test_expected_shortfall_on_breach_days():
    r = np.array([0.01, -0.05, 0.00, -0.07, 0.02])
    es = expected_shortfall(r, -0.03)  # breaches at -0.05 and -0.07
    assert es == pytest.approx((-0.05 + -0.07) / 2)


def test_expected_shortfall_none_when_no_breach():
    r = np.array([0.01, 0.02, 0.00])
    assert expected_shortfall(r, -0.03) is None


# --------------------------------------------------------------------------- #
# run_var_backtest — end to end
# --------------------------------------------------------------------------- #
def _series_with_breaches(n, breach_idx, var=-0.03, breach_ret=-0.05, ok_ret=0.001):
    r = np.full(n, ok_ret)
    r[breach_idx] = breach_ret
    return r, var


def test_run_backtest_well_calibrated_passes():
    # exactly 5% breaches, evenly spaced -> Kupiec ~0, independence ok
    idx = np.arange(19, 200, 20)  # 10 breaches in 200 days
    r, var = _series_with_breaches(200, idx)
    res = run_var_backtest(r, var, confidence=0.95)
    assert res["exceptions"] == 10
    assert res["breach_rate"] == pytest.approx(0.05)
    assert res["kupiec"]["reject"] is False
    assert res["model_passes"] is True
    assert res["basel_traffic_light"]["zone"] == "green"
    assert res["observed_expected_shortfall"] == pytest.approx(-0.05)


def test_run_backtest_underconservative_fails():
    # 30 breaches in 200 days (15%), clustered -> fails coverage
    idx = np.arange(50, 80)
    r, var = _series_with_breaches(200, idx)
    res = run_var_backtest(r, var, confidence=0.95)
    assert res["exceptions"] == 30
    assert res["kupiec"]["reject"] is True
    assert res["model_passes"] is False
    assert res["basel_traffic_light"]["zone"] == "red"


def test_run_backtest_scalar_broadcast_and_series_shape():
    r = np.array([0.01, -0.04, 0.00, -0.10])
    res = run_var_backtest(r, -0.03, confidence=0.95, dates=["d1", "d2", "d3", "d4"])
    assert res["n_observations"] == 4
    assert res["exceptions"] == 2
    assert res["series"]["breach"] == [False, True, False, True]
    assert res["series"]["date"] == ["d1", "d2", "d3", "d4"]
    assert len(res["series"]["var_threshold"]) == 4


def test_run_backtest_validation():
    with pytest.raises(ValueError):
        run_var_backtest([], -0.03)
    with pytest.raises(ValueError):
        run_var_backtest([0.01, 0.02], [-0.03, -0.03, -0.03])  # length mismatch
    with pytest.raises(ValueError):
        run_var_backtest([0.01], -0.03, confidence=0.0)


def test_run_backtest_is_json_serialisable():
    import json
    idx = np.arange(19, 200, 20)
    r, var = _series_with_breaches(200, idx)
    res = run_var_backtest(r, var)
    json.dumps(res)  # must not raise (no numpy scalars/arrays leak through)
