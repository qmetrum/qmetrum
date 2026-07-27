"""Tests for SES alert email delivery (boto3 mocked; no real send)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import email_notify as en


# ------------------------------------------------------------- config gating

def test_is_email_configured(monkeypatch):
    monkeypatch.delenv("EMAIL_ALERTS_ENABLED", raising=False)
    monkeypatch.delenv("ALERT_EMAIL_SENDER", raising=False)
    assert en.is_email_configured() is False
    monkeypatch.setenv("EMAIL_ALERTS_ENABLED", "true")
    assert en.is_email_configured() is False           # sender still missing
    monkeypatch.setenv("ALERT_EMAIL_SENDER", "alerts@qmetrum.io")
    assert en.is_email_configured() is True
    monkeypatch.setenv("EMAIL_ALERTS_ENABLED", "false")
    assert en.is_email_configured() is False           # explicitly disabled


def test_send_email_noop_when_unconfigured(monkeypatch):
    monkeypatch.delenv("EMAIL_ALERTS_ENABLED", raising=False)
    # Must not even try to import/construct a client.
    assert en.send_email(to_address="a@b.com", subject="s", body_text="t") is False


# ------------------------------------------------------------------- sending

@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setenv("EMAIL_ALERTS_ENABLED", "true")
    monkeypatch.setenv("ALERT_EMAIL_SENDER", "alerts@qmetrum.io")
    monkeypatch.setenv("AWS_REGION", "eu-north-1")


def test_send_email_calls_ses(configured):
    fake_client = MagicMock()
    fake_client.send_email.return_value = {"MessageId": "abc123"}
    fake_boto3 = MagicMock()
    fake_boto3.client.return_value = fake_client
    with patch.dict("sys.modules", {"boto3": fake_boto3}):
        ok = en.send_email(to_address="user@x.com", subject="Sub",
                           body_text="Body", body_html="<p>Body</p>")
    assert ok is True
    fake_boto3.client.assert_called_once_with("ses", region_name="eu-north-1")
    kwargs = fake_client.send_email.call_args.kwargs
    assert kwargs["Source"] == "alerts@qmetrum.io"
    assert kwargs["Destination"]["ToAddresses"] == ["user@x.com"]
    assert kwargs["Message"]["Body"]["Html"]["Data"] == "<p>Body</p>"


def test_send_email_never_raises_on_ses_error(configured):
    fake_client = MagicMock()
    fake_client.send_email.side_effect = RuntimeError("SES throttled")
    fake_boto3 = MagicMock()
    fake_boto3.client.return_value = fake_client
    with patch.dict("sys.modules", {"boto3": fake_boto3}):
        assert en.send_email(to_address="user@x.com", subject="s", body_text="t") is False


def test_send_email_rejects_bad_recipient(configured):
    assert en.send_email(to_address="not-an-email", subject="s", body_text="t") is False


# ------------------------------------------------------------- email content

def test_build_alert_email_is_grounded():
    result = {"ticker": "AAPL", "alert_type": "price_threshold", "direction": "above",
              "value": 231.5, "threshold": 220.0}
    subject, text, html = en.build_alert_email(rule_name="AAPL breakout", result=result)
    assert "AAPL" in subject and "AAPL breakout" in subject
    assert "above 220.00" in text and "231.50" in text
    assert "not investment advice" in text
    assert "AAPL" in html and "231.50" in html
