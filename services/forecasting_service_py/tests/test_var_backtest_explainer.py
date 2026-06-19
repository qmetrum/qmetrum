"""Tests for app.agents.var_backtest_explainer (LLM mocked — no Gemini call)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.agents import var_backtest_explainer as vbe
from app.agents.llm import LlmResult


COMPARE = {
    "confidence": 0.95, "horizon_days": 1, "n_observations": 120, "weight_mode": "constant",
    "data_window": {"start": "2021-05-01", "end": "2026-04-29"},
    "recommended": {"key": "mps_d8", "label": "MPS fan (d=8)", "why": "closest to target"},
    "methods": [
        {"key": "historical", "label": "Historical", "status": "ok", "breach_rate": 0.028,
         "expected_breach_rate": 0.05, "kupiec": {"p_value": 0.08, "reject": False},
         "christoffersen_cc": {"p_value": 0.09, "reject": False}, "basel_zone": "green", "model_passes": True},
        {"key": "mps_d4", "label": "MPS fan (d=4)", "status": "ok", "breach_rate": 0.158,
         "expected_breach_rate": 0.05, "kupiec": {"p_value": 0.0, "reject": True},
         "christoffersen_cc": {"p_value": 0.0, "reject": True}, "basel_zone": "red", "model_passes": False},
        {"key": "mps_d16", "label": "MPS fan (d=16)", "status": "skipped",
         "reason": "d^N exceeds dense-tensor cap"},
    ],
}


def test_build_prompt_is_grounded():
    p = vbe.build_prompt("Big Tech Growth", COMPARE)
    assert "Big Tech Growth" in p
    assert "15.8%" in p and "FAILS" in p          # d=4 numbers present
    assert "MPS fan (d=8)" in p and "Recommended" in p
    assert "skipped" in p                          # skipped method surfaced
    assert "do not invent" in p.lower() or "only the supplied" in p.lower()


def _fake(text: str) -> LlmResult:
    return LlmResult(text=text, model="gemini-2.5-flash", prompt_tokens=10,
                     output_tokens=20, latency_ms=5, cached=False, input_hash="x")


def test_run_parses_structured_output():
    payload = {
        "headline": "Trustworthy via d=8; d=4 anti-conservative.",
        "assessment": "Historical and d=8 pass; d=4 breaches 15.8% vs 5%.",
        "method_notes": [{"method": "MPS fan (d=4)", "note": "too many breaches"}],
        "watch": ["d=4 anti-conservative tails"],
    }
    with patch.object(vbe, "generate", return_value=_fake(json.dumps(payload))):
        parsed, result = vbe.run(portfolio_name="Big Tech Growth", compare=COMPARE)
    assert parsed["headline"].startswith("Trustworthy")
    assert parsed["watch"] == ["d=4 anti-conservative tails"]
    assert result.model == "gemini-2.5-flash"


def test_run_raises_on_malformed_json():
    with patch.object(vbe, "generate", return_value=_fake("not json")):
        with pytest.raises(ValueError, match="malformed JSON"):
            vbe.run(portfolio_name="X", compare=COMPARE)


def test_run_cache_key_tracks_verdicts():
    # The cache_key_extra must include each method's verdict so the explanation
    # regenerates when the backtest changes.
    captured = {}

    def _capture(prompt, **kwargs):
        captured.update(kwargs)
        return _fake(json.dumps({"headline": "h", "assessment": "a", "method_notes": [], "watch": []}))

    with patch.object(vbe, "generate", side_effect=_capture):
        vbe.run(portfolio_name="X", compare=COMPARE)
    keys = {m["key"] for m in captured["cache_key_extra"]["methods"]}
    assert {"historical", "mps_d4", "mps_d16"} <= keys
    assert captured["agent_name"] == "var_backtest_explain"
    assert captured["schema"] is vbe.VarBacktestExplanation
