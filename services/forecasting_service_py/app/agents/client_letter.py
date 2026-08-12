"""Client-communication engine — draft a quarterly client letter.

The productized version of the concierge letter: assemble a portfolio's REAL
quarterly numbers server-side (performance + the Regime Watch diversification
measure), then have a tightly-gated LLM narrate them into a warm, client-ready
draft. The model only NARRATES supplied numbers; it never computes or invents.

Honesty charter (this is client-facing, so it is strict):
- Use ONLY the supplied numbers. No predicted returns, price targets, or
  probabilities. No fabricated benchmarks or dollar values.
- Frame everything as realized MEASUREMENT, not a forecast.
- The output is always a DRAFT for the advisor to review and edit; the advisor
  is the fiduciary. Never phrase it as advice or a recommendation.
- No em or en dashes.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import pandas as pd
from pydantic import BaseModel
from sqlmodel import select

from app.agents.llm import generate, LlmResult
from app.db.models import PortfolioRegimeSnapshot
from app.services.market_store import get_price_series_cached

SYSTEM_PROMPT = """You are helping a financial advisor draft a warm, plain-English QUARTERLY CLIENT LETTER about one portfolio. You are given ONLY real, already-computed numbers. Write a letter a client could read, in the advisor's voice.

Write JSON with these fields:
- greeting: one short warm opening line (address the client as [Client First Name], a literal placeholder).
- performance_paragraph: 2-4 sentences on how the quarter and the past year went, using the supplied returns, volatility, and drawdown. If an all-stock (S&P 500) comparison is supplied, use it to explain the smoother-ride tradeoff plainly.
- diversification_paragraph: 2-4 sentences ONLY IF regime facts are supplied, else "". Explain, as a MEASUREMENT, what the realized stock-vs-bond correlation is versus the portfolio's own baseline, and what a higher-than-baseline reading does and does not mean (it has not necessarily cost money; it matters most in a sharp sell-off). Never predict.
- closing_paragraph: 2-3 sentences: nothing needs client action today, the advisor is watching, invite them to reply.

Rules (non-negotiable):
- Use ONLY the supplied numbers. Never invent a figure, benchmark, event, or dollar value.
- Never state or imply a FORECAST, a predicted return, a price target, a probability, an accuracy, or a track record.
- Frame correlation and returns as REALIZED measurement of what already happened.
- Warm, human, professional. Expand any jargon. This is a DRAFT the advisor will review and edit before sending.
- NEVER use em dashes or en dashes. Use commas, colons, or periods.

