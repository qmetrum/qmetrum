"""QLens brief agent: grounds on Qmetrum data, honesty-gated bull/bear -> stance.
Mocks the LLM and the data layer — no network, no API cost."""
from __future__ import annotations

import json

import pytest

import app.agents.qlens_brief as qb
from app.agents.llm import LlmResult


class _FakeResult(LlmResult):
    pass


def _fake_llm_json(**over):
    base = {
        "bull": ["Momentum positive [0]", "Reasonable valuation [5]"],
        "bear": ["Near range highs [3]", "Elevated volatility [4]"],
        "stance": "Hold",
        "conviction": "medium",
        "key_risks": ["Multiple compression [5]"],
        "what_would_change_my_mind": ["A break below the range [3]"],
        "rationale": "Balanced setup weighing momentum against valuation [0][5].",
    }
    base.update(over)
    return json.dumps(base)


@pytest.fixture()
def patched(monkeypatch):
    # Deterministic Qmetrum data
    monkeypatch.setattr(qb, "get_price_series_cached",
                        lambda t, period="1y": [{"date": f"2026-01-{(i % 28) + 1:02d}", "price": 100 + i}
                                                for i in range(200)])
    monkeypatch.setattr(qb, "get_fundamentals_cached",
                        lambda t: {"profile": {"sector": "Technology"},
                                   "valuation": {"pe_ratio": 24.0, "market_cap": 3.1e12},
                                   "technicals": {"beta": 1.2}})

    captured = {}

    def fake_generate(prompt, *, agent_name, schema=None, cache_key_extra=None, use_cache=True):
        captured["prompt"] = prompt
        captured["agent_name"] = agent_name
        return LlmResult(text=fake_generate.payload, model="fake", prompt_tokens=1,
                         output_tokens=1, latency_ms=5, cached=False, input_hash="h")
    fake_generate.payload = _fake_llm_json()
    monkeypatch.setattr(qb, "generate", fake_generate)
    return captured, fake_generate


def test_brief_grounds_and_returns_structured(patched):
    captured, _ = patched
    brief, result = qb.run("aapl")
    assert brief["ticker"] == "AAPL"
    assert brief["stance"] == "Hold" and brief["conviction"] == "medium"
    assert brief["bull"] and brief["bear"]
    # grounded in Qmetrum's own data
    assert any(f["source"].startswith("qmetrum/price") for f in brief["facts"])
    assert any(f["source"] == "qmetrum/fundamentals" for f in brief["facts"])
    # the prompt carried the honesty gate
    assert "never invent" in captured["prompt"].lower() or "never state or imply" in captured["prompt"].lower()
    assert captured["agent_name"] == "qlens_brief"
    assert brief["disclaimer"] and "not a forecast" in brief["disclaimer"]


def test_bad_stance_and_conviction_coerced(patched):
    _, fake = patched
    fake.payload = _fake_llm_json(stance="YOLO", conviction="insane")
    brief, _ = qb.run("MSFT")
    assert brief["stance"] == "Hold"     # invalid -> safe default
    assert brief["conviction"] == "low"


def test_context_becomes_a_user_fact(patched):
    brief, _ = qb.run("AAPL", extra_context="Guidance was cut 5% for next quarter.")
    assert any(f["source"] == "user-context" and "guidance" in f["statement"].lower()
               for f in brief["facts"])


def test_malformed_json_raises(patched):
    _, fake = patched
    fake.payload = "not json at all"
    with pytest.raises(ValueError):
        qb.run("AAPL")
