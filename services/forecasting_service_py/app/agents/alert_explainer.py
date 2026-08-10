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
- A detector score is a statistical deviation, not a prediction and not a
  measure of how reliable the signal is. Never imply an accuracy, hit rate, or
  track record; none is provided to you.
- If the input says a detector is unvalidated, or that the data came from a
  synthetic or replayed feed, say so plainly in the explanation.
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


_KIND_MEANING = {
    "robust_z": "return deviated sharply from its recent baseline",
    "cusum": "a sustained cumulative drift accumulated in one direction",
    "regime_shift": "the recent return distribution stopped matching the reference window",
    "spread_widen": "the quoted bid-ask spread widened well beyond its baseline",
    "obi_extreme": "order-book depth became extremely one-sided",
    "quote_rate_spike": "quote traffic spiked far above its normal rate",
    "burst": "several different detectors fired together in a short window",
    "dependence_shift": "cross-asset correlation structure broke from its reference period",
    "volume_spike": "traded volume spiked far above its baseline",
    "microprice_drift": "the size-weighted microprice diverged from the last trade price",
}

# Feeds that are not live market data.
_NON_LIVE_FEEDS = {"synthetic": "a synthetic (simulated) feed",
                   "csv": "a replayed historical file"}


def _qpulse_event_line(ts: str, payload: dict[str, Any]) -> str:
    """Describe a Qpulse detector event without overstating what it means.

    The gating status and feed provenance are stated explicitly so the model
    cannot present an unvalidated detector, or a simulated feed, as though it
    were a track-recorded signal on live data."""
    q = payload.get("qpulse") or {}
    kind = str(q.get("kind", "unknown"))
    bits = [f"Detector event ({ts}): {kind}"]
    meaning = _KIND_MEANING.get(kind)
    if meaning:
        bits.append(f"— {meaning}")
    if q.get("score") is not None:
        bits.append(f"; score {_fmt_num(q.get('score'))} (standard deviations from baseline)")
    if q.get("severity"):
        bits.append(f"; severity {q['severity']}")
    if q.get("price") is not None:
        bits.append(f"; price at detection {_fmt_num(q.get('price'))}")

    line = "".join(bits) + "."
    if q.get("narrative"):
        line += f" Detector note: {q['narrative']}"

    feed = str(q.get("feed") or "").lower()
    if feed in _NON_LIVE_FEEDS:
        line += (f" IMPORTANT: this came from {_NON_LIVE_FEEDS[feed]}, "
                 f"not live market data — say so.")

    if payload.get("gated_on_reference_catalog") and payload.get("reference_gate"):
        line += (f" This detector kind was scored offline against {payload['reference_gate']} "
                 f"(historical daily bars); its accuracy on live data is unmeasured.")
    else:
        line += (" This detector kind has NOT been scored against any labeled "
                 "catalog for this asset — treat it as experimental and say so.")
    return line


def _regime_event_line(ts: str, payload: dict[str, Any]) -> str:
    """Describe a Regime Watch measurement honestly: realized equity-vs-bond
    correlation now vs the portfolio's own baseline. A MEASUREMENT, never a
    prediction — no accuracy, probability, or track record is implied."""
    val = _fmt_num(payload.get("value"))
    base = _fmt_num(payload.get("baseline"))
    delta = _fmt_num(payload.get("delta"))
    as_of = payload.get("as_of")
    triggered = bool(payload.get("triggered"))
    verb = "has risen above" if triggered else "is at or below"
    line = (
        f"Regime measurement ({ts}): the portfolio's realized equity-vs-bond return "
        f"correlation is {val} over the short window, versus its OWN long-run baseline "
        f"of {base} (change {delta}); it {verb} that baseline"
    )
    line += f", as of {as_of}." if as_of else "."
    line += (
        " This is a realized MEASUREMENT of how the equity and bond sleeves have "
        "co-moved — it is NOT a forecast, and it implies no probability of a drawdown, "
        "no accuracy, and no track record."
    )
    return line


def build_prompt(
    rule_name: str,
    ticker: str,
    alert_type: str,
    direction: str,
    threshold: float,
    latest_event: Optional[dict[str, Any]],
    exposures: list[dict[str, Any]],
) -> str:
    payload = (latest_event or {}).get("payload") or {}
    detector = str(payload.get("detector_source", "")).lower()

    event_line = "No triggered events yet — this alert has not fired."
    if latest_event:
        ts = latest_event.get("evaluated_at") or ""
        triggered = "triggered" if latest_event.get("triggered") else "not triggered"
        if detector == "qpulse":
            event_line = _qpulse_event_line(ts, payload)
        elif detector == "regime_watch":
            event_line = _regime_event_line(ts, payload)
        else:
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

    # Regime Watch is a whole-portfolio diversification measure, not a single
    # ticker, and has no fixed price threshold — frame it that way (no fabricated
    # ticker exposure, no fabricated "threshold 0.00").
    if detector == "regime_watch":
        rule_line = (
            "Rule: diversification regime watch — measures the realized equity-vs-bond "
            "correlation on the portfolio's real holdings against the portfolio's OWN "
            "long-run baseline; fires when the short-window correlation rises materially "
            "above that baseline (no fixed price threshold)"
        )
        subject = ("Subject: this portfolio's equity/bond diversification "
                   "(a whole-book measure, not a single ticker).")
        return (
            f"{SYSTEM_PROMPT}\n\n"
            f"Alert: {rule_name}\n"
            f"{subject}\n"
            f"{rule_line}\n"
            f"{event_line}\n\n"
            "Write the explanation now, 2-3 sentences, no bullets."
        )

    if exposures:
        exposure_lines = "\n".join(
            f"- {e['portfolio_name']}: weight {_fmt_pct(e.get('weight'))}"
            for e in exposures
        )
    else:
        exposure_lines = "(ticker is not currently held in any of this user's portfolios)"

    # A Qpulse rule has no direction/threshold — it is fed by an external
    # streaming detector, so quoting "direction above, threshold 0.00" would be
    # a fabricated condition.
    is_qpulse = detector == "qpulse"
    rule_line = (
        "Rule: streaming anomaly detection (Qpulse); no fixed threshold — the "
        "detector fires on statistical deviation from a rolling baseline"
        if is_qpulse else
        f"Rule: {alert_type}, direction {direction}, threshold {_fmt_num(threshold)}"
    )

    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Alert: {rule_name}\n"
        f"Ticker: {ticker}\n"
        f"{rule_line}\n"
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
