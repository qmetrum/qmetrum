from __future__ import annotations

from typing import List

from .schemas import Fact

# Baked into every agent prompt: the honesty gate.
_HONESTY = (
    "Rules: cite the supporting fact number [n] after every claim. Use ONLY the facts "
    "listed; do not invent prices, data, or events. Never state or imply a return, a price "
    "target, a probability, an accuracy, or a track record. Be concise and concrete."
)


def _facts_block(facts: List[Fact]) -> str:
    return "\n".join(f"[{f.idx}] ({f.source}) {f.statement}" for f in facts)


def bull_prompt(ticker: str, facts: List[Fact]) -> str:
    return f"""You are the BULL analyst for {ticker}. Build the strongest evidence-based case TO OWN it.
{_HONESTY}

FACTS:
{_facts_block(facts)}

Return JSON only: {{"points": ["claim ... [n]", ...]}}  (3-5 points, each citing a fact number)."""


def bear_prompt(ticker: str, facts: List[Fact]) -> str:
    return f"""You are the BEAR analyst for {ticker}. Build the strongest evidence-based case to be CAUTIOUS or to AVOID it.
{_HONESTY}

FACTS:
{_facts_block(facts)}

Return JSON only: {{"points": ["claim ... [n]", ...]}}  (3-5 points, each citing a fact number)."""


def judge_prompt(ticker: str, facts: List[Fact], bull_points: List[str], bear_points: List[str]) -> str:
    bull = "\n".join(f"- {p}" for p in bull_points) or "- (none)"
    bear = "\n".join(f"- {p}" for p in bear_points) or "- (none)"
    return f"""You are the PORTFOLIO MANAGER. Weigh the bull and bear cases for {ticker} and issue a stance.
{_HONESTY}
This is a reasoned opinion, NOT advice and NOT a forecast. Conviction is qualitative
(low/medium/high) reflecting how strongly the evidence agrees — it is NOT a probability of being right.

FACTS:
{_facts_block(facts)}

BULL CASE:
{bull}

BEAR CASE:
{bear}

Return JSON only:
{{"stance": "Buy|Hold|Sell",
  "conviction": "low|medium|high",
  "key_risks": ["...", ...],
  "what_would_change_my_mind": ["...", ...],
  "rationale": "2-4 sentences weighing both sides, citing [n]."}}"""
