"""Tests for app.agents.scenario_explainer (LLM mocked — no Gemini call)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.agents import scenario_explainer as se
from app.agents.llm import LlmResult


def _fan(start: float, end: float, n: int = 5, lo2: float | None = None, hi2: float | None = None):
    step = (end - start) / (n - 1)
    central = [start + step * i for i in range(n)]
    fan: dict = {"central": central}
    if lo2 is not None:
        fan["lower_2s"] = [v - (lo2 * i / (n - 1)) for i, v in enumerate(central)]
        fan["lower_2s"][-1] = central[-1] - lo2
    if hi2 is not None:
        fan["upper_2s"] = [v + (hi2 * i / (n - 1)) for i, v in enumerate(central)]
        fan["upper_2s"][-1] = central[-1] + hi2
    return fan


SCENARIOS = [
    {"name": "base", "fan": _fan(100.0, 104.0, lo2=8.0, hi2=8.0)},
    {"name": "bear_10", "shock_pct": -10.0, "vol_scale": 1.0, "drift_shift": 0.0,
     "fan": _fan(90.0, 93.6, lo2=9.0, hi2=9.0)},
    {"name": "high_vol_regime", "shock_pct": 0.0, "vol_scale": 1.25, "drift_shift": 0.0,
     "fan": _fan(100.0, 104.0, lo2=14.0, hi2=14.0)},
    # NB: _discovery values are decimal FRACTIONS in production
    # (adversarial_discovery.py) — -0.124 means a -12.4% shock.
    {"name": "worst_case_cvar", "fan": _fan(84.0, 87.0, lo2=10.0, hi2=10.0),
     "discovery": {"cvar": -0.1834, "shock_pcts": {"AAPL": -0.124, "TLT": -0.031},
                   "shock_vector_sigma": [-2.1, -0.5], "runtime_ms": 900}},
]


def _fake(text: str) -> LlmResult:
    return LlmResult(text=text, model="gemini-2.5-flash", prompt_tokens=10,
                     output_tokens=20, latency_ms=5, cached=False, input_hash="x")


def _payload(names):
    return json.dumps({"summary": "exec-summary", "explanations": [
        {"name": n, "headline": f"h-{n}", "narrative": f"n-{n}"} for n in names
    ]})


# ---------------------------------------------------------------- derivation

def test_derive_facts_vs_base_and_dollar_impact():
    facts = se.derive_facts(SCENARIOS, portfolio_value=1_000_000)
    by_name = {f["name"]: f for f in facts}
    # bear_10 ends at 93.6 vs base end 104.0 -> -10.0%
    assert by_name["bear_10"]["vs_base_pct"] == pytest.approx(-10.0, abs=0.01)
    assert by_name["bear_10"]["dollar_impact"] == pytest.approx(-100_000, rel=0.001)
    # base compares to its own path, not to itself
    assert by_name["base"]["is_base"] and by_name["base"]["vs_base_pct"] is None
    assert by_name["base"]["path_return_pct"] == pytest.approx(4.0, abs=0.01)
    # high-vol: same median as base but wider band
    assert by_name["high_vol_regime"]["vs_base_pct"] == pytest.approx(0.0, abs=0.01)
    assert by_name["high_vol_regime"]["band_pct"] > by_name["base"]["band_pct"]


def test_find_base_name_fallbacks():
    assert se.find_base_name([{"name": "base", "fan": {}}, {"name": "x", "fan": {}}]) == "base"
    assert se.find_base_name([{"name": "Base Case", "shock_pct": 0, "fan": {}}]) == "Base Case"
    assert se.find_base_name(
        [{"name": "Neutral", "shock_pct": 0.0, "vol_scale": 1.0, "drift_shift": 0.0, "fan": {}}]
    ) == "Neutral"
    assert se.find_base_name([{"name": "Bear", "shock_pct": -5.0, "fan": {}}]) is None
    # vol_scale=0 is a vol-suppressed run, NOT a neutral reference
    assert se.find_base_name(
        [{"name": "no_vol", "shock_pct": 0.0, "vol_scale": 0.0, "drift_shift": 0.0, "fan": {}}]
    ) is None


# -------------------------------------------------------------------- prompt

def test_build_prompt_is_grounded():
    facts = se.derive_facts(SCENARIOS, portfolio_value=1_000_000)
    p = se.build_prompt("Growth Fund", 1_000_000, facts)
    assert "Growth Fund" in p and "$1.00M" in p
    assert '"bear_10"' in p and "shock -10.0%" in p
    assert "[BASE reference]" in p
    # worst_case_cvar's per-asset attribution is surfaced, SCALED from the
    # decimal fractions production sends to percent (regression: 100x bug)
    assert "AAPL: -12.4%" in p and "TLT: -3.1%" in p
    assert "CVaR" in p and "-18.3%" in p          # cvar labeled and scaled too
    assert "server-generated" in p          # no user knobs on worst_case_cvar
    assert "only the supplied numbers" in p.lower()
    assert "recommendation" in p.lower() or "recommendations" in p.lower()


# ----------------------------------------------------------------------- run

def test_run_single_batched_call_and_alignment():
    calls = []

    def _capture(prompt, **kwargs):
        calls.append(kwargs)
        # Model returns entries out of order — run() must realign to input order.
        return _fake(_payload(["worst_case_cvar", "base", "bear_10", "high_vol_regime"]))

    with patch.object(se, "generate", side_effect=_capture):
        summary, explanations, facts, result = se.run(
            portfolio_name="P", portfolio_value=500_000, scenarios=SCENARIOS)
    assert len(calls) == 1                       # ONE batched call for the whole set
    assert [e["name"] for e in explanations] == [s["name"] for s in SCENARIOS]
    assert explanations[0]["headline"] == "h-base"
    assert calls[0]["agent_name"] == "scenario_explain"
    assert calls[0]["schema"] is se.ScenarioExplanations


def test_run_cache_key_is_data_dependent():
    captured = {}

    def _capture(prompt, **kwargs):
        captured.update(kwargs)
        return _fake(_payload([s["name"] for s in SCENARIOS]))

    with patch.object(se, "generate", side_effect=_capture):
        se.run(portfolio_name="P", portfolio_value=500_000, scenarios=SCENARIOS)
    key = captured["cache_key_extra"]["scenarios"]
    by_name = {k["name"]: k for k in key}
    # Terminal simulated levels (not just knobs) key the cache, so narratives
    # regenerate when market data moves the fans.
    assert by_name["bear_10"]["end"] == pytest.approx(93.6)
    assert by_name["bear_10"]["downside_end"] == pytest.approx(84.6)


def test_run_raises_on_malformed_json():
    with patch.object(se, "generate", return_value=_fake("not json")):
        with pytest.raises(ValueError, match="malformed JSON"):
            se.run(portfolio_name="P", portfolio_value=1.0, scenarios=SCENARIOS)


def test_fact_block_skips_garbage_discovery():
    scenarios = [
        {"name": "base", "fan": _fan(100.0, 104.0)},
        {"name": "worst_case_cvar", "fan": _fan(84.0, 87.0),
         "discovery": {"cvar": "n/a", "shock_pcts": {"AAPL": "bad", "TLT": -0.05}}},
    ]
    facts = se.derive_facts(scenarios, portfolio_value=1_000_000)
    p = se.build_prompt("P", 1_000_000, facts)   # must not raise
    assert "TLT: -5.0%" in p and "AAPL" not in p # numeric kept, garbage skipped
    # non-numeric cvar → the fact line is omitted ("CVaR" itself is in SYSTEM_PROMPT)
    assert "found by adversarial search" not in p


def test_run_never_misattributes_on_dropped_entry():
    # Model returns correctly-named entries for all but the FIRST scenario:
    # that slot must be skipped, not steal another scenario's narrative.
    names = [s["name"] for s in SCENARIOS]
    with patch.object(se, "generate", return_value=_fake(_payload(names[1:]))):
        _, explanations, _, _ = se.run(portfolio_name="P", portfolio_value=1.0, scenarios=SCENARIOS)
    got = {e["name"]: e for e in explanations}
    assert "base" not in got                     # dropped, not borrowed
    for n in names[1:]:
        assert got[n]["headline"] == f"h-{n}"    # everyone else keeps their own


def test_run_duplicate_names_do_not_collapse():
    dups = [
        {"name": "dup", "shock_pct": 4.0, "fan": _fan(100.0, 104.0)},
        {"name": "dup", "shock_pct": -11.0, "fan": _fan(100.0, 89.0)},
    ]
    two = json.dumps({"explanations": [
        {"name": "dup", "headline": "up", "narrative": "rises"},
        {"name": "dup", "headline": "down", "narrative": "falls"},
    ]})
    with patch.object(se, "generate", return_value=_fake(two)):
        _, explanations, _, _ = se.run(portfolio_name="P", portfolio_value=1.0, scenarios=dups)
    assert [e["headline"] for e in explanations] == ["up", "down"]


def test_run_tolerates_bare_array_output():
    # Wrapper-dropping: model returns a top-level array instead of
    # {"explanations": [...]} — run() must accept it, not crash with a 500.
    bare = json.dumps([
        {"name": s["name"], "headline": f"h-{s['name']}", "narrative": "n"} for s in SCENARIOS
    ])
    with patch.object(se, "generate", return_value=_fake(bare)):
        _, explanations, _, _ = se.run(portfolio_name="P", portfolio_value=1.0, scenarios=SCENARIOS)
    assert [e["name"] for e in explanations] == [s["name"] for s in SCENARIOS]


def test_run_raises_on_non_object_json():
    with patch.object(se, "generate", return_value=_fake(json.dumps("just a string"))):
        with pytest.raises(ValueError, match="not an object or array"):
            se.run(portfolio_name="P", portfolio_value=1.0, scenarios=SCENARIOS)


def test_run_raises_on_empty_explanations():
    with patch.object(se, "generate", return_value=_fake(json.dumps({"explanations": []}))):
        with pytest.raises(ValueError, match="no explanations"):
            se.run(portfolio_name="P", portfolio_value=1.0, scenarios=SCENARIOS)


# ------------------------------------------------------------------ endpoint

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


def _request_body():
    return {
        "portfolio_name": "Growth Fund",
        "portfolio_value": 1_000_000,
        "scenarios": [
            {"name": s["name"], **{k: s[k] for k in ("shock_pct", "vol_scale", "drift_shift") if k in s},
             "fan": s["fan"], **({"discovery": s["discovery"]} if "discovery" in s else {})}
            for s in SCENARIOS
        ],
    }


def test_endpoint_explains_each_scenario(client):
    with patch.object(se, "generate",
                      return_value=_fake(_payload([s["name"] for s in SCENARIOS]))):
        r = client.post("/agents/scenario-explain", json=_request_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert [e["name"] for e in body["explanations"]] == [s["name"] for s in SCENARIOS]
    assert body["summary"] == "exec-summary"
    assert body["disclaimer"]
    # source_data carries derived facts, not raw path arrays
    src = body["source_data"]["scenarios"]
    assert src[1]["vs_base_pct"] == pytest.approx(-10.0, abs=0.01)
    assert "fan" not in src[0] and "central" not in src[0]
    # source_data echoes the raw fractional discovery values as received
    assert src[3]["discovery"]["shock_pcts"]["AAPL"] == pytest.approx(-0.124)


def test_endpoint_rejects_empty_and_underscore_only(client):
    r = client.post("/agents/scenario-explain", json={
        "portfolio_name": "P", "portfolio_value": 1.0, "scenarios": []})
    assert r.status_code == 422  # pydantic min_length
    r = client.post("/agents/scenario-explain", json={
        "portfolio_name": "P", "portfolio_value": 1.0,
        "scenarios": [{"name": "_mps", "fan": {"central": [1.0, 2.0]}}]})
    assert r.status_code == 400


def test_endpoint_rejects_short_fan(client):
    r = client.post("/agents/scenario-explain", json={
        "portfolio_name": "P", "portfolio_value": 1.0,
        "scenarios": [{"name": "x", "fan": {"central": [1.0]}}]})
    assert r.status_code == 422


def test_endpoint_maps_runtime_error_to_503(client):
    with patch.object(se, "generate", side_effect=RuntimeError("GOOGLE_API_KEY not set")):
        r = client.post("/agents/scenario-explain", json=_request_body())
    assert r.status_code == 503
