"""Tests for the year-end narrator (LLM mocked, no Gemini call), the honest
review-year data helpers in the router (None for missing months, real
walk-forward model accuracy or nothing), and the year-end PDF template
building end-to-end with real-shaped data."""

from __future__ import annotations

import importlib
import json
from datetime import datetime
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.agents import report_narrator as rn
from app.agents.llm import LlmResult
from app.reports.template_yearend import generate_yearend_report

# app/reports/__init__.py rebinds the name `report_router` to the APIRouter
# instance, so fetch the module itself for its helper functions.
rr = importlib.import_module("app.reports.report_router")

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


FACTS = {
    "portfolio_name": "Growth Fund",
    "review_year": 2025,
    "portfolio_value_start": 2_200_000,
    "portfolio_value_end": 2_450_000,
    "return_period": 0.1136,
    "coverage_label": "January to December 2025",
    "benchmark": {"label": "S&P 500", "return_period": 0.089},
    "monthly_returns": [{"month": "Jan", "return": 0.028},
                        {"month": "Feb", "return": -0.032}],
    "risk_metrics": {"annualized_vol": 0.1105, "sharpe": 0.82, "sortino": 1.14,
                     "max_drawdown": -0.052, "regime": "Normal",
                     "fragility_score": 0.98},
    "metrics_window": "engine's trailing two-year analysis window ending July 27, 2026",
    "vol_series": [{"month": "Jan", "vol": 9.2}, {"month": "Feb", "vol": 14.5}],
    "fragility_series": [{"month": "Jan", "fragility": 0.85},
                         {"month": "Feb", "fragility": 1.45}],
    "model_accuracy": {"hit_rate": 0.61, "avg_error": 0.021, "n_steps": 84,
                       "best_model": "prophet"},
    "top_contributors": [{"ticker": "VTI", "name": "Vanguard Total Stock",
                          "return": 0.142, "contribution": 0.0497}],
    "bottom_contributors": [{"ticker": "BND", "name": "Vanguard Total Bond",
                             "return": -0.018, "contribution": -0.0045}],
}


def _fake(text: str) -> LlmResult:
    return LlmResult(text=text, model="gemini-2.5-flash", prompt_tokens=10,
                     output_tokens=20, latency_ms=5, cached=False, input_hash="x")


def _payload(**over):
    base = {
        "year_summary": "ys", "risk_commentary": "rc",
        "model_commentary": "mc", "year_ahead": "ya",
        "considerations": ["c1", "c2"],
    }
    base.update(over)
    return json.dumps(base)


# ── Narrator ──────────────────────────────────────────────────────────


def test_yearend_prompt_is_grounded_and_forbids_dashes():
    p = rn.build_yearend_prompt(FACTS)
    assert "Growth Fund" in p and "Review year: 2025" in p
    assert "Covered months: January to December 2025" in p
    assert "$2.20M" in p and "$2.45M" in p
    assert "Total return over the covered months: +11.36%" in p
    assert "Benchmark (S&P 500) over the same months: +8.90%" in p
    assert "Jan: +2.80%" in p and "Feb: -3.20%" in p
    assert "annualized volatility +11.05%" in p and "Sharpe 0.82" in p
    assert "trailing two-year analysis window" in p
    assert "Current regime: Normal, fragility score 0.98" in p
    assert "Jan: 9.2%" in p                     # monthly vol
    assert "Jan: 0.85" in p                     # monthly fragility
    assert ("winning model prophet, directional accuracy 61% across 84 "
            "validation points, mean absolute forecast error 2.1%") in p
    assert "VTI: return +14.20%, contribution +4.97%" in p
    assert "BND: return -1.80%" in p
    assert "NEVER use em dashes" in p


def test_yearend_prompt_omits_absent_sections():
    facts = dict(FACTS, benchmark=None, model_accuracy=None,
                 portfolio_value_start=None, portfolio_value_end=None,
                 vol_series=[], fragility_series=[])
    p = rn.build_yearend_prompt(facts)
    assert "No benchmark data was available for the covered months." in p
    assert "No model validation facts are available for this run." in p
    assert "winning model" not in p
    assert "Portfolio value" not in p           # no dollar values -> omitted
    assert "Monthly realized volatility" not in p
    assert "Monthly fragility score" not in p


