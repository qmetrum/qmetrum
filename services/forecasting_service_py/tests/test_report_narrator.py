"""Tests for app.agents.report_narrator (LLM mocked, no Gemini call)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.agents import report_narrator as rn
from app.agents.llm import LlmResult


FACTS = {
    "portfolio_name": "Growth Fund",
    "portfolio_value": 2_500_000,
    "horizon_days": 90,
    "risk_metrics": {"annualized_vol": 0.16, "sharpe_ratio": 1.1, "sortino_ratio": 1.4,
                     "var_95_daily": -0.021, "cvar_95_daily": -0.033, "max_drawdown": -0.18,
                     "beta": 0.95, "fragility_score": 1.2, "regime": "Normal"},
    "forecast": {"return_pct": 3.8, "band_pct": 16.2},
    "scenarios": [
        {"name": "base", "return_pct": 3.8, "dollar_impact": 95_000, "downside_pct": -8.4},
        {"name": "bear_10", "return_pct": -10.0, "dollar_impact": -250_000, "downside_pct": -9.7},
    ],
    "holdings": [{"ticker": "AAA", "weight": 0.6, "sector": "Tech"},
                 {"ticker": "BBB", "weight": 0.4, "sector": "Bonds"}],
}


def _fake(text: str) -> LlmResult:
    return LlmResult(text=text, model="gemini-2.5-flash", prompt_tokens=10,
                     output_tokens=20, latency_ms=5, cached=False, input_hash="x")


def _payload(**over):
    base = {
        "executive_summary": "sum", "forecast_commentary": "fc",
        "risk_commentary": "rc", "scenario_commentary": "sc",
        "holdings_commentary": "hc", "considerations": ["c1", "c2"],
    }
    base.update(over)
    return json.dumps(base)


def test_prompt_is_grounded_and_forbids_dashes():
    p = rn.build_prompt(FACTS)
    assert "Growth Fund" in p and "$2.50M" in p
    assert "+16.00%" in p                 # annualized vol
    assert "-2.10%" in p                  # VaR
    assert "bear_10: return -10.0%" in p and "-$250K" in p
    assert "AAA: 60%" in p
    assert "NEVER use em dashes" in p


def test_run_strips_any_dash_that_slips_through():
    with patch.object(rn, "generate", return_value=_fake(_payload(
            risk_commentary="Risk is high — very high – indeed",
            considerations=["Trim AAA — it dominates"]))):
        out, _ = rn.run(facts=FACTS)
    assert "—" not in json.dumps(out) and "–" not in json.dumps(out)
    assert out["risk_commentary"] == "Risk is high, very high, indeed"


def test_run_cache_key_tracks_facts():
    captured = {}

    def _cap(prompt, **kw):
        captured.update(kw)
        return _fake(_payload())

    with patch.object(rn, "generate", side_effect=_cap):
        rn.run(facts=FACTS)
    key = captured["cache_key_extra"]
    assert key["vol"] == pytest.approx(0.16)
    assert {s["name"] for s in key["scenarios"]} == {"base", "bear_10"}
    assert captured["agent_name"] == "report_narrator"
    assert captured["schema"] is rn.ReportNarrative


def test_run_raises_on_malformed_json():
    with patch.object(rn, "generate", return_value=_fake("nope")):
        with pytest.raises(ValueError, match="malformed JSON"):
            rn.run(facts=FACTS)
