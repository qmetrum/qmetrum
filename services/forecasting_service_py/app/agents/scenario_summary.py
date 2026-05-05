"""Scenario results summarizer.

Input: a set of scenarios that were just run, each with params + computed
return + dollar impact. Output: a short executive paragraph comparing
outcomes and flagging the most consequential scenario.
"""
from __future__ import annotations

from typing import Any

from app.agents.llm import generate, LlmResult
from app.agents.disclaimer import with_disclaimer


SYSTEM_PROMPT = """You write a brief executive summary (3-5 sentences) interpreting a set of scenario-simulation results on a portfolio.

Style:
- Plain English, factual, neutral — like a risk analyst's note.
- Use the exact numbers supplied; do not invent figures.
- Compare best vs. worst case. State the dollar impact of the worst case.
- If a pattern is obvious (e.g. downside driven mostly by equity shock rather than vol), call it out.
- No trade recommendations. No price targets.
"""


def _fmt_money(v: float) -> str:
    sign = "-" if v < 0 else ""
    mag = abs(v)
    if mag >= 1_000_000:
        return f"{sign}${mag / 1_000_000:.2f}M"
    if mag >= 1_000:
        return f"{sign}${mag / 1_000:.0f}K"
    return f"{sign}${mag:,.0f}"


def _fmt_pct(v: float) -> str:
    return f"{v:+.1f}%"


def build_prompt(
    portfolio_name: str,
    portfolio_value: float,
    scenarios: list[dict[str, Any]],
) -> str:
    lines = []
    for s in scenarios:
        lines.append(
            f"- {s['name']}: shock {s.get('shock_pct', 0):+.1f}%, "
            f"vol×{s.get('vol_scale', 1.0):.2f}, drift {s.get('drift_shift', 0.0):+.4f} → "
            f"return {_fmt_pct(float(s.get('return_pct', 0.0)))}, "
            f"impact {_fmt_money(float(s.get('dollar_impact', 0.0)))}"
        )

    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Portfolio: {portfolio_name}\n"
        f"Portfolio value: {_fmt_money(portfolio_value)}\n"
        f"Scenarios run:\n" + "\n".join(lines) + "\n\n"
        "Write the summary now."
    )


def run(
    *,
    portfolio_name: str,
    portfolio_value: float,
    scenarios: list[dict[str, Any]],
) -> tuple[str, LlmResult]:
    prompt = build_prompt(portfolio_name, portfolio_value, scenarios)
    scenario_key = [
        {
            "name": s["name"],
            "return_pct": round(float(s.get("return_pct", 0.0)), 4),
            "dollar_impact": round(float(s.get("dollar_impact", 0.0)), 2),
        }
        for s in scenarios
    ]
    result = generate(
        prompt,
        agent_name="scenario_summary",
        cache_key_extra={
            "portfolio_name": portfolio_name,
            "portfolio_value": round(portfolio_value, 2),
            "scenarios": scenario_key,
        },
    )
    return with_disclaimer(result.text), result