def test_run_yearend_strips_any_dash_that_slips_through():
    with patch.object(rn, "generate", return_value=_fake(_payload(
            year_ahead="Fragility is elevated — watch it – closely",
            considerations=["Review March — it drove the loss"]))):
        out, _ = rn.run_yearend(facts=FACTS)
    assert "—" not in json.dumps(out) and "–" not in json.dumps(out)
    assert out["year_ahead"] == "Fragility is elevated, watch it, closely"


def test_run_yearend_cache_key_tracks_facts():
    captured = {}

    def _cap(prompt, **kw):
        captured.update(kw)
        return _fake(_payload())

    with patch.object(rn, "generate", side_effect=_cap):
        rn.run_yearend(facts=FACTS)
    key = captured["cache_key_extra"]
    assert key["review_year"] == 2025
    assert key["return_period"] == pytest.approx(0.1136)
    assert key["bench_return"] == pytest.approx(0.089)
    assert key["hit_rate"] == pytest.approx(0.61)
    assert key["contributors"] == ["VTI", "BND"]
    assert captured["agent_name"] == "yearend_narrator"
    assert captured["schema"] is rn.YearEndNarrative


def test_run_yearend_cache_key_handles_missing_benchmark_and_accuracy():
    captured = {}

    def _cap(prompt, **kw):
        captured.update(kw)
        return _fake(_payload())

    with patch.object(rn, "generate", side_effect=_cap):
        rn.run_yearend(facts=dict(FACTS, benchmark=None, model_accuracy=None))
    key = captured["cache_key_extra"]
    assert key["bench_return"] is None
    assert key["hit_rate"] is None


def test_run_yearend_raises_on_malformed_json():
    with patch.object(rn, "generate", return_value=_fake("nope")):
        with pytest.raises(ValueError, match="malformed JSON"):
            rn.run_yearend(facts=FACTS)


# ── Router helpers: honest review-year series ─────────────────────────


def _daily_series():
    """Jan has a full month of data, Feb a single point, Mar a full month;
    Apr onward nothing."""
    idx = (list(pd.bdate_range("2025-01-02", "2025-01-31"))
           + [pd.Timestamp("2025-02-14")]
           + list(pd.bdate_range("2025-03-03", "2025-03-31")))
    return pd.Series(np.linspace(100.0, 110.0, len(idx)), index=pd.DatetimeIndex(idx))


def test_monthly_returns_or_none_flags_missing_months():
    s = _daily_series()
    out = rr._monthly_returns_or_none(s, 2025)
    assert len(out) == 12
    jan = s[(s.index.month == 1)]
    assert out[0] == pytest.approx(float(jan.iloc[-1] / jan.iloc[0] - 1))
    assert out[1] is None                       # single observation -> None, not 0.0
    assert out[2] is not None
    assert all(v is None for v in out[3:])
    assert rr._monthly_returns_or_none(pd.Series(dtype=float), 2025) == [None] * 12


def test_coverage_run_stops_at_first_gap():
    assert rr._coverage_run([None, 0.1, 0.2, None, 0.3] + [None] * 7) == [1, 2]
    assert rr._coverage_run([None] * 12) == []
    assert rr._coverage_run([0.01] * 12) == list(range(12))


def test_cumulative_pct_only_covers_the_run():
    monthly = [None, 0.10, 0.10] + [None] * 9
    cov = rr._coverage_run(monthly)
    out = rr._cumulative_pct(monthly, cov)
    assert out[0] is None
    assert out[1] == pytest.approx(10.0)
    assert out[2] == pytest.approx(21.0)
    assert all(v is None for v in out[3:])


def test_compute_yearend_vol_flags_thin_months():
    out = rr._compute_yearend_vol(_daily_series(), 2025)
    assert out[0] is not None and out[0] > 0
    assert out[1] is None                       # <5 return observations
    assert all(v is None for v in out[3:])
    assert rr._compute_yearend_vol(None, 2025) == [None] * 12


def test_real_model_accuracy_uses_engine_forecast_quality():
    data = {
        "model_used": "prophet",
        "forecast_result": {"forecast_quality": {
            "mape": 0.021, "directional_accuracy": 0.61,
            "n_validation_steps": 84, "model": "prophet",
            "source": "walk_forward_validation",
        }},
    }
    ma = rr._real_model_accuracy(data)
    assert ma == {"hit_rate": 0.61, "avg_error": 0.021, "n_steps": 84,
                  "best_model": "prophet"}


