"""Integration: _evaluate_alerts_internal emails the rule owner on a fresh
trigger and stays silent under cooldown. boto3/SES never touched (send_email
is mocked). Importing app.main is heavy; run standalone if needed."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlmodel import Session, delete

import app.main as m
from app.db.database import engine, init_db
from app.db.models import AlertEvent, AlertRule, User

USER_ID = 91
EMAIL = "alertuser@qmetrum.dev"


@pytest.fixture()
def rule_id():
    init_db()
    with Session(engine) as s:
        if not s.get(User, USER_ID):
            s.add(User(id=USER_ID, email=EMAIL, is_active=True))
            s.commit()
        rule = AlertRule(user_id=USER_ID, name="AAPL breakout", ticker="AAPL",
                         alert_type="price_threshold", direction="above",
                         threshold_value=100.0, is_active=True)
        s.add(rule)
        s.commit()
        s.refresh(rule)
        # Clean any prior events for a deterministic cooldown test.
        s.exec(delete(AlertEvent).where(AlertEvent.alert_id == rule.id))
        s.commit()
        return rule.id


def _triggered(rule):
    return {"alert_id": rule.id, "ticker": rule.ticker, "alert_type": "price_threshold",
            "triggered": True, "value": 231.5, "threshold": 100.0, "direction": "above"}


def test_fresh_trigger_sends_email(rule_id):
    sent = []
    with patch.object(m, "_evaluate_alert_rule", side_effect=_triggered), \
         patch.object(m, "is_email_configured", return_value=True), \
         patch.object(m, "send_email", side_effect=lambda **kw: sent.append(kw) or True):
        summary = m._evaluate_alerts_internal(alert_ids=[rule_id], owner_user_id=USER_ID)
    assert summary["triggered_count"] == 1
    assert len(sent) == 1
    assert sent[0]["to_address"] == EMAIL
    assert "AAPL" in sent[0]["subject"]


def test_cooldown_suppresses_second_email(rule_id):
    sent = []
    with patch.object(m, "_evaluate_alert_rule", side_effect=_triggered), \
         patch.object(m, "is_email_configured", return_value=True), \
         patch.object(m, "send_email", side_effect=lambda **kw: sent.append(kw) or True):
        m._evaluate_alerts_internal(alert_ids=[rule_id], owner_user_id=USER_ID)
        # Immediate re-run: within cooldown window -> persisted event suppressed,
        # so no second email.
        m._evaluate_alerts_internal(alert_ids=[rule_id], owner_user_id=USER_ID)
    assert len(sent) == 1


def test_no_email_when_disabled(rule_id):
    sent = []
    with patch.object(m, "_evaluate_alert_rule", side_effect=_triggered), \
         patch.object(m, "is_email_configured", return_value=False), \
         patch.object(m, "send_email", side_effect=lambda **kw: sent.append(kw) or True):
        m._evaluate_alerts_internal(alert_ids=[rule_id], owner_user_id=USER_ID)
    assert sent == []


def test_email_failure_does_not_break_evaluation(rule_id):
    with patch.object(m, "_evaluate_alert_rule", side_effect=_triggered), \
         patch.object(m, "is_email_configured", return_value=True), \
         patch.object(m, "send_email", side_effect=RuntimeError("SES down")):
        summary = m._evaluate_alerts_internal(alert_ids=[rule_id], owner_user_id=USER_ID)
    # Evaluation still succeeds and the event is still persisted.
    assert summary["triggered_count"] == 1
    with Session(engine) as s:
        events = s.exec(
            __import__("sqlmodel").select(AlertEvent).where(AlertEvent.alert_id == rule_id)
        ).all()
    assert len(events) == 1
