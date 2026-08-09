from __future__ import annotations

import datetime as _dt
import json
import re
from typing import Callable, List, Optional

from .data import gather_facts
from .llm import GeminiLLM
from .prompts import bear_prompt, bull_prompt, judge_prompt
from .schemas import CONVICTIONS, STANCES, Fact, QLensVerdict

DISCLAIMER = (
    "QLens is a reasoned opinion from a simulated analyst debate - not investment advice, "
    "not a recommendation, and not a forecast. No performance or accuracy is claimed. "
    "Do your own due diligence."
)


def _parse_json(text: str) -> dict:
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def run_lens(
    ticker: str,
    llm: Optional[object] = None,
    extra_context: Optional[str] = None,
    facts: Optional[List[Fact]] = None,
) -> QLensVerdict:
    """Run the bull -> bear -> judge debate and return an honesty-gated verdict.

    Pass `llm` (anything with a .generate(prompt)->str method) to inject a fake in
    tests; defaults to Gemini. Pass `facts` to skip live data gathering."""
    ticker = ticker.strip().upper()
    gen: Callable[[str], str] = (llm.generate if llm is not None else GeminiLLM().generate)

    if facts is None:
        facts = gather_facts(ticker, extra_context)

    bull = _parse_json(gen(bull_prompt(ticker, facts))).get("points", []) or []
    bear = _parse_json(gen(bear_prompt(ticker, facts))).get("points", []) or []
    verdict = _parse_json(gen(judge_prompt(ticker, facts, bull, bear)))

    stance = verdict.get("stance", "Hold")
    if stance not in STANCES:
        stance = "Hold"
    conviction = verdict.get("conviction", "low")
    if conviction not in CONVICTIONS:
        conviction = "low"

    return QLensVerdict(
        ticker=ticker,
        as_of=_dt.date.today().isoformat(),
        stance=stance,
        conviction=conviction,
        bull=[str(p) for p in bull],
        bear=[str(p) for p in bear],
        key_risks=[str(x) for x in verdict.get("key_risks", []) or []],
        what_would_change_my_mind=[str(x) for x in verdict.get("what_would_change_my_mind", []) or []],
        rationale=str(verdict.get("rationale", "")),
        facts=[f.__dict__ for f in facts],
        disclaimer=DISCLAIMER,
    )
