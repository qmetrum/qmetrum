"""VaR-95 backtest explainer.

Input: a multi-method VaR backtest comparison (the result produced by
var_backtest_runner.run_portfolio_var_backtest_comparison and cached in
RiskSimulationCache). Output: a structured, plain-English read for a PM —
is the portfolio's VaR trustworthy, what the coverage tests mean, which
method to trust, and what to watch. Numbers-first; explains, never recommends
a trade (that line belongs to a future "propose the move" agent).
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from app.agents.llm import generate, LlmResult


SYSTEM_PROMPT = """You are a buy-side risk analyst explaining a VaR-95 backtest to a portfolio manager.

You are given a backtest comparison of several VaR methods on ONE portfolio. Explain, in plain professional English for a quant-literate PM:
- Whether the portfolio's VaR is trustworthy (does a method pass coverage at the stated confidence?).
- What the coverage tests mean: Kupiec POF (is the breach FREQUENCY right — too many breaches = anti-conservative, too few = over-conservative); Christoffersen conditional coverage (are breaches INDEPENDENT or do they CLUSTER); the Basel traffic light (green/yellow/red regulatory zone).
- Which method is most trustworthy and why (use the recommended method if one is given).
- If an MPS-fan method FAILS while a higher physical-dimension (d) one PASSES, explain that finer return binning corrects anti-conservative tails.

Rules:
- Use ONLY the supplied numbers. Never invent figures.
- Numbers-first and concise. No fluff.
- Do NOT make trade recommendations or price targets — explain the RISK MODEL only.

Return JSON with: headline (one-line verdict), assessment (2-4 sentences), method_notes (one short note per method, referencing its breach rate / test result), watch (caveats to watch — e.g. anti-conservative tails, short window, drift vs constant weights, no passing method).
"""


class MethodNote(BaseModel):
    method: str
    note: str


class VarBacktestExplanation(BaseModel):
    headline: str
    assessment: str
    method_notes: list[MethodNote]
    watch: list[str]


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _method_line(m: dict[str, Any]) -> str:
    if m.get("status") != "ok":
        return f"- {m.get('label', m.get('key'))}: skipped ({m.get('reason', 'n/a')})"
    return (
        f"- {m.get('label')}: breach rate {_pct(m.get('breach_rate'))} "
        f"(target {_pct(m.get('expected_breach_rate'))}), "
        f"Kupiec p={m.get('kupiec', {}).get('p_value', 0):.3f} "
        f"({'reject' if m.get('kupiec', {}).get('reject') else 'pass'}), "
        f"Christoffersen p={m.get('christoffersen_cc', {}).get('p_value', 0):.3f} "
        f"({'reject' if m.get('christoffersen_cc', {}).get('reject') else 'pass'}), "
        f"Basel {m.get('basel_zone')}, "
        f"{'PASSES' if m.get('model_passes') else 'FAILS'} coverage"
    )


def build_prompt(portfolio_name: str, compare: dict[str, Any]) -> str:
    methods = compare.get("methods", [])
    rec = compare.get("recommended")
    rec_line = (
        f"Recommended method: {rec['label']} ({rec.get('why', '')})"
        if rec else "Recommended method: none passed coverage"
    )
    window = compare.get("data_window", {}) or {}
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Portfolio: {portfolio_name}\n"
        f"Confidence: {int(float(compare.get('confidence', 0.95)) * 100)}%  ·  "
        f"horizon: {compare.get('horizon_days', 1)}-day  ·  "
        f"observations: {compare.get('n_observations', 0)}  ·  "
        f"composition basis: {compare.get('weight_mode', 'constant')}  ·  "
        f"window: {window.get('start', '?')} → {window.get('end', '?')}\n"
        f"Methods:\n" + "\n".join(_method_line(m) for m in methods) + "\n"
        f"{rec_line}\n\n"
        "Write the explanation now as JSON."
    )


def run(*, portfolio_name: str, compare: dict[str, Any]) -> tuple[dict[str, Any], LlmResult]:
    prompt = build_prompt(portfolio_name, compare)
    # Cache key: the verdicts that would change the explanation.
    method_key = [
        {
            "key": m.get("key"),
            "passes": m.get("model_passes"),
            "breach_rate": round(float(m.get("breach_rate") or 0), 4),
            "basel": m.get("basel_zone"),
            "status": m.get("status"),
        }
        for m in compare.get("methods", [])
    ]
    result = generate(
        prompt,
        agent_name="var_backtest_explain",
        schema=VarBacktestExplanation,
        cache_key_extra={
            "portfolio_name": portfolio_name,
            "recommended": (compare.get("recommended") or {}).get("key"),
            "weight_mode": compare.get("weight_mode"),
            "n_observations": compare.get("n_observations"),
            "methods": method_key,
        },
    )
    try:
        parsed = json.loads(result.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"explainer returned malformed JSON: {exc}")
    return parsed, result
