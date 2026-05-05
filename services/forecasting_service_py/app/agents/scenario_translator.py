"""Scenario translator agent.

Input: a natural-language description of a market scenario.
Output: structured params {name, shock_pct, vol_scale, drift_shift} that slot
into the existing scenarios page sliders.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.agents.llm import generate, LlmResult


class ScenarioParams(BaseModel):
    name: str = Field(description="Short 2-4 word Title-Case name, e.g. '2008 Crash'")
    shock_pct: float = Field(
        description=(
            "One-time initial return shock as a percentage (NOT a decimal). "
            "Negative for drawdowns. Must be in [-30, 30]."
        )
    )
    vol_scale: float = Field(
        description=(
            "Volatility multiplier. 1.0 = normal. Greater than 1 = more "
            "volatile. Must be in [0.5, 3.0]."
        )
    )
    drift_shift: float = Field(
        description=(
            "Per-day drift adjustment as a decimal. Negative = bearish bias. "
            "Must be in [-0.005, 0.005]."
        )
    )


SYSTEM_PROMPT = """You translate natural-language market scenarios into structured simulation parameters.

Return JSON matching the provided schema. Do not invent extreme values.

Calibration examples:
- "2008-style crash": shock_pct ≈ -25, vol_scale ≈ 2.0, drift_shift ≈ -0.003
- "mild recession": shock_pct ≈ -5, vol_scale ≈ 1.3, drift_shift ≈ -0.001
- "rate spike": shock_pct ≈ -3, vol_scale ≈ 1.5, drift_shift ≈ -0.0005
- "strong recovery / bull market": shock_pct ≈ 10, vol_scale ≈ 0.8, drift_shift ≈ 0.002
- "calm / low-vol regime": shock_pct ≈ 0, vol_scale ≈ 0.7, drift_shift ≈ 0.0005
- "tech crash / dot-com": shock_pct ≈ -20, vol_scale ≈ 1.8, drift_shift ≈ -0.002

If the user states a specific magnitude (e.g. "30% drop"), honor it exactly — clamped to the allowed range.
The `name` field should be concise, specific, and capitalized (e.g. "Tech Sector Selloff").
"""


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def run(description: str) -> tuple[ScenarioParams, LlmResult]:
    prompt = f"{SYSTEM_PROMPT}\n\nUser description: {description.strip()}\n"
    result = generate(
        prompt,
        agent_name="scenario_translator",
        schema=ScenarioParams,
    )
    data = json.loads(result.text)
    params = ScenarioParams(
        name=str(data.get("name", "Custom Scenario"))[:40] or "Custom Scenario",
        shock_pct=_clamp(float(data.get("shock_pct", 0.0)), -30.0, 30.0),
        vol_scale=_clamp(float(data.get("vol_scale", 1.0)), 0.5, 3.0),
        drift_shift=_clamp(float(data.get("drift_shift", 0.0)), -0.005, 0.005),
    )
    return params, result
