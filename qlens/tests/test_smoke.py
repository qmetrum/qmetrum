"""Smoke test: orchestration + schema with a fake LLM. No network, no API cost."""
from qlens.orchestrator import DISCLAIMER, run_lens
from qlens.schemas import STANCES, Fact


class FakeLLM:
    def generate(self, prompt: str) -> str:
        if "BULL analyst" in prompt:
            return '{"points": ["Momentum is positive [1]", "Valuation reasonable [4]"]}'
        if "BEAR analyst" in prompt:
            return '{"points": ["Near range highs [2]", "Beta elevated [5]"]}'
        return (
            '{"stance": "Hold", "conviction": "medium", '
            '"key_risks": ["Multiple compression [4]"], '
            '"what_would_change_my_mind": ["A break below range [2]"], '
            '"rationale": "Balanced setup [1][2]."}'
        )


def _facts():
    return [Fact(i, "test", f"fact {i}") for i in range(6)]


def test_run_lens_with_fake_llm():
    v = run_lens("aapl", llm=FakeLLM(), facts=_facts())
    assert v.ticker == "AAPL"
    assert v.stance in STANCES and v.stance == "Hold"
    assert v.conviction == "medium"
    assert v.bull and v.bear
    assert v.disclaimer == DISCLAIMER
    assert isinstance(v.to_dict(), dict)


def test_bad_stance_and_conviction_coerced():
    class Bad(FakeLLM):
        def generate(self, prompt: str) -> str:
            if "PORTFOLIO MANAGER" in prompt:
                return '{"stance": "YOLO", "conviction": "insane"}'
            return super().generate(prompt)

    v = run_lens("MSFT", llm=Bad(), facts=_facts())
    assert v.stance == "Hold"      # invalid stance coerced to a safe default
    assert v.conviction == "low"   # invalid conviction coerced
