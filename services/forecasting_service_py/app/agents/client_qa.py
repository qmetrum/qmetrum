"""Client Q&A agent.

Single-turn: advisor asks a question about one portfolio, the agent answers
grounded in the portfolio's holdings, current metrics/regime, and active
alerts (and the latest event for each alert).
"""
from __future__ import annotations

from typing import Any, Optional

from app.agents.llm import generate, LlmResult
from app.agents.disclaimer import with_disclaimer


SYSTEM_PROMPT = """You are an advisor-facing assistant answering a question about ONE client portfolio.

Rules:
- Answer in 2-6 sentences unless the question genuinely needs more depth.
- Ground every claim in the data provided below. If the data does not contain
  what is needed to answer, say so plainly — do not guess.
- Use only the numbers supplied. Do not invent figures, prices, or dates.
- Do NOT make trade recommendations, buy/sell calls, or price targets.
- Be direct. No hedging boilerplate. No repeating of the question.
"""


def _fmt_pct(v: Any, decimals: int = 1) -> str:
    try:
        return f"{float(v) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_num(v: Any, decimals: int = 2) -> str:
    try:
        return f"{float(v):.{decimals}f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_holdings(holdings: list[dict[str, Any]]) -> str:
    if not holdings:
        return "(no holdings)"
    return "\n".join(
        f"- {str(h.get('ticker', '')).upper()} "
        f"(weight {_fmt_pct(h.get('weight'))}"
        + (f", qty {h['quantity']}" if h.get("quantity") is not None else "")
        + ")"
        for h in holdings
    )


def _fmt_metrics(metrics: dict[str, Any]) -> str:
    if not metrics:
        return "(no metrics available)"
    return (
        f"- Sharpe ratio: {_fmt_num(metrics.get('sharpe_ratio'))}\n"
        f"- Sortino ratio: {_fmt_num(metrics.get('sortino_ratio'))}\n"
        f"- Annualized volatility: {_fmt_pct(metrics.get('annualized_volatility'))}\n"
        f"- VaR (95%): {_fmt_pct(metrics.get('var_95'))}\n"
        f"- Max drawdown: {_fmt_pct(metrics.get('max_drawdown'))}"
    )


def _fmt_alerts(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return "(no active alerts on held tickers)"
    lines = []
    for a in alerts:
        latest = a.get("latest_event") or {}
        triggered = ""
        if latest:
            triggered = (
                f", last eval {latest.get('evaluated_at', '')[:10]}: "
                f"{'triggered' if latest.get('triggered') else 'not triggered'}"
            )
        lines.append(
            f"- {a['ticker']} / {a['name']}: {a['alert_type']} "
            f"{a['direction']} {_fmt_num(a['threshold_value'])}{triggered}"
        )
    return "\n".join(lines)


def build_prompt(
    portfolio_name: str,
    holdings: list[dict[str, Any]],
    metrics: dict[str, Any],
    regime: str,
    alerts: list[dict[str, Any]],
    question: str,
) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Portfolio: {portfolio_name}\n"
        f"Current regime: {regime or 'Normal'}\n\n"
        f"Holdings:\n{_fmt_holdings(holdings)}\n\n"
        f"Metrics:\n{_fmt_metrics(metrics)}\n\n"
        f"Active alerts on held tickers:\n{_fmt_alerts(alerts)}\n\n"
        f"Advisor question: {question.strip()}\n\n"
        "Answer now."
    )


def run(
    *,
    portfolio_id: int,
    portfolio_name: str,
    holdings: list[dict[str, Any]],
    metrics: dict[str, Any],
    regime: str,
    alerts: list[dict[str, Any]],
    question: str,
    snapshot_hash: Optional[str] = None,
) -> tuple[str, LlmResult]:
    prompt = build_prompt(portfolio_name, holdings, metrics, regime, alerts, question)
    result = generate(
        prompt,
        agent_name="client_qa",
        cache_key_extra={
            "portfolio_id": portfolio_id,
            "snapshot_hash": snapshot_hash or "",
            "question": question.strip(),
        },
    )
    return with_disclaimer(result.text), result
