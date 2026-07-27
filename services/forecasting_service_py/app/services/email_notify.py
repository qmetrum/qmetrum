"""Transactional email via AWS SES (used for alert notifications).

Deliberately best-effort and self-contained: a send failure or missing config
must NEVER break the caller (alert evaluation persists regardless). Enabled
only when EMAIL_ALERTS_ENABLED is set AND a verified sender is configured.

Config (env / SSM):
  EMAIL_ALERTS_ENABLED   "true" to turn delivery on (default off)
  ALERT_EMAIL_SENDER     verified SES "From" address, e.g. alerts@qmetrum.io
  AWS_REGION             SES region (falls back to eu-north-1)
  APP_BASE_URL           link back to the app in the email body (optional)

IAM: the ECS task role needs ses:SendEmail (see deploy notes).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _flag(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def is_email_configured() -> bool:
    """True only when delivery is enabled AND a sender address is set."""
    return _flag("EMAIL_ALERTS_ENABLED") and bool(os.getenv("ALERT_EMAIL_SENDER"))


def send_email(*, to_address: str, subject: str, body_text: str,
               body_html: Optional[str] = None) -> bool:
    """Send one email via SES. Returns True on success, False otherwise.
    Never raises: callers treat email as fire-and-forget."""
    if not is_email_configured():
        return False
    if not to_address or "@" not in to_address:
        logger.warning("Alert email skipped: invalid recipient %r", to_address)
        return False

    sender = os.getenv("ALERT_EMAIL_SENDER")
    region = os.getenv("AWS_REGION") or os.getenv("COGNITO_REGION") or "eu-north-1"
    try:
        import boto3  # lazy: keeps boto3 optional for non-AWS/local runs
    except ImportError:
        logger.warning("Alert email skipped: boto3 not installed")
        return False

    body = {"Text": {"Data": body_text, "Charset": "UTF-8"}}
    if body_html:
        body["Html"] = {"Data": body_html, "Charset": "UTF-8"}

    try:
        client = boto3.client("ses", region_name=region)
        resp = client.send_email(
            Source=sender,
            Destination={"ToAddresses": [to_address]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": body,
            },
        )
        logger.info("Alert email sent to %s (MessageId=%s)", to_address,
                    resp.get("MessageId"))
        return True
    except Exception as e:  # boto ClientError, endpoint errors, throttling, etc.
        logger.warning("Alert email to %s failed: %s", to_address, e)
        return False


def _fmt_num(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "n/a"
    return f"{f:,.2f}"


def build_alert_email(*, rule_name: str, result: dict) -> tuple[str, str, str]:
    """Compose (subject, text, html) from a triggered alert's evaluation result.
    Uses only the real evaluation fields; no invented content."""
    ticker = result.get("ticker", "?")
    atype = str(result.get("alert_type", "alert")).replace("_", " ")
    direction = result.get("direction")
    value = result.get("value")
    threshold = result.get("threshold")

    subject = f"Qsight alert: {ticker} {rule_name}".strip()

    facts = [f"Alert: {rule_name}", f"Ticker: {ticker}", f"Type: {atype}"]
    if direction is not None and threshold is not None:
        facts.append(f"Condition: {direction} {_fmt_num(threshold)}")
    if value is not None:
        facts.append(f"Observed value: {_fmt_num(value)}")
    if result.get("reason"):
        facts.append(f"Note: {result['reason']}")

    app_url = os.getenv("APP_BASE_URL", "").rstrip("/")
    link = f"\n\nView in Qsight: {app_url}/alerts" if app_url else ""
    disclaimer = (
        "\n\nThis is an automated alert generated from your configured rule and "
        "market data. It is informational only and not investment advice."
    )
    text = "\n".join(facts) + link + disclaimer

    rows = "".join(f"<tr><td style='padding:2px 10px 2px 0;color:#5A6270'>{k}</td>"
                   f"<td style='padding:2px 0;font-weight:600'>{v}</td></tr>"
                   for k, v in (f.split(": ", 1) for f in facts if ": " in f))
    link_html = (f"<p><a href='{app_url}/alerts'>View in Qsight</a></p>" if app_url else "")
    html = (
        f"<div style='font-family:Helvetica,Arial,sans-serif;font-size:14px;color:#1A1A2E'>"
        f"<h2 style='color:#0B1D3A;margin:0 0 8px'>Qsight alert triggered</h2>"
        f"<table style='border-collapse:collapse'>{rows}</table>{link_html}"
        f"<p style='font-size:11px;color:#8B95A2;margin-top:16px'>"
        f"This is an automated alert generated from your configured rule and market "
        f"data. It is informational only and not investment advice.</p></div>"
    )
    return subject, text, html