Return JSON: {"greeting": "...", "performance_paragraph": "...", "diversification_paragraph": "...", "closing_paragraph": "..."}
"""

DISCLAIMER = (
    "Figures are computed from end-of-day prices, before fees and taxes, and assume the "
    "portfolio's holdings are held throughout the period. Volatility is the annualized standard "
    "deviation of daily returns; the deepest drop is the largest peak-to-trough decline in the "
    "period. Correlation figures are realized over a trailing window, not forecasts. Past "
    "performance does not guarantee future results. This letter is a draft for advisor review; "
    "it is not investment advice or a recommendation."
)


class ClientLetterOut(BaseModel):
    greeting: str
    performance_paragraph: str
    diversification_paragraph: str
    closing_paragraph: str


def _pf_metrics(rows: list[dict]) -> Optional[dict]:
    if not rows or len(rows) < 30:
        return None
    s = pd.Series(
        {pd.to_datetime(r["date"]): float(r["price"]) for r in rows}
    ).sort_index()
    r = s.pct_change().dropna()
    if len(r) < 30:
        return None
    eq = (1.0 + r).cumprod()
    dd = (eq / eq.cummax() - 1.0).min()
    return {
        "quarter_return_pct": round(float((1.0 + r.tail(63)).prod() - 1.0) * 100, 1),
        "year_return_pct": round(float((1.0 + r).prod() - 1.0) * 100, 1),
        "ann_vol_pct": round(float(r.std()) * (252 ** 0.5) * 100, 1),
        "max_drawdown_pct": round(float(dd) * 100, 1),
        "n_obs": int(len(r)),
    }


def _weighted_series(holdings: list[dict], session) -> list[dict]:
    """Weighted portfolio price index from holdings, as [{date, price}]."""
    frames = {}
    total = sum(float(h.get("weight", 0.0) or 0.0) for h in holdings) or 1.0
    for h in holdings:
        tk = (h.get("ticker") or "").upper()
        rows = get_price_series_cached(tk, period="1y", session=session) or []
        if rows:
            frames[tk] = pd.Series(
                {pd.to_datetime(x["date"]): float(x["price"]) for x in rows}
            )
    if not frames:
        return []
    df = pd.DataFrame(frames).sort_index().ffill().dropna()
    if len(df) < 2:
        return []
    rets = df.pct_change().dropna()
    w = {h["ticker"].upper(): float(h.get("weight", 0.0) or 0.0) / total for h in holdings}
    blend = sum(rets[c] * w.get(c, 0.0) for c in rets.columns)
    idx = (1.0 + blend).cumprod() * 100.0
    return [{"date": d.strftime("%Y-%m-%d"), "price": float(v)} for d, v in idx.items()]


def gather_facts(portfolio_id: int, holdings: list[dict], session) -> dict[str, Any]:
    """Assemble the REAL numbers the letter will narrate. All reproducible."""
    facts: dict[str, Any] = {"portfolio_id": portfolio_id}
    pf_series = _weighted_series(holdings, session)
    facts["portfolio"] = _pf_metrics(pf_series)

    spy = get_price_series_cached("SPY", period="1y", session=session) or []
    spy_m = _pf_metrics(spy)
    if spy_m:
        facts["all_stock"] = {
            "quarter_return_pct": spy_m["quarter_return_pct"],
            "ann_vol_pct": spy_m["ann_vol_pct"],
        }

    row = session.exec(
        select(PortfolioRegimeSnapshot)
        .where(PortfolioRegimeSnapshot.portfolio_id == portfolio_id)
        .order_by(PortfolioRegimeSnapshot.updated_at.desc())
    ).first()
    if row is not None and row.status == "ok":
        facts["regime"] = {
            "short_corr": row.short_corr,
            "baseline_corr": row.baseline_corr,
            "delta": row.delta,
            "as_of": row.as_of.strftime("%Y-%m-%d") if row.as_of else None,
        }
    return facts


def build_prompt(facts: dict[str, Any]) -> str:
    p = facts.get("portfolio") or {}
    lines = ["Portfolio quarterly numbers (all realized, already computed):"]
    if p:
        lines += [
            f"  quarter return: {p['quarter_return_pct']}%",
            f"  trailing-year return: {p['year_return_pct']}%",
            f"  annualized volatility: {p['ann_vol_pct']}%",
            f"  deepest drop in the year: {p['max_drawdown_pct']}%",
        ]
    a = facts.get("all_stock")
    if a:
        lines += [
            f"  all-stock (S&P 500) quarter return: {a['quarter_return_pct']}%",
            f"  all-stock annualized volatility: {a['ann_vol_pct']}%",
        ]
    reg = facts.get("regime")
    if reg:
        lines += [
            "Diversification (Regime Watch) facts:",
            f"  realized equity-vs-bond correlation: {reg['short_corr']}",
            f"  portfolio's own long-run baseline correlation: {reg['baseline_corr']}",
            f"  change vs baseline: {reg['delta']}",
            f"  as of: {reg['as_of']}",
        ]
    else:
        lines.append("No diversification facts supplied: leave diversification_paragraph empty.")
    return f"{SYSTEM_PROMPT}\n\n" + "\n".join(lines) + "\n\nWrite the letter now as JSON."


def run(*, portfolio_id: int, holdings: list[dict], session) -> tuple[dict[str, Any], LlmResult]:
    """Draft the client letter. Returns (letter, LlmResult). `letter` carries the
    narrated parts, the source facts, and the fixed disclaimer."""
    facts = gather_facts(portfolio_id, holdings, session)
    if not facts.get("portfolio"):
        raise ValueError("Not enough price history to draft a letter for this portfolio.")
    prompt = build_prompt(facts)
    result = generate(
        prompt,
        agent_name="client_letter",
        schema=ClientLetterOut,
        cache_key_extra={"portfolio_id": portfolio_id, "facts": facts},
    )
    try:
        parsed = json.loads(result.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"client_letter returned malformed JSON: {exc}")
    if not isinstance(parsed, dict):
        raise ValueError("client_letter returned malformed JSON: not an object")

    letter = {
        "portfolio_id": portfolio_id,
        "greeting": str(parsed.get("greeting", "")),
        "performance_paragraph": str(parsed.get("performance_paragraph", "")),
        "diversification_paragraph": str(parsed.get("diversification_paragraph", "")),
        "closing_paragraph": str(parsed.get("closing_paragraph", "")),
        "facts": facts,
        "disclaimer": DISCLAIMER,
        "is_draft": True,
    }
    return letter, result