def test_real_model_accuracy_falls_back_to_model_validation():
    data = {
        # A degraded run marks forecast_quality with a string, not a dict.
        "forecast_result": {"forecast_quality": "fallback_post_explosion"},
        "model_used": "arima",
        "model_validation": {"quality_per_model": {"arima": {
            "mape": 0.03, "directional_accuracy": 0.55, "n_validation_steps": 40,
        }}},
    }
    ma = rr._real_model_accuracy(data)
    assert ma["best_model"] == "arima" and ma["n_steps"] == 40
    assert ma["hit_rate"] == pytest.approx(0.55)


def test_real_model_accuracy_returns_none_instead_of_inventing():
    assert rr._real_model_accuracy({}) is None
    nan_quality = {"forecast_result": {"forecast_quality": {
        "mape": float("nan"), "directional_accuracy": 0.6,
        "n_validation_steps": 10, "model": "lstm"}}}
    assert rr._real_model_accuracy(nan_quality) is None
    zero_steps = {"forecast_result": {"forecast_quality": {
        "mape": 0.02, "directional_accuracy": 0.6,
        "n_validation_steps": 0, "model": "lstm"}}}
    assert rr._real_model_accuracy(zero_steps) is None


def _price_df(start, n, base, step):
    dates = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"date": dates, "price": [base + i * step for i in range(n)]})


def test_compute_top_contributors_drops_holdings_without_year_data():
    data = {
        "price_data": {
            "AAA": _price_df("2025-01-02", 200, 100, 0.5),
            "BBB": _price_df("2025-01-02", 200, 100, -0.1),
            "CCC": _price_df("2025-01-02", 200, 50, 0.2),
            "DDD": _price_df("2025-01-02", 200, 80, 0.05),
            "EEE": _price_df("2023-01-02", 100, 100, 1.0),   # outside the year
        },
        "weights": {"AAA": 0.3, "BBB": 0.2, "CCC": 0.3, "DDD": 0.15, "EEE": 0.05},
        "fundamentals": {},
    }
    top = rr._compute_top_contributors(data, 2025, top=True)
    bottom = rr._compute_top_contributors(data, 2025, top=False)
    assert [r["ticker"] for r in top] == ["AAA", "CCC", "DDD"]
    assert [r["ticker"] for r in bottom] == ["BBB"]          # never repeats the top 3
    assert "EEE" not in [r["ticker"] for r in top + bottom]


def test_build_review_year_prices_falls_back_to_fetched_frames():
    """With no MarketData rows, the series is built from the price frames the
    report already fetched; with no frames either, it is empty (never 100.0)."""
    data = {
        "tickers": ["AAA", "BBB"],
        "weights": {"AAA": 0.6, "BBB": 0.4},
        "price_data": {
            "AAA": _price_df("2025-01-02", 60, 100, 0.5),
            "BBB": _price_df("2025-01-02", 60, 50, -0.05),
        },
    }
    s = rr._build_review_year_prices(data, 2025)
    assert len(s) == 60
    assert float(s.iloc[0]) == pytest.approx(100.0)
    assert rr._monthly_returns_or_none(s, 2025)[0] is not None

    empty = rr._build_review_year_prices(
        {"tickers": ["AAA"], "weights": {"AAA": 1.0}, "price_data": {}}, 2025)
    assert len(empty) == 0


# ── Template (end-to-end PDF build) ───────────────────────────────────


def _cumulative(monthly):
    out, running = [], 1.0
    for r in monthly:
        if r is None:
            out.append(None)
            continue
        running *= 1 + r
        out.append((running - 1) * 100)
    return out


