"""Client-letter agent: grounds on real portfolio numbers, gated narration.
Mocks the LLM and the price layer — no network, no API cost."""
from __future__ import annotations

import json

import pytest

import app.agents.client_letter as cl
from app.agents.llm import LlmResult


def _prices(n=260, start=100.0, drift=0.0003):
    # deterministic upward-drifting series with wiggle
    out = []
    p = start
    import datetime as dt
    d = dt.date(2025, 8, 1)
    for i in range(n):
        p *= (1 + drift + 0.004 * ((-1) ** i))
        out.append({"date": (d + dt.timedelta(days=i)).strftime("%Y-%m-%d"), "price": round(p, 2)})
    return out


@pytest.fixture()
def patched(monkeypatch):
    monkeypatch.setattr(cl, "get_price_series_cached",
                        lambda t, period="1y", session=None: _prices())

    # a fake regime snapshot via a fake session.exec(...).first()
    class _Row:
        status = "ok"; short_corr = 0.55; baseline_corr = 0.30; delta = 0.25
        class _AsOf:
            @staticmethod
            def strftime(f): return "2026-08-10"
        as_of = _AsOf()

    class _Exec:
        def first(self): return _Row()
    class _Session:
        def exec(self, *a, **k): return _Exec()

    payload = json.dumps({
        "greeting": "Dear [Client First Name],",
        "performance_paragraph": "Your portfolio returned a steady quarter with a calmer ride than stocks alone.",
        "diversification_paragraph": "Your realized stock-bond correlation is 0.55 versus a 0.30 baseline.",
        "closing_paragraph": "Nothing needs action today; reply anytime.",
    })

    def fake_generate(prompt, *, agent_name, schema=None, cache_key_extra=None, use_cache=True):
        fake_generate.prompt = prompt
        fake_generate.agent = agent_name
        return LlmResult(text=payload, model="fake", prompt_tokens=1, output_tokens=1,
                         latency_ms=5, cached=False, input_hash="h")
    monkeypatch.setattr(cl, "generate", fake_generate)
    return fake_generate, _Session()


def test_letter_grounds_and_gates(patched):
    fake, session = patched
    holdings = [{"ticker": "SPY", "weight": 0.6}, {"ticker": "AGG", "weight": 0.4}]
    letter, result = cl.run(portfolio_id=3, holdings=holdings, session=session)
    # real facts assembled
    assert letter["facts"]["portfolio"]["n_obs"] > 30
    assert "quarter_return_pct" in letter["facts"]["portfolio"]
    assert letter["facts"]["regime"]["short_corr"] == 0.55
    assert letter["is_draft"] is True
    assert "draft for advisor review" in letter["disclaimer"]
    # the prompt carried the honesty gate + the real numbers
    p = fake.prompt.lower()
    assert "only the supplied numbers" in p
    assert "never" in p and ("forecast" in p or "predict" in p)
    assert "baseline" in p
    assert fake.agent == "client_letter"


def test_no_history_raises(patched, monkeypatch):
    _, session = patched
    monkeypatch.setattr(cl, "get_price_series_cached", lambda t, period="1y", session=None: [])
    with pytest.raises(ValueError):
        cl.run(portfolio_id=3, holdings=[{"ticker": "SPY", "weight": 1.0}], session=session)


def test_regime_absent_instructs_empty_paragraph(patched, monkeypatch):
    fake, _ = patched

    class _ExecNone:
        def first(self): return None
    class _SessionNoRegime:
        def exec(self, *a, **k): return _ExecNone()

    holdings = [{"ticker": "SPY", "weight": 1.0}]
    cl.run(portfolio_id=9, holdings=holdings, session=_SessionNoRegime())
    assert "leave diversification_paragraph empty" in fake.prompt
