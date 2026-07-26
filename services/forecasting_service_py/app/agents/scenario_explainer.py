"""Per-scenario explainer.

Input: the scenario fans a portfolio forecast just produced (percentile band
paths per scenario, plus the scenario's setup knobs when user-defined and the
_discovery attribution for the adversarial worst case). Output: a structured
explanation PER SCENARIO — what the scenario models and what its simulated
outcome shows — via ONE batched LLM call for the whole set.

Unlike scenario_summary (one aggregate paragraph, grounded in a client-side
knob heuristic), this agent derives its facts server-side from the actual
simulated paths: median terminal outcome vs the base scenario, tail levels,
band width, and the worst point on the median path.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel

from app.agents.llm import generate, LlmResult


SYSTEM_PROMPT = """You are a buy-side risk analyst describing scenario-simulation results on ONE portfolio to its manager.

For EACH scenario below, explain what the scenario models and what its simulated outcome shows. Each block supplies:
- Setup knobs when user-defined: one-time price shock (%), volatility multiple (x), daily drift shift.
- Simulated results over the horizon: the median (p50) path's start/end level and return, the return of its end level vs the BASE scenario's end level, the estimated dollar impact at that relative return, pessimistic and optimistic tail end levels (2.5th/5th and 97.5th/95th percentile paths), the width of the 95% band at the horizon (uncertainty), and the lowest point on the median path.
- For the machine-discovered adversarial scenario (worst_case_cvar): the per-asset shock attribution and the tail-loss measure (CVaR) that a gradient search minimized using the portfolio's cross-asset dependence model.

Write:
- summary: a 3-5 sentence executive paragraph comparing outcomes ACROSS the whole set — best vs worst case with the worst case's dollar impact, whether the downside is driven by price shocks or volatility, and what the adversarial scenario adds if present.
- For each scenario:
  - headline: ONE sentence — what this scenario is and its bottom line for the portfolio.
  - narrative: 2-4 sentences — what the setup means in plain terms, what the simulation shows (median outcome, tails, dollar impact), and what distinguishes this scenario (e.g. under a volatility regime the median barely moves but the band widens; the adversarial case names which assets drive the loss).

Rules:
- Use ONLY the supplied numbers. Never invent figures.
- Plain professional English a client could read; expand jargon on first use.
- Treat "base" as the no-shock reference the other scenarios are compared against.
- Do NOT make trade recommendations or price targets.
- NEVER use em dashes or en dashes anywhere in the text. Use commas, colons, or periods instead.

