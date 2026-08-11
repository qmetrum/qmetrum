"""QLens brief — a decision-support "second opinion" on a single holding.

Mirrors the design of the standalone qmetrum/qlens repo (honesty-gated bull vs
bear -> Buy/Hold/Sell), but native to the backend: it grounds the reasoning in
Qmetrum's OWN market data (prices + fundamentals) and reuses the shared LLM
client (Gemini, cached + logged via the agentrun table). One batched structured
call keeps it cheap and on-demand.

Honesty charter (same as the QLens repo): every claim cites a supplied fact;
nothing is invented; NO return, price target, probability, accuracy, or track
record is ever stated or implied. The stance is a reasoned opinion, not advice.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import pandas as pd
from pydantic import BaseModel

from app.agents.llm import generate, LlmResult
from app.services.market_store import get_fundamentals_cached, get_price_series_cached

STANCES = ("Buy", "Hold", "Sell")
CONVICTIONS = ("low", "medium", "high")

SYSTEM_PROMPT = """You are a buy-side research desk producing a decision-support brief on ONE stock for a portfolio manager. You run an internal bull-vs-bear debate, then a portfolio manager weighs both sides and issues a stance.

You are given a numbered list of FACTS (each with a source). Do the following:
- bull: 3-5 points making the strongest evidence-based case TO OWN the stock. Cite the fact number [n] after each point.
- bear: 3-5 points making the strongest case to be CAUTIOUS or AVOID. Cite [n] after each point.
- stance: Buy, Hold, or Sell, on balance.
- conviction: low, medium, or high, reflecting how strongly the evidence AGREES. This is NOT a probability of being right.
- key_risks: 1-3 things that most threaten the stance.
- what_would_change_my_mind: 1-3 concrete observations that would flip it.
- rationale: 2-4 sentences weighing both sides, citing [n].

Rules (non-negotiable):
- Use ONLY the supplied facts. Never invent a price, number, or event.
- Cite the fact number [n] after every factual claim.
- NEVER state or imply a return, a price target, a probability, an accuracy figure, or a track record.
- This is a reasoned opinion, NOT investment advice and NOT a forecast.
- NEVER use em dashes or en dashes. Use commas, colons, or periods.

Return JSON: {"bull": [...], "bear": [...], "stance": "...", "conviction": "...", "key_risks": [...], "what_would_change_my_mind": [...], "rationale": "..."}
"""


class QLensBriefOut(BaseModel):
    bull: list[str]
    bear: list[str]
    stance: str
    conviction: str
    key_risks: list[str]
    what_would_change_my_mind: list[str]
    rationale: str


def gather_facts(ticker: str, extra_context: Optional[str] = None) -> list[dict[str, Any]]:
    """Sourced facts from Qmetrum's OWN data: cached prices + fundamentals.
    Each fact is {idx, source, statement}. Degrades honestly if data is thin."""
    facts: list[dict[str, Any]] = []
    i = 0

    def add(source: str, statement: str) -> None:
        nonlocal i
        facts.append({"idx": i, "source": source, "statement": statement})
        i += 1

    try:
        rows = get_price_series_cached(ticker, period="1y") or []
        if len(rows) >= 2:
            s = pd.Series([float(r["price"]) for r in rows])
            last = float(s.iloc[-1])
            add("qmetrum/price", f"Last close {last:.2f}.")
            for label, n in (("1-month", 21), ("3-month", 63), ("6-month", 126)):
                if len(s) > n:
                    chg = (last / float(s.iloc[-n - 1]) - 1) * 100
                    add("qmetrum/price", f"{label} price change {chg:+.1f}%.")
            hi, lo = float(s.max()), float(s.min())
            if hi > lo:
                pos = (last - lo) / (hi - lo) * 100
                add("qmetrum/price", f"Trailing-year range {lo:.2f} to {hi:.2f}; last is at {pos:.0f}% of it.")
            vol = float(s.pct_change().dropna().std()) * (252 ** 0.5) * 100
            add("qmetrum/price", f"Annualized volatility of daily returns is {vol:.0f}%.")
    except Exception:
        add("system", "Price history was unavailable; reasoning from remaining facts only.")

    try:
        fund = get_fundamentals_cached(ticker) or {}
        profile = fund.get("profile", {}) if isinstance(fund, dict) else {}
        val = fund.get("valuation", {}) if isinstance(fund, dict) else {}
        tech = fund.get("technicals", {}) if isinstance(fund, dict) else {}
        for label, v in (
            ("sector", profile.get("sector")),
            ("industry", profile.get("industry")),
        ):
            if v:
                add("qmetrum/fundamentals", f"{label.capitalize()}: {v}.")
        for label, v in (
            ("trailing P/E", val.get("pe_ratio")),
            ("forward P/E", val.get("forward_pe")),
            ("EV/EBITDA", val.get("ev_to_ebitda")),
            ("market cap", val.get("market_cap")),
            ("beta", tech.get("beta")),
        ):
            if v is not None:
                add("qmetrum/fundamentals", f"{label}: {v}.")
    except Exception:
        pass

    if extra_context:
        for line in [ln.strip() for ln in extra_context.splitlines() if ln.strip()]:
            add("user-context", line)

    return facts


def _facts_block(facts: list[dict[str, Any]]) -> str:
    return "\n".join(f"[{f['idx']}] ({f['source']}) {f['statement']}" for f in facts)


def build_prompt(ticker: str, facts: list[dict[str, Any]]) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Stock: {ticker}\n\n"
        f"FACTS:\n{_facts_block(facts)}\n\n"
        "Write the brief now as JSON."
    )


DISCLAIMER = (
    "QLens is a reasoned opinion from a simulated bull/bear debate: not investment advice, "
    "not a recommendation, and not a forecast. No performance or accuracy is claimed."
)


def run(ticker: str, extra_context: Optional[str] = None) -> tuple[dict[str, Any], LlmResult]:
    """Produce a decision-support brief for one ticker. Returns (brief, LlmResult)."""
    ticker = ticker.strip().upper()
    facts = gather_facts(ticker, extra_context)
    prompt = build_prompt(ticker, facts)
    # Cache key includes the facts so the brief regenerates when data moves.
    result = generate(
        prompt,
        agent_name="qlens_brief",
        schema=QLensBriefOut,
        cache_key_extra={"ticker": ticker, "facts": [f["statement"] for f in facts]},
    )
    try:
        parsed = json.loads(result.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"qlens_brief returned malformed JSON: {exc}")
    if not isinstance(parsed, dict):
        raise ValueError("qlens_brief returned malformed JSON: not an object")

    stance = parsed.get("stance", "Hold")
    if stance not in STANCES:
        stance = "Hold"
    conviction = parsed.get("conviction", "low")
    if conviction not in CONVICTIONS:
        conviction = "low"

    brief = {
        "ticker": ticker,
        "stance": stance,
        "conviction": conviction,
        "bull": [str(x) for x in (parsed.get("bull") or [])],
        "bear": [str(x) for x in (parsed.get("bear") or [])],
        "key_risks": [str(x) for x in (parsed.get("key_risks") or [])],
        "what_would_change_my_mind": [str(x) for x in (parsed.get("what_would_change_my_mind") or [])],
        "rationale": str(parsed.get("rationale", "")),
        "facts": facts,
        "disclaimer": DISCLAIMER,
    }
    return brief, result
