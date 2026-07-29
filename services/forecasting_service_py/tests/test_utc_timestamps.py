"""Timestamps served to clients must carry an explicit UTC offset.

The bug this pins down: the service used to persist `datetime.utcnow()`, which is
naive, so the API emitted "2026-07-29T14:54:14.123456" with no timezone
designator. Per the ECMAScript spec a date-time string without an offset is
parsed as LOCAL time, so browsers shifted every timestamp by the viewer's UTC
offset and a freshly triggered alert rendered as "2h ago" on arrival.

NOTE: importing app.main is heavy (TensorFlow + sentence-transformers), so run
this module on its own if you want it fast:  pytest tests/test_utc_timestamps.py
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.main as m
from app.db.database import engine, init_db
from app.db.models import AlertEvent, AlertRule, MarketData, User
from app.utils.timeutil import as_utc, iso_utc, utcnow

USER_ID = 90701

# An ISO-8601 instant that states its zone, either "Z" or "+HH:MM".
HAS_OFFSET = re.compile(r"(Z|[+-]\d{2}:\d{2})$")


@pytest.fixture(scope="module", autouse=True)
def _user():
    init_db()
    with Session(engine) as s:
        if not s.get(User, USER_ID):
            s.add(User(id=USER_ID, email=f"u{USER_ID}@qmetrum.dev", is_active=True))
        s.commit()


@pytest.fixture
def client():
    return TestClient(m.app)


@pytest.fixture
def alert_rule():
    with Session(engine) as s:
        rule = AlertRule(
            user_id=USER_ID, name="utc-timestamp-test", ticker="TSTUTC", alert_type="price_threshold"
        )
        s.add(rule)
        s.commit()
        s.refresh(rule)
        rule_id = rule.id
    yield rule_id
    with Session(engine) as s:
        for ev in s.exec(select(AlertEvent).where(AlertEvent.alert_id == rule_id)).all():
            s.delete(ev)
        rule = s.get(AlertRule, rule_id)
        if rule:
            s.delete(rule)
        s.commit()


def test_utcnow_is_aware():
    assert utcnow().tzinfo is not None


def test_alert_event_timestamp_served_with_offset(client, alert_rule):
    """The reported bug: /alerts/events must not emit a zone-less timestamp."""
    with Session(engine) as s:
        s.add(AlertEvent(alert_id=alert_rule, ticker="TSTUTC", alert_type="price_threshold", triggered=True))
        s.commit()

    resp = client.get(
        "/alerts/events",
        params={"triggered_only": True, "limit": 10},
        headers={"X-User-Id": str(USER_ID)},
    )
    assert resp.status_code == 200
    items = [i for i in resp.json()["items"] if i["ticker"] == "TSTUTC"]
    assert items, "expected the event we just created"
    assert HAS_OFFSET.search(items[0]["evaluated_at"]), (
        f"evaluated_at={items[0]['evaluated_at']!r} has no timezone designator; "
        "browsers will parse it as local time"
    )


def test_event_age_is_not_shifted_by_the_reader_offset(client, alert_rule):
    """A brand-new event must read as ~0 seconds old, not one UTC offset old."""
    with Session(engine) as s:
        s.add(AlertEvent(alert_id=alert_rule, ticker="TSTUTC", alert_type="anomaly", triggered=True))
        s.commit()

    resp = client.get(
        "/alerts/events",
        params={"triggered_only": True, "limit": 10},
        headers={"X-User-Id": str(USER_ID)},
    )
    served = [i for i in resp.json()["items"] if i["alert_type"] == "anomaly"][0]["evaluated_at"]
    age = abs((utcnow() - datetime.fromisoformat(served)).total_seconds())
    assert age < 60, f"fresh event appeared {age:.0f}s old — timestamp is offset-shifted"


def test_legacy_naive_row_reads_back_aware(alert_rule):
    """Rows written before this change are naive on disk and must still work.

    They are the reason UtcDateTime attaches UTC on read rather than requiring a
    backfill: comparing a legacy row against utcnow() must not raise
    "can't compare offset-naive and offset-aware datetimes".
    """
    with engine.connect() as c:
        c.execute(
            sa.text(
                "INSERT INTO alertevent (alert_id, ticker, alert_type, triggered, payload, evaluated_at) "
                "VALUES (:a, 'TSTUTC', 'legacy', 0, '{}', '2026-07-27 07:59:56.275666')"
            ),
            {"a": alert_rule},
        )
        c.commit()

    with Session(engine) as s:
        row = s.exec(select(AlertEvent).where(AlertEvent.alert_type == "legacy")).first()
        assert row is not None, "legacy row was not inserted"
        assert row.evaluated_at.tzinfo is not None, "legacy naive row did not come back aware"
        # The comparison that used to raise TypeError:
        assert (utcnow() - row.evaluated_at).total_seconds() > 0


def test_storage_format_unchanged(alert_rule):
    """UtcDateTime must not alter what lands on disk — no migration, no backfill."""
    with Session(engine) as s:
        s.add(AlertEvent(alert_id=alert_rule, ticker="TSTUTC", alert_type="storage", triggered=False))
        s.commit()

    with engine.connect() as c:
        raw = c.execute(
            sa.text("SELECT evaluated_at FROM alertevent WHERE alert_type = 'storage'")
        ).scalar()
    # Naive UTC, exactly as before: no offset suffix persisted.
    assert not HAS_OFFSET.search(str(raw)), f"storage format changed: {raw!r}"


def test_calendar_date_columns_stay_naive():
    """`date` is a trading day, not an instant; it feeds pandas and stays naive.

    If this starts failing, someone converted a calendar column to UtcDateTime and
    market-data comparisons against strptime()-built values will raise.
    """
    assert MarketData.__table__.c.date.type.__class__.__name__ == "DateTime"


@pytest.mark.parametrize(
    "value,expected_offset",
    [
        (datetime(2026, 7, 29, 14, 0), True),                      # naive -> assumed UTC
        (datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc), True),  # already aware
        (None, False),
    ],
)
def test_iso_utc_always_states_its_zone(value, expected_offset):
    out = iso_utc(value)
    if not expected_offset:
        assert out is None
    else:
        assert HAS_OFFSET.search(out), out


def test_as_utc_is_idempotent():
    naive = datetime(2026, 7, 29, 14, 0)
    assert as_utc(as_utc(naive)) == as_utc(naive)
    assert as_utc(naive).utcoffset().total_seconds() == 0