Return JSON: {"summary": "...", "explanations": [{"name", "headline", "narrative"}, ...]} with EXACTLY one explanation per scenario, in the SAME ORDER, using the EXACT scenario names given.
"""


class ScenarioExplanation(BaseModel):
    name: str
    headline: str
    narrative: str


class ScenarioExplanations(BaseModel):
    summary: str
    explanations: list[ScenarioExplanation]


def _fmt_money(v: float) -> str:
    sign = "-" if v < 0 else ""
    mag = abs(v)
    if mag >= 1_000_000:
        return f"{sign}${mag / 1_000_000:.2f}M"
    if mag >= 1_000:
        return f"{sign}${mag / 1_000:.0f}K"
    return f"{sign}${mag:,.0f}"


def _last(seq: Optional[list[float]]) -> Optional[float]:
    return seq[-1] if seq else None


def _pct_of(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """(a/b - 1) * 100, or None when either side is unusable."""
    if a is None or b is None or not b:
        return None
    return (a / b - 1.0) * 100.0


def find_base_name(scenarios: list[dict[str, Any]]) -> Optional[str]:
    """The reference scenario: server-added "base" wins, then the UI's neutral
    preset, then any scenario whose knobs are all neutral."""
    names = {s["name"] for s in scenarios}
    if "base" in names:
        return "base"
    if "Base Case" in names:
        return "Base Case"
    for s in scenarios:
        vol = s.get("vol_scale")
        if (
            not s.get("shock_pct")
            and (vol is None or float(vol) == 1.0)
            and not s.get("drift_shift")
        ):
            return s["name"]
    return None


def derive_facts(
    scenarios: list[dict[str, Any]],
    portfolio_value: float,
) -> list[dict[str, Any]]:
    """Reduce each scenario's fan to the numbers the narrative is grounded in.

    Each input item: {name, shock_pct?, vol_scale?, drift_shift?, fan, discovery?}
    where fan = {central, lower_1s?, upper_1s?, lower_2s?, upper_2s?, p5?, p95?}.
    """
    base_name = find_base_name(scenarios)
    base_end: Optional[float] = None
    for s in scenarios:
        if s["name"] == base_name:
            base_end = _last(s["fan"].get("central"))
            break

    facts = []
    for s in scenarios:
        fan = s["fan"]
        central: list[float] = fan.get("central") or []
        start, end = central[0], central[-1]
        is_base = s["name"] == base_name
        # Shock + drift relative to the baseline outcome; the base scenario
        # (and anything without a base to compare to) falls back to its own path.
        vs_base_pct = _pct_of(end, base_end) if (base_end and not is_base) else None
        rel_return_pct = vs_base_pct if vs_base_pct is not None else _pct_of(end, start)
        down_end = _last(fan.get("lower_2s")) or _last(fan.get("p5"))
        up_end = _last(fan.get("upper_2s")) or _last(fan.get("p95"))
        band_pct = (
            (up_end - down_end) / end * 100.0 if (down_end is not None and up_end is not None and end) else None
        )
        facts.append(
            {
                "name": s["name"],
                "is_base": is_base,
                "shock_pct": s.get("shock_pct"),
                "vol_scale": s.get("vol_scale"),
                "drift_shift": s.get("drift_shift"),
                "horizon_days": len(central),
                "start": start,
                "end": end,
                "path_return_pct": _pct_of(end, start),
                "vs_base_pct": vs_base_pct,
                "dollar_impact": (
                    portfolio_value * rel_return_pct / 100.0 if rel_return_pct is not None else None
                ),
                "downside_end": down_end,
                "downside_pct": _pct_of(down_end, end),
                "upside_end": up_end,
                "band_pct": band_pct,
                "worst_point_pct": _pct_of(min(central), start),
                "discovery": s.get("discovery"),
            }
        )
    return facts


def _knob_line(f: dict[str, Any]) -> str:
    if f.get("shock_pct") is None and f.get("vol_scale") is None and f.get("drift_shift") is None:
        return "setup: server-generated (no user knobs)"
    return (
        f"setup: shock {float(f.get('shock_pct') or 0):+.1f}%, "
        f"vol x{float(f.get('vol_scale') or 1.0):.2f}, "
        f"drift {float(f.get('drift_shift') or 0):+.4f}/day"
    )


def _fact_block(f: dict[str, Any]) -> str:
    lines = [f"Scenario \"{f['name']}\"" + (" [BASE reference]" if f["is_base"] else "")]
    lines.append(f"  {_knob_line(f)}")
    lines.append(
        f"  median path: {f['start']:,.2f} -> {f['end']:,.2f} over {f['horizon_days']} days"
        + (f" ({f['path_return_pct']:+.1f}%)" if f["path_return_pct"] is not None else "")
    )
    if f["vs_base_pct"] is not None:
        lines.append(
            f"  vs base end level: {f['vs_base_pct']:+.1f}%"
            + (f", dollar impact {_fmt_money(f['dollar_impact'])}" if f["dollar_impact"] is not None else "")
        )
    elif f["is_base"] and f["dollar_impact"] is not None:
        lines.append(f"  dollar impact of median path: {_fmt_money(f['dollar_impact'])}")
    if f["downside_end"] is not None and f["downside_pct"] is not None:
        lines.append(
            f"  pessimistic tail ends at {f['downside_end']:,.2f} ({f['downside_pct']:+.1f}% vs median end)"
        )
    if f["upside_end"] is not None:
        lines.append(f"  optimistic tail ends at {f['upside_end']:,.2f}")
    if f["band_pct"] is not None:
        lines.append(f"  95% band width at horizon: {f['band_pct']:.1f}% of median end")
    if f["worst_point_pct"] is not None and f["worst_point_pct"] < 0:
        lines.append(f"  lowest point on median path: {f['worst_point_pct']:+.1f}% from start")
    disc = f.get("discovery")
    if isinstance(disc, dict):
        # _discovery values are decimal fractions (adversarial_discovery.py) —
        # scale to percent here; skip anything non-numeric rather than crash.
        shocks = disc.get("shock_pcts")
        if isinstance(shocks, dict):
            parts = []
            for t, p in sorted(shocks.items()):
                try:
                    parts.append(f"{t}: {float(p) * 100:+.1f}%")
                except (TypeError, ValueError):
                    continue
            if parts:
                lines.append(f"  adversarial per-asset shocks: {', '.join(parts)}")
        try:
            cvar = float(disc["cvar"]) if disc.get("cvar") is not None else None
        except (TypeError, ValueError):
            cvar = None
        if cvar is not None:
            lines.append(
                f"  expected tail loss (CVaR) found by adversarial search: {cvar * 100:+.1f}% of portfolio value"
            )
    return "\n".join(lines)


def build_prompt(
    portfolio_name: str,
    portfolio_value: float,
    facts: list[dict[str, Any]],
) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Portfolio: {portfolio_name}\n"
        f"Portfolio value: {_fmt_money(portfolio_value)}\n\n"
        + "\n\n".join(_fact_block(f) for f in facts)
        + "\n\nWrite the explanations now as JSON."
    )


def run(
    *,
    portfolio_name: str,
    portfolio_value: float,
    scenarios: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], LlmResult]:
    """Explain every scenario in one batched structured call.

    Returns (executive summary, explanations aligned to input order,
    derived facts, LlmResult).
    """
    facts = derive_facts(scenarios, portfolio_value)
    prompt = build_prompt(portfolio_name, portfolio_value, facts)
    # Cache key: the simulated outcomes, not just the knobs — so explanations
    # regenerate when market data (and therefore the fans) move.
    scenario_key = [
        {
            "name": f["name"],
            "end": round(float(f["end"]), 4),
            "downside_end": round(float(f["downside_end"]), 4) if f["downside_end"] is not None else None,
        }
        for f in facts
    ]
    result = generate(
        prompt,
        agent_name="scenario_explain",
        schema=ScenarioExplanations,
        cache_key_extra={
            "portfolio_name": portfolio_name,
            "portfolio_value": round(portfolio_value, 2),
            "scenarios": scenario_key,
        },
    )
    try:
        parsed = json.loads(result.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"scenario explainer returned malformed JSON: {exc}")

    # Tolerate the classic wrapper-dropping failure (bare top-level array);
    # anything else non-dict is malformed output.
    if isinstance(parsed, list):
        summary = ""
        raw = parsed
    elif isinstance(parsed, dict):
        summary = str(parsed.get("summary") or "")
        raw = parsed.get("explanations") or []
    else:
        raise ValueError("scenario explainer returned malformed JSON: not an object or array")
    # Align to input order by name. Positional fallback may only claim an entry
    # that isn't already used AND isn't named for another input scenario —
    # never borrow a named entry (misattribution is worse than a gap).
    entries = [e for e in raw if isinstance(e, dict)]
    by_name: dict[str, list[int]] = {}
    for idx, e in enumerate(entries):
        by_name.setdefault(e.get("name"), []).append(idx)
    input_names = {f["name"] for f in facts}
    claimed: set[int] = set()
    aligned = []
    for i, f in enumerate(facts):
        e = None
        idx = next((j for j in by_name.get(f["name"], []) if j not in claimed), None)
        if idx is not None:
            e = entries[idx]
            claimed.add(idx)
        elif i < len(entries) and i not in claimed and entries[i].get("name") not in input_names:
            e = entries[i]
            claimed.add(i)
        if e:
            aligned.append(
                {"name": f["name"], "headline": e.get("headline", ""), "narrative": e.get("narrative", "")}
            )
    if not aligned:
        raise ValueError("scenario explainer returned no explanations")
    return summary, aligned, facts, result