def _template_data(**over):
    monthly = [0.028, 0.015, -0.032, 0.041, 0.018, -0.012,
               0.035, -0.008, 0.022, 0.019, -0.015, 0.031]
    bench_monthly = [m - 0.003 for m in monthly]
    data = {
        "client_name": "Growth Fund",
        "advisor_name": "Alex Advisor",
        "firm_name": "Example Advisors",
        "report_date": datetime(2026, 1, 5),
        "review_year": 2025,
        "portfolio_value_start": 2_200_000.0,
        "portfolio_value_end": 2_450_000.0,
        "portfolio_return_ytd": float(np.prod([1 + m for m in monthly]) - 1),
        "coverage_label": "January to December 2025",
        "full_year": True,
        "benchmark_return_ytd": float(np.prod([1 + m for m in bench_monthly]) - 1),
        "benchmark_label": "S&P 500 (SPY proxy)",
        "sharpe": 0.82, "sortino": 1.14,
        "max_drawdown": -0.052, "annualized_vol": 0.1105,
        "metrics_window_label": ("engine's trailing two-year analysis window "
                                 "ending January 05, 2026"),
        "regime": "Normal", "fragility_score": 0.98,
        "months": MONTHS,
        "portfolio_cumulative": _cumulative(monthly),
        "benchmark_cumulative": _cumulative(bench_monthly),
        "monthly_returns": monthly,
        "vol_series": [9.2, 10.1, 14.5, 11.8, 10.3, 9.8,
                       10.5, 11.2, 10.0, 9.5, 12.1, 10.8],
        "fragility_series": [0.85, 0.92, 1.45, 1.12, 0.95, 0.88,
                             0.97, 1.05, 0.92, 0.87, 1.15, 0.98],
        "model_accuracy": {"hit_rate": 0.61, "avg_error": 0.021,
                           "n_steps": 84, "best_model": "prophet"},
        "top_contributors": [
            {"ticker": "VTI", "name": "Vanguard Total Stock",
             "return": 0.142, "contribution": 0.0497},
            {"ticker": "GLD", "name": "SPDR Gold Shares",
             "return": 0.185, "contribution": 0.0148},
        ],
        "bottom_contributors": [
            {"ticker": "BND", "name": "Vanguard Total Bond",
             "return": -0.018, "contribution": -0.0045},
        ],
        "narrative": {
            "year_summary": "The portfolio finished the covered months ahead of the benchmark.",
            "risk_commentary": "Volatility peaked in March and normalized into year end.",
            "model_commentary": "Directional accuracy of 61% across 84 validation points.",
            "year_ahead": "With fragility at 0.98, the risk state is currently normal.",
            "considerations": ["Evaluate the March drawdown month against tolerance."],
        },
        "proposed_changes": None,
    }
    data.update(over)
    return data


def _assert_pdf(path):
    blob = path.read_bytes()
    assert blob.startswith(b"%PDF")
    assert len(blob) > 10_000


def test_generate_yearend_report_builds_pdf(tmp_path):
    out = tmp_path / "yearend.pdf"
    generate_yearend_report(str(out), _template_data())
    _assert_pdf(out)


def test_generate_yearend_report_numbers_only_partial_year(tmp_path):
    """No benchmark, no dollar values, no model accuracy, no narrative, and a
    partial year with missing months: the PDF still builds with the absent
    elements omitted rather than invented."""
    monthly = [None, None, 0.021, -0.013, 0.034, 0.008,
               0.017, -0.006, 0.011, 0.024, None, None]
    out = tmp_path / "yearend_min.pdf"
    generate_yearend_report(str(out), _template_data(
        monthly_returns=monthly,
        portfolio_cumulative=_cumulative(monthly),
        benchmark_cumulative=None,
        benchmark_return_ytd=None, benchmark_label=None,
        portfolio_value_start=None, portfolio_value_end=None,
        portfolio_return_ytd=float(np.prod([1 + m for m in monthly if m is not None]) - 1),
        coverage_label="March to October 2025", full_year=False,
        model_accuracy=None, narrative=None,
        vol_series=[None, None, 14.5, 11.8, 10.3, 9.8, 10.5, 11.2, 10.0, 9.5, None, None],
        fragility_series=[None] * 12,
    ))
    _assert_pdf(out)


def test_generate_yearend_report_without_any_risk_series(tmp_path):
    out = tmp_path / "yearend_norisk.pdf"
    generate_yearend_report(str(out), _template_data(
        vol_series=[None] * 12, fragility_series=[None] * 12,
        top_contributors=[], bottom_contributors=[],
    ))
    _assert_pdf(out)


def test_generate_yearend_report_escapes_ai_and_advisor_text(tmp_path):
    """AI narrative and advisor-authored text with XML-special characters must
    not break the PDF build."""
    out = tmp_path / "yearend_escape.pdf"
    generate_yearend_report(str(out), _template_data(
        model_accuracy={"hit_rate": 0.61, "avg_error": 0.021,
                        "n_steps": 84, "best_model": "prophet & co <v2>"},
        regime="High <Fragility> & Stress",
        narrative={
            "year_summary": "Returns were > 10% & drawdowns < 6%.",
            "risk_commentary": "Vol <peaked> in March & fell.",
            "model_commentary": "Accuracy > 60% across <84> points.",
            "year_ahead": "Watch fragility & volatility <closely>.",
            "considerations": ["Evaluate <VTI> & the 35% weight."],
        },
        proposed_changes=["Trim <AAA> & rebalance into BBB."],
    ))
    _assert_pdf(out)
