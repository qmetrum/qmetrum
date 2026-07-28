"""Tests for the market event narrator (LLM mocked, no Gemini call), the real
event-window slicing and date-based benchmark alignment in the router, and the
market event PDF template building end-to-end with real-shaped data."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from app.agents import report_narrator as rn
from app.agents.llm import LlmResult
from app.reports.template_market_event import generate_market_event_report

# app/reports/__init__.py rebinds the name `report_router` to the APIRouter
# instance, so fetch the module itself for its helper functions.
rr = importlib.import_module("app.reports.report_router")


FACTS = {
    "portfolio_name": "Growth Fund",
    "portfolio_value": 2_450_000,
    "event_name": "Rate Shock",
    "event_date": "2026-03-10",
    "event_summary": "Surprise 50bps hike; equities sold off sharply.",
    "window_start": "2026-02-17",
    "window_end": "2026-03-31",
    "trading_days": 31,
    "portfolio": {"event_return": -0.032, "peak_drawdown": -0.041},
    "benchmark": {"label": "S&P 500", "event_return": -0.058, "peak_drawdown": -0.062},
    "risk": {"regime": "High_Fragility", "fragility_score": 1.72},
    # One-dollar-basis downside reconciliation. A single-event briefing carries
    # no simulated scenario set, so worst_scenario is None (and no consistency
    # flag can fire); this mirrors what _risk_reconciliation returns here.
    "risk_reconciliation": {
        "portfolio_value": 2_450_000,
        "var_1d_pct": -0.021, "var_1d_dollars": -51_450.0,
        "max_drawdown_pct": -0.052, "max_drawdown_dollars": -127_400.0,
        "worst_scenario": None, "worst_scenario_dollars": None,
        "forecast_downside_pct": -3.1, "forecast_downside_dollars": -75_950.0,
        "fragility_label": "elevated (above the 1.5 fragile threshold)",
        "flags": [],
    },
    "forecast": {"model": "prophet", "horizon_days": 30, "return_pct": 1.8, "band_pct": 12.4},
    "holdings_impact": [
        {"ticker": "VTI", "name": "Vanguard Total Stock", "return": -0.055, "contribution": -0.0193},
        {"ticker": "GLD", "name": "SPDR Gold Shares", "return": 0.022, "contribution": 0.0018},
        {"ticker": "XYZ", "name": "No Data Asset", "return": None, "contribution": None},
    ],
}


def _fake(text: str) -> LlmResult:
    return LlmResult(text=text, model="gemini-2.5-flash", prompt_tokens=10,
                     output_tokens=20, latency_ms=5, cached=False, input_hash="x")


def _payload(**over):
    base = {
        "event_commentary": "ec", "benchmark_commentary": "bc",
        "risk_synthesis": "rs", "outlook": "ol", "considerations": ["c1", "c2"],
    }
    base.update(over)
    return json.dumps(base)


# ── Narrator ──────────────────────────────────────────────────────────


def test_market_event_prompt_is_grounded_and_forbids_dashes():
    p = rn.build_market_event_prompt(FACTS)
    assert "Growth Fund" in p and "$2.45M" in p
    assert "Rate Shock" in p and "2026-03-10" in p
    assert "2026-02-17 to 2026-03-31 (31 trading days)" in p
    assert "return since the last close before the event -3.20%" in p
    assert "peak drawdown in the window -4.10%" in p
    assert "Benchmark (S&P 500) through the same window" in p
    assert "-5.80%" in p and "peak drawdown -6.20%" in p
    assert "regime: High_Fragility, fragility score 1.72" in p
    assert "model: prophet" in p
    assert "next 30 trading days +1.80%" in p
    assert "interval width at horizon 12.4%" in p
    assert "VTI: return -5.50%, contribution -1.93%" in p
    assert "XYZ" not in p                       # no real data -> omitted, not zeroed
    assert "Surprise 50bps hike" in p
    assert "NEVER use em dashes" in p


def test_market_event_prompt_omits_absent_sections():
    facts = dict(FACTS, benchmark=None, forecast=None, event_summary="")
    p = rn.build_market_event_prompt(facts)
    assert "through the same window" not in p    # no benchmark block
    assert "No engine forecast is available for this run." in p
    assert "median projected return" not in p
    assert "Advisor's event description" not in p


def test_market_event_prompt_grounds_reconciliation_on_one_basis():
    p = rn.build_market_event_prompt(FACTS)
    assert "Downside on one basis (dollars for this portfolio)" in p
    assert "1-day VaR95: -$51K (-2.10%)" in p
    assert "realized max drawdown: -$127K (-5.20%)" in p
    assert "forecast downside (low end): -$76K" in p
    assert "fragility reading: elevated (above the 1.5 fragile threshold)" in p
    # No simulated scenario set in a single-event briefing -> no worst-scenario
    # row and no consistency flag are fabricated.
    assert "worst simulated scenario" not in p
    assert "CONSISTENCY FLAG" not in p
    # The narrator is instructed to produce the one-view synthesis field.
    assert "risk_synthesis" in p


def test_market_event_prompt_omits_reconciliation_when_absent():
    p = rn.build_market_event_prompt(dict(FACTS, risk_reconciliation=None))
    assert "Downside on one basis" not in p


def test_run_market_event_strips_any_dash_that_slips_through():
    with patch.object(rn, "generate", return_value=_fake(_payload(
            risk_synthesis="The event cost more than VaR — but less than the drawdown",
            outlook="Uncertainty is high — very high – indeed",
            considerations=["Watch VTI — it dominated the loss"]))):
        out, _ = rn.run_market_event(facts=FACTS)
    assert "—" not in json.dumps(out) and "–" not in json.dumps(out)
    assert out["outlook"] == "Uncertainty is high, very high, indeed"
    assert out["risk_synthesis"] == "The event cost more than VaR, but less than the drawdown"


def test_run_market_event_cache_key_tracks_facts():
    captured = {}

    def _cap(prompt, **kw):
        captured.update(kw)
        return _fake(_payload())

    with patch.object(rn, "generate", side_effect=_cap):
        rn.run_market_event(facts=FACTS)
    key = captured["cache_key_extra"]
    assert key["event_name"] == "Rate Shock"
    assert key["event_date"] == "2026-03-10"
    assert key["event_return"] == pytest.approx(-0.032)
    assert key["bench_return"] == pytest.approx(-0.058)
    assert key["forecast_return"] == pytest.approx(1.8)
    assert captured["agent_name"] == "market_event_narrator"
    assert captured["schema"] is rn.MarketEventNarrative


def test_run_market_event_cache_key_handles_missing_benchmark_and_forecast():
    captured = {}

    def _cap(prompt, **kw):
        captured.update(kw)
        return _fake(_payload())

    with patch.object(rn, "generate", side_effect=_cap):
        rn.run_market_event(facts=dict(FACTS, benchmark=None, forecast=None))
    key = captured["cache_key_extra"]
    assert key["bench_return"] is None
    assert key["forecast_return"] is None


def test_run_market_event_cache_key_tracks_reconciliation():
    captured = {}

    def _cap(prompt, **kw):
        captured.update(kw)
        return _fake(_payload())

    with patch.object(rn, "generate", side_effect=_cap):
        rn.run_market_event(facts=FACTS)
    assert captured["cache_key_extra"]["recon_maxdd"] == pytest.approx(-0.052)
    # Omitted reconciliation -> None in the cache key, never invented.
    with patch.object(rn, "generate", side_effect=_cap):
        rn.run_market_event(facts=dict(FACTS, risk_reconciliation=None))
    assert captured["cache_key_extra"]["recon_maxdd"] is None


def test_run_market_event_raises_on_malformed_json():
    with patch.object(rn, "generate", return_value=_fake("nope")):
        with pytest.raises(ValueError, match="malformed JSON"):
            rn.run_market_event(facts=FACTS)


# ── Router helpers: real event window + date-aligned benchmark ────────


def _trading_days(n=60, start="2026-01-05"):
    return list(pd.bdate_range(start, periods=n).to_pydatetime())


def _iso(dts):
    return [dt.strftime("%Y-%m-%d") for dt in dts]


def test_slice_event_window_centers_on_real_event_date():
    ts = _trading_days()
    prices = [100.0 + i for i in range(60)]
    w = rr._slice_event_window(_iso(ts), prices, ts[30])
    assert w["dates"] == ts[15:46]              # 15 before + event day + 15 after
    assert w["event_pos"] == 15
    assert w["anchor"] == 14                    # last trading day BEFORE the event
    # Impact from the last pre-event close through the window end, on REAL data
    assert w["event_return"] == pytest.approx(prices[45] / prices[29] - 1)
    assert w["port_idx"][0] == pytest.approx(100.0)
    assert len(w["port_dd"]) == 31


def test_slice_event_window_anchors_weekend_event_to_prior_close():
    ts = _trading_days()                        # starts Monday 2026-01-05
    prices = [100.0 + i for i in range(60)]
    saturday = datetime(2026, 1, 10)
    w = rr._slice_event_window(_iso(ts), prices, saturday)
    assert w["dates"][w["event_pos"]] == datetime(2026, 1, 12)   # next trading day
    assert w["dates"][w["anchor"]] == datetime(2026, 1, 9)       # Friday before
    # No fabricated weekend points: every window date is a real trading day
    assert all(dt.weekday() < 5 for dt in w["dates"])


def test_slice_event_window_event_on_first_day():
    ts = _trading_days()
    prices = [100.0 + i for i in range(60)]
    w = rr._slice_event_window(_iso(ts), prices, ts[0])
    assert w["anchor"] == 0 and w["event_pos"] == 0
    assert w["event_return"] == pytest.approx(prices[15] / prices[0] - 1)


@pytest.mark.parametrize("bad_date", [datetime(2020, 1, 1), datetime(2027, 1, 1)])
def test_slice_event_window_rejects_out_of_history_event(bad_date):
    ts = _trading_days()
    prices = [100.0 + i for i in range(60)]
    with pytest.raises(HTTPException) as exc:
        rr._slice_event_window(_iso(ts), prices, bad_date)
    assert exc.value.status_code == 400
    assert "outside the available price history" in exc.value.detail


def test_slice_event_window_rejects_empty_history():
    with pytest.raises(HTTPException) as exc:
        rr._slice_event_window([], [], datetime(2026, 1, 6))
    assert exc.value.status_code == 400


def _bench_df(dts, closes):
    return pd.DataFrame({"date": pd.to_datetime(dts), "close": closes})


def test_align_benchmark_matches_by_date():
    window = _trading_days(31)
    closes = [50.0 + i for i in range(31)]
    out = rr._align_benchmark_to_dates(_bench_df(window, closes), window)
    assert out is not None and len(out) == 31
    assert out[0] == pytest.approx(100.0)
    assert out[-1] == pytest.approx(closes[-1] / closes[0] * 100)


def test_align_benchmark_ffills_small_interior_gaps():
    window = _trading_days(31)
    keep = [i for i in range(31) if i not in (10, 11)]   # 29/31 coverage
    df = _bench_df([window[i] for i in keep], [50.0 + i for i in keep])
    out = rr._align_benchmark_to_dates(df, window)
    assert out is not None and len(out) == 31
    assert out[10] == pytest.approx(out[9])              # forward-filled holiday gap


def test_align_benchmark_returns_none_when_alignment_impossible():
    window = _trading_days(31)
    # Missing first window date -> no honest base point
    df_no_head = _bench_df(window[1:], [50.0 + i for i in range(1, 31)])
    assert rr._align_benchmark_to_dates(df_no_head, window) is None
    # Sparse coverage (many missing dates) -> omit rather than pad
    keep = list(range(0, 31, 2))
    df_sparse = _bench_df([window[i] for i in keep], [50.0 + i for i in keep])
    assert rr._align_benchmark_to_dates(df_sparse, window) is None
    # No data at all
    empty = pd.DataFrame(columns=["date", "close"])
    assert rr._align_benchmark_to_dates(empty, window) is None
    # Shifted dates that never overlap the window -> None, never positional
    shifted = [dt + timedelta(days=200) for dt in window]
    df_shifted = _bench_df(shifted, [50.0 + i for i in range(31)])
    assert rr._align_benchmark_to_dates(df_shifted, window) is None


# ── Template (end-to-end PDF build) ───────────────────────────────────


def _template_data(**over):
    dates = _trading_days(31, start="2026-02-17")
    event_date = dates[16]
    rng = np.random.default_rng(7)
    port_ret = rng.normal(-0.001, 0.008, 31)
    port_ret[16:19] = [-0.020, -0.011, 0.006]
    bench_ret = rng.normal(-0.0015, 0.011, 31)
    bench_ret[16:19] = [-0.030, -0.016, 0.004]
    port_idx = 100 * np.cumprod(1 + port_ret)
    bench_idx = 100 * np.cumprod(1 + bench_ret)
    port_dd = ((port_idx / np.maximum.accumulate(port_idx)) - 1) * 100
    bench_dd = ((bench_idx / np.maximum.accumulate(bench_idx)) - 1) * 100

    data = {
        "client_name": "Growth Fund",
        "advisor_name": "Alex Advisor",
        "firm_name": "Example Advisors",
        "report_date": datetime(2026, 4, 2),
        "portfolio_value": 2_450_000,
        "event_name": "Rate Shock",
        "event_date": event_date,
        "event_summary": "Surprise 50bps hike; equities sold off sharply.",
        "portfolio_return_event": float(port_idx[-1] / port_idx[15] - 1),
        "benchmark_return_event": float(bench_idx[-1] / bench_idx[15] - 1),
        "benchmark_label": "S&P 500",
        "portfolio_drawdown_peak": float(port_dd.min() / 100.0),
        "regime": "High_Fragility",
        "fragility_score": 1.72,
        "holdings_impact": [
            {"ticker": "VTI", "name": "Vanguard Total Stock",
             "return": -0.055, "contribution": -0.0193},
            {"ticker": "GLD", "name": "SPDR Gold Shares",
             "return": 0.022, "contribution": 0.0018},
            {"ticker": "XYZ", "name": "No Data Asset",
             "return": None, "contribution": None},
        ],
        "forecast_facts": {"model": "prophet", "horizon_days": 30,
                           "return_pct": 1.8, "band_pct": 12.4},
        # Risk in one view: the standing downside measures on one dollar basis,
        # beside the measured event impact. No scenario set for a single event,
        # so worst_scenario is None and no consistency flag fires.
        "risk_reconciliation": {
            "portfolio_value": 2_450_000.0,
            "var_1d_pct": -0.021, "var_1d_dollars": -51_450.0,
            "max_drawdown_pct": -0.052, "max_drawdown_dollars": -127_400.0,
            "worst_scenario": None, "worst_scenario_dollars": None,
            "forecast_downside_pct": -3.1, "forecast_downside_dollars": -75_950.0,
            "fragility_label": "elevated (above the 1.5 fragile threshold)",
            "flags": [],
        },
        # Honest track record: directional accuracy with a 95% CI that includes
        # the 50% coin-flip baseline (so it is NOT read as a reliable edge).
        "track_record": {"hit_rate": 0.58, "n_steps": 60, "ci_low": 0.45,
                         "ci_high": 0.71, "beats_coinflip": False,
                         "best_model": "prophet"},
        "narrative": {
            "event_commentary": "The portfolio fell with the sell-off and partly recovered.",
            "benchmark_commentary": "The portfolio's drawdown stayed shallower than the benchmark's.",
            "risk_synthesis": ("The event's move stayed within the portfolio's realized "
                               "maximum drawdown; the 1-day VaR is the shallowest measure."),
            "outlook": "The model's median path implies a modest recovery over 30 trading days.",
            "considerations": ["Evaluate the VTI position given its -5.5% event return."],
        },
        "dates": dates,
        "portfolio_index": port_idx.tolist(),
        "benchmark_index": bench_idx.tolist(),
        "portfolio_dd": port_dd.tolist(),
        "benchmark_dd": bench_dd.tolist(),
    }
    data.update(over)
    return data


def _assert_pdf(path):
    blob = path.read_bytes()
    assert blob.startswith(b"%PDF")
    assert len(blob) > 10_000


def test_generate_market_event_report_builds_pdf(tmp_path):
    out = tmp_path / "event.pdf"
    generate_market_event_report(str(out), _template_data())
    _assert_pdf(out)


def test_generate_market_event_report_omits_benchmark_when_unaligned(tmp_path):
    """No benchmark, no narrative, no forecast: the PDF still builds,
    numbers-only, with the benchmark omitted rather than padded."""
    out = tmp_path / "event_min.pdf"
    generate_market_event_report(str(out), _template_data(
        benchmark_return_event=None, benchmark_index=None, benchmark_dd=None,
        benchmark_label=None, narrative=None, forecast_facts=None,
    ))
    _assert_pdf(out)


def test_generate_market_event_report_handles_missing_forecast_interval(tmp_path):
    """A forecast without a confidence interval renders the no-interval note."""
    out = tmp_path / "event_noband.pdf"
    generate_market_event_report(str(out), _template_data(
        forecast_facts={"model": "arima", "horizon_days": 30,
                        "return_pct": -0.9, "band_pct": None},
    ))
    _assert_pdf(out)


def test_generate_market_event_report_escapes_user_text(tmp_path):
    """Advisor-typed event text with XML-special characters must not break
    the PDF build."""
    out = tmp_path / "event_escape.pdf"
    generate_market_event_report(str(out), _template_data(
        event_name="Rates <up> & vol",
        event_summary="Yields rose > 5% & spreads widened <sharply>.",
    ))
    _assert_pdf(out)


def test_generate_market_event_report_omits_reconciliation_and_track_record(tmp_path):
    """No dollar reconciliation and no walk-forward validation figures: the
    risk-in-one-view box degrades to just the measured event impact, and the
    model-track-record line is omitted rather than fabricated."""
    out = tmp_path / "event_no_recon.pdf"
    generate_market_event_report(str(out), _template_data(
        risk_reconciliation=None, track_record=None, narrative=None,
    ))
    _assert_pdf(out)


def test_generate_market_event_report_surfaces_consistency_flag(tmp_path):
    """When a consistency flag is present it is rendered; the PDF still builds."""
    out = tmp_path / "event_flag.pdf"
    recon = dict(_template_data()["risk_reconciliation"])
    recon["flags"] = ["The worst simulated scenario is milder than the portfolio's "
                      "own realized maximum drawdown; the stress set may understate "
                      "tail risk."]
    generate_market_event_report(str(out), _template_data(risk_reconciliation=recon))
    _assert_pdf(out)


def test_generate_market_event_report_escapes_ai_and_reconciliation_text(tmp_path):
    """AI risk-synthesis text and the reconciliation's fragility label with
    XML-special characters must not break the PDF build."""
    out = tmp_path / "event_ai_escape.pdf"
    data = _template_data()
    data["narrative"]["risk_synthesis"] = "VaR < drawdown & the event move > 0."
    data["risk_reconciliation"] = dict(data["risk_reconciliation"],
                                       fragility_label="elevated & <flagged>")
    generate_market_event_report(str(out), data)
    _assert_pdf(out)
