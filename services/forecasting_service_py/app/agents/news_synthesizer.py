"""News synthesizer agent.

Input: a list of news items (title, publisher, timestamp) for a given ticker.
Output: structured summary, overall sentiment, and up to 5 highlights pointing
back to specific items by index.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field

from app.agents.llm import generate, LlmResult


class NewsHighlight(BaseModel):
    index: int = Field(description="0-based index into the input items array")
    note: str = Field(description="One sentence on why this item matters")


class NewsSynthesis(BaseModel):
    summary: str = Field(description="2-3 sentence overall summary")
    sentiment: str = Field(description="One of: bullish, bearish, mixed, neutral")
    highlights: list[NewsHighlight] = Field(
        default_factory=list,
        description="Up to 5 most significant items, ranked most → least important",
    )


SYSTEM_PROMPT = """You summarize a batch of news items about a single ticker.

Instructions:
- Write a 2-3 sentence neutral summary of the dominant themes.
- Classify overall sentiment as exactly one of: bullish, bearish, mixed, neutral.
- Pick up to 5 most significant items and return their 0-based indices with a one-line note explaining why each matters.
- Do not make investment recommendations.
- If items are sparse or unrelated, say so honestly.
"""


def _format_items(items: list[dict[str, Any]]) -> str:
    lines = []
    for i, it in enumerate(items):
        title = str(it.get("title", "")).strip()
        publisher = str(it.get("publisher", "")).strip() or "unknown"
        ts = str(it.get("timestamp", "")).strip()
        ts_short = ts.split("T", 1)[0] if ts else ""
        lines.append(f"[{i}] ({publisher}, {ts_short}) {title}")
    return "\n".join(lines)


def _news_hash(items: list[dict[str, Any]]) -> str:
    normalized = [
        {"title": str(it.get("title", "")), "ts": str(it.get("timestamp", ""))}
        for it in items
    ]
    blob = json.dumps(normalized, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def run(ticker: str, items: list[dict[str, Any]]) -> tuple[NewsSynthesis, LlmResult]:
    ticker = ticker.upper()
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Ticker: {ticker}\n"
        f"News items (indexed):\n{_format_items(items)}\n"
    )
    result = generate(
        prompt,
        agent_name="news_synthesizer",
        schema=NewsSynthesis,
        cache_key_extra={"ticker": ticker, "news_hash": _news_hash(items)},
    )
    data = json.loads(result.text)
    raw_highlights = data.get("highlights") or []
    normalized_highlights: list[NewsHighlight] = []
    for h in raw_highlights[:5]:
        try:
            idx = int(h.get("index", -1))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(items):
            normalized_highlights.append(NewsHighlight(index=idx, note=str(h.get("note", "")).strip()))
    sentiment = str(data.get("sentiment", "neutral")).strip().lower()
    if sentiment not in {"bullish", "bearish", "mixed", "neutral"}:
        sentiment = "neutral"
    synthesis = NewsSynthesis(
        summary=str(data.get("summary", "")).strip(),
        sentiment=sentiment,
        highlights=normalized_highlights,
    )
    return synthesis, result
