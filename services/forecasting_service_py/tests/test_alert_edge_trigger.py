"""Alert dedup is EDGE-triggered: fire once per threshold crossing, re-arm only
after it clears, and the scheduler respects US market hours (no weekend firing)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session, delete, select

import app.main as m
from app.db.database import engine, init_db
from app.db.models import AlertEvent, AlertRule, User

USER_ID = 92


@pytest.fixture()
def rule_id():
    init_db()
    with Session(engine) as s:
        if not s.get(User, USER_ID):
            s.add(User(id=USER_ID, email="edge@qmetrum.dev", is_active=True))
            s.commit()
        r = AlertRule(user_id=USER_ID, name="edge", ticker="AAPL", alert_type="price_threshold",
                      direction="above", threshold_value=100.0, is_active=True)
        s.add(r)
        s.commit()
        s.refresh(r)
        s.exec(delete(AlertEvent).where(AlertEvent.alert_id == r.id))
        s.commit()
        return r.id


def _res(triggered):
    return lambda rule: {"alert_id": rule.id, "ticker": rule.ticker, "alert_type": "price_threshold",
                         "triggered": triggered, "value": 231.5, "threshold": 100.0, "direction": "above"}


def _count(rid):
    with Session(engine) as s:
        return len(s.exec(select(AlertEvent).where(AlertEvent.alert_id == rid)).all())


def test_fires_once_then_rearms_after_clear(rule_id):
    with patch.object(m, "is_email_configured", return_value=False):
        # rising edge -> exactly one triggered event
        with patch.object(m, "_evaluate_alert_rule", side_effect=_res(True)):
            m._evaluate_alerts_internal(alert_ids=[rule_id], owner_user_id=USER_ID)
        assert _count(rule_id) == 1

        # still over threshold -> NO new event (this was the "all the time" bug)
        with patch.object(m, "_evaluate_alert_rule", side_effect=_res(True)):
            summary = m._evaluate_alerts_internal(alert_ids=[rule_id], owner_user_id=USER_ID)
        assert _count(rule_id) == 1
        assert summary["items"][0]["already_active"] is True

        # condition clears -> falling-edge event recorded (re-arms)
        with patch.object(m, "_evaluate_alert_rule", side_effect=_res(False)):
            m._evaluate_alerts_internal(alert_ids=[rule_id], owner_user_id=USER_ID)
        assert _count(rule_id) == 2

        # re-crosses -> fires again (fresh rising edge)
        with patch.object(m, "_evaluate_alert_rule", side_effect=_res(True)):
            m._evaluate_alerts_internal(alert_ids=[rule_id], owner_user_id=USER_ID)
        assert _count(rule_id) == 3


def test_market_hours_gate():
    assert m._market_is_open(datetime(2026, 8, 1, 16, 0, tzinfo=timezone.utc)) is False   # Saturday
    assert m._market_is_open(datetime(2026, 8, 2, 16, 0, tzinfo=timezone.utc)) is False   # Sunday
    assert m._market_is_open(datetime(2026, 8, 5, 16, 0, tzinfo=timezone.utc)) is True    # Wed 12:00 ET
    assert m._market_is_open(datetime(2026, 8, 5, 21, 30, tzinfo=timezone.utc)) is False  # Wed 17:30 ET (closed)
    assert m._market_is_open(datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)) is False   # Wed 08:00 ET (pre-open)
