"""Portfolio commentary agent.

Given a portfolio's holdings, performance metrics, risk metrics, and current
regime, produce a short narrative paragraph (100-150 words) suitable for an
advisor-facing report. Purely descriptive — no recommendations.
"""
from __future__ import annotations

from typing import Any, Optional

from app.agents.llm import generate, LlmResult
from app.agents.disclaimer import with_disclaimer


SYSTEM_PROMPT = """You are writing a concise paragraph for a financial advisor's portfolio report.

Audience: an advisor reviewing a client portfolio.
Style: plain English, precise, neutral. No hype, no sales language.
Length: 100-150 words. Output one paragraph only — no headers, no bullet lists.
Content: describe the portfolio's current composition, its recent performance
and risk profile, and any notable tension or context (e.g. concentration,
regime, drawdown). Do NOT make recommendations, trade ideas, or price targets.
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


def _format_holdings(holdings: list[dict[str, Any]]) -> str:
    if not holdings:
        return "(no holdings)"
    lines = []
    for h in holdings:
        ticker = str(h.get("ticker", "")).upper()
        weight = h.get("weight")
        weight_str = _fmt_pct(weight, 1) if weight is not None else "n/a"
        lines.append(f"- {ticker} {weight_str}")
    return "\n".join(lines)


def build_prompt(
    portfolio_name: str,
    holdings: list[dict[str, Any]],
    metrics: dict[str, Any],
    regime: str,
    horizon_days: int,
) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Portfolio: {portfolio_name}\n"
        f"Current regime: {regime}\n"
        f"Forecast horizon: {horizon_days} days\n\n"
        f"Holdings:\n{_format_holdings(holdings)}\n\n"
        f"Metrics:\n"
        f"- Sharpe ratio: {_fmt_num(metrics.get('sharpe_ratio'))}\n"
        f"- Sortino ratio: {_fmt_num(metrics.get('sortino_ratio'))}\n"
        f"- Annualized volatility: {_fmt_pct(metrics.get('annualized_volatility'))}\n"
        f"- VaR (95%): {_fmt_pct(metrics.get('var_95'))}\n"
        f"- Max drawdown: {_fmt_pct(metrics.get('max_drawdown'))}\n\n"
        "Write the commentary paragraph now."
    )


def run(
    *,
    portfolio_id: int,
    portfolio_name: str,
    holdings: list[dict[str, Any]],
    metrics: dict[str, Any],
    regime: str,
    horizon_days: int,
    snapshot_hash: Optional[str] = None,
) -> tuple[str, LlmResult]:
    """Generate commentary. Returns (text_with_disclaimer, raw LlmResult)."""
    prompt = build_prompt(portfolio_name, holdings, metrics, regime, horizon_days)
    result = generate(
        prompt,
        agent_name="portfolio_commentary",
        cache_key_extra={
            "portfolio_id": portfolio_id,
            "snapshot_hash": snapshot_hash or "",
        },
    )
    return with_disclaimer(result.text), result
