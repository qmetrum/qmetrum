"""Alert explainer agent.

Input: an AlertRule, the latest AlertEvent (if any), and the list of portfolios
in which the user holds the alert's ticker.

Output: a 2-3 sentence plain-English explanation of why this alert matters
right now — contextualized to the user's actual exposure.
"""
from __future__ import annotations

from typing import Any, Optional

from app.agents.llm import generate, LlmResult
from app.agents.disclaimer import with_disclaimer


SYSTEM_PROMPT = """You explain why a market alert matters right now, to an advisor reading a portfolio dashboard.

Style:
- 2-3 sentences, plain English.
- State the factual situation, then its significance for the client's exposure.
- Do NOT give trade recommendations, targets, or prescriptive advice.
- If holdings are concentrated, mention concentration. If holdings are small or
  absent, say the direct impact is limited.
- Do not invent figures. Use only the numbers provided.
"""


def _fmt_pct(v: Any) -> str:
    try:
        return f"{float(v) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_num(v: Any) -> str:
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "n/a"


def build_prompt(
    rule_name: str,
    ticker: str,
    alert_type: str,
    direction: str,
    threshold: float,
    latest_event: Optional[dict[str, Any]],
    exposures: list[dict[str, Any]],
) -> str:
    event_line = "No triggered events yet — this alert has not fired."
    if latest_event:
        ts = latest_event.get("evaluated_at") or ""
        triggered = "triggered" if latest_event.get("triggered") else "not triggered"
        payload = latest_event.get("payload") or {}
        payload_bits = []
        for key in ("observed_value", "current_price", "latest_price", "value"):
            if key in payload:
                payload_bits.append(f"{key}={payload[key]}")
                break
        payload_line = (", ".join(payload_bits)) if payload_bits else ""
        event_line = (
            f"Most recent evaluation ({ts}): {triggered}."
            f"{(' ' + payload_line) if payload_line else ''}"
        )

    if exposures:
        exposure_lines = "\n".join(
            f"- {e['portfolio_name']}: weight {_fmt_pct(e.get('weight'))}"
            for e in exposures
        )
    else:
        exposure_lines = "(ticker is not currently held in any of this user's portfolios)"

    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Alert: {rule_name}\n"
        f"Ticker: {ticker}\n"
        f"Rule: {alert_type}, direction {direction}, threshold {_fmt_num(threshold)}\n"
        f"{event_line}\n\n"
        f"User's exposure to {ticker}:\n{exposure_lines}\n\n"
        "Write the explanation now, 2-3 sentences, no bullets."
    )


def run(
    *,
    alert_id: int,
    rule_name: str,
    ticker: str,
    alert_type: str,
    direction: str,
    threshold: float,
    latest_event: Optional[dict[str, Any]],
    exposures: list[dict[str, Any]],
) -> tuple[str, LlmResult]:
    prompt = build_prompt(
        rule_name, ticker, alert_type, direction, threshold, latest_event, exposures
    )
    cache_key_extra = {
        "alert_id": alert_id,
        "event_id": (latest_event or {}).get("id"),
    }
    result = generate(prompt, agent_name="alert_explainer", cache_key_extra=cache_key_extra)
    return with_disclaimer(result.text), result
