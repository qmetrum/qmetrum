"""Alert feedback loop + per-user notification preferences.

NOTE: importing app.main is heavy (TensorFlow + sentence-transformers), so run
this module on its own if you want it fast:  pytest tests/test_alert_feedback_prefs.py
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.main as m
from app.db.database import engine, init_db
from app.db.models import (AlertEvent, AlertFeedback, AlertRule, Portfolio,
                           Position, User, UserAlertPreference)

KEY = "fb-test-key"
USER_ID = 90501
OTHER_ID = 90502


@pytest.fixture(scope="module", autouse=True)
def _users():
    init_db()
    with Session(engine) as s:
        for uid in (USER_ID, OTHER_ID):
            if not s.get(User, uid):
                s.add(User(id=uid, email=f"u{uid}@qmetrum.dev", is_active=True))
        s.commit()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(m, "QPULSE_INGEST_KEY", KEY)
    return TestClient(m.app)


@pytest.fixture(autouse=True)
def _clean():
    """Remove every row these tests create.

    The rules matter as much as the feedback: a leaked anomaly rule on a shared
    ticker makes /qpulse/ingest fan out to more rules than the ingest tests
    expect, so leaking here fails a different module."""
    yield
    with Session(engine) as s:
        for uid in (USER_ID, OTHER_ID):
            for f in s.exec(select(AlertFeedback).where(AlertFeedback.user_id == uid)).all():
                s.delete(f)
            for p in s.exec(select(UserAlertPreference)
                            .where(UserAlertPreference.user_id == uid)).all():
                s.delete(p)
            for r in s.exec(select(AlertRule).where(AlertRule.user_id == uid)).all():
                for e in s.exec(select(AlertEvent)
                                .where(AlertEvent.alert_id == r.id)).all():
                    s.delete(e)
                s.delete(r)
        s.commit()


def _make_event(user_id=USER_ID, ticker="BTC-USD", kind="robust_z", severity="WARNING"):
    with Session(engine) as s:
        rule = AlertRule(user_id=user_id, name=f"{ticker} r", ticker=ticker,
                         alert_type="anomaly", is_active=True,
                         extra_config={"detector": "qpulse"})
        s.add(rule)
        s.commit()
        s.refresh(rule)
        ev = AlertEvent(alert_id=rule.id, ticker=ticker, alert_type="anomaly",
                        triggered=True, evaluated_at=datetime.utcnow(),
                        payload={"detector_source": "qpulse", "reference_gate": None,
                                 "gated_on_reference_catalog": False,
                                 "qpulse": {"kind": kind, "score": 7.0,
                                            "severity": severity}})
        s.add(ev)
        s.commit()
        s.refresh(ev)
        return rule.id, ev.id


def _hdr(uid=USER_ID):
    return {"X-User-Id": str(uid)}


# --- preferences ----------------------------------------------------------

def test_preferences_default_on_first_read(client):
    p = client.get("/alerts/preferences", headers=_hdr()).json()
    assert p["email_enabled"] is True
    assert p["min_severity"] == "ALERT"
    assert p["muted_tickers"] == [] and p["muted_kinds"] == []


def test_preferences_update_and_validate(client):
    r = client.put("/alerts/preferences", headers=_hdr(),
                   json={"min_severity": "ANOMALY", "quiet_hours_start": 22,
                         "quiet_hours_end": 7, "muted_tickers": ["  eth-usd "]})
    assert r.status_code == 200
    p = r.json()
    assert p["min_severity"] == "ANOMALY"
    assert p["muted_tickers"] == ["ETH-USD"]      # canonicalised

    assert client.put("/alerts/preferences", headers=_hdr(),
                      json={"min_severity": "LOUD"}).status_code == 422
    assert client.put("/alerts/preferences", headers=_hdr(),
                      json={"quiet_hours_start": 99}).status_code == 422


def test_partial_update_leaves_other_fields_alone(client):
    client.put("/alerts/preferences", headers=_hdr(), json={"min_severity": "ANOMALY"})
    client.put("/alerts/preferences", headers=_hdr(), json={"email_enabled": False})
    p = client.get("/alerts/preferences", headers=_hdr()).json()
    assert p["min_severity"] == "ANOMALY" and p["email_enabled"] is False


# --- the gating logic itself ---------------------------------------------

@pytest.mark.parametrize("sev,floor,expected", [
    ("ANOMALY", "ALERT", True), ("INFO", "ALERT", False),
    ("ALERT", "ALERT", True), ("WARNING", "ANOMALY", False),
    ("WEIRD", "ALERT", True),          # unknown severity is not silently dropped
])
def test_severity_floor(sev, floor, expected):
    prefs = UserAlertPreference(user_id=1, min_severity=floor)
    assert m._should_email(prefs, "BTC-USD", "robust_z", sev,
                           datetime(2026, 7, 28, 12)) is expected


def test_muted_ticker_and_kind_block_email():
    prefs = UserAlertPreference(user_id=1, muted_tickers=["BTC-USD"])
    assert not m._should_email(prefs, "btc-usd", "robust_z", "ANOMALY",
                               datetime(2026, 7, 28, 12))
    prefs2 = UserAlertPreference(user_id=1, muted_kinds=["robust_z"])
    assert not m._should_email(prefs2, "ETH-USD", "ROBUST_Z", "ANOMALY",
                               datetime(2026, 7, 28, 12))


def test_quiet_hours_including_wrap_around_midnight():
    prefs = UserAlertPreference(user_id=1, quiet_hours_start=22, quiet_hours_end=7)
    at = lambda h: datetime(2026, 7, 28, h)  # noqa: E731
    assert not m._should_email(prefs, "X", "k", "ANOMALY", at(23))   # inside
    assert not m._should_email(prefs, "X", "k", "ANOMALY", at(3))    # inside, wrapped
    assert m._should_email(prefs, "X", "k", "ANOMALY", at(12))       # outside

    # start == end disables the window entirely
    off = UserAlertPreference(user_id=1, quiet_hours_start=0, quiet_hours_end=0)
    assert m._should_email(off, "X", "k", "ANOMALY", at(3))


def test_quiet_hours_use_the_user_timezone():
    prefs = UserAlertPreference(user_id=1, quiet_hours_start=22, quiet_hours_end=7,
                                quiet_hours_tz_offset_min=120)  # UTC+2
    # 21:00 UTC is 23:00 local -> quiet
    assert not m._should_email(prefs, "X", "k", "ANOMALY", datetime(2026, 7, 28, 21))


# --- feedback -------------------------------------------------------------

def test_feedback_recorded_and_updatable(client):
    _, ev = _make_event()
    assert client.post(f"/alerts/events/{ev}/feedback", headers=_hdr(),
                       json={"rating": "useful"}).status_code == 200
    # Re-rating replaces rather than duplicating.
    client.post(f"/alerts/events/{ev}/feedback", headers=_hdr(),
                json={"rating": "not_useful", "reason": "noise"})
    with Session(engine) as s:
        rows = s.exec(select(AlertFeedback).where(AlertFeedback.alert_event_id == ev)).all()
        assert len(rows) == 1 and rows[0].rating == "not_useful"
        assert rows[0].ticker == "BTC-USD" and rows[0].alert_kind == "robust_z"


def test_invalid_rating_rejected(client):
    _, ev = _make_event()
    assert client.post(f"/alerts/events/{ev}/feedback", headers=_hdr(),
                       json={"rating": "meh"}).status_code == 422


def test_cannot_rate_another_users_event(client):
    _, ev = _make_event(user_id=USER_ID)
    r = client.post(f"/alerts/events/{ev}/feedback", headers=_hdr(OTHER_ID),
                    json={"rating": "useful"})
    assert r.status_code == 404, "must not confirm another user's event exists"


def test_auto_mute_after_repeated_not_useful(client):
    client.put("/alerts/preferences", headers=_hdr(), json={"auto_mute_after": 3})
    last = None
    for _ in range(3):
        _, ev = _make_event(kind="spread_widen")
        last = client.post(f"/alerts/events/{ev}/feedback", headers=_hdr(),
                           json={"rating": "not_useful"}).json()
    assert last["auto_muted_kind"] == "spread_widen"
    prefs = client.get("/alerts/preferences", headers=_hdr()).json()
    assert "spread_widen" in prefs["muted_kinds"]


def test_a_useful_rating_breaks_the_auto_mute_streak(client):
    client.put("/alerts/preferences", headers=_hdr(), json={"auto_mute_after": 3})
    for rating in ("not_useful", "not_useful", "useful"):
        _, ev = _make_event(kind="cusum")
        client.post(f"/alerts/events/{ev}/feedback", headers=_hdr(),
                    json={"rating": rating})
    prefs = client.get("/alerts/preferences", headers=_hdr()).json()
    assert "cusum" not in prefs["muted_kinds"]


def test_auto_mute_can_be_disabled(client):
    client.put("/alerts/preferences", headers=_hdr(), json={"auto_mute_after": 0})
    for _ in range(4):
        _, ev = _make_event(kind="burst")
        r = client.post(f"/alerts/events/{ev}/feedback", headers=_hdr(),
                        json={"rating": "not_useful"}).json()
        assert r["auto_muted_kind"] is None


def test_feedback_summary(client):
    _, e1 = _make_event(kind="robust_z")
    _, e2 = _make_event(kind="robust_z")
    client.post(f"/alerts/events/{e1}/feedback", headers=_hdr(), json={"rating": "useful"})
    client.post(f"/alerts/events/{e2}/feedback", headers=_hdr(), json={"rating": "not_useful"})
    s = client.get("/alerts/feedback/summary", headers=_hdr()).json()
    assert s["total"] == 2 and s["useful"] == 1 and s["not_useful"] == 1
    assert s["by_kind"]["robust_z"] == {"useful": 1, "not_useful": 1}


# --- preferences actually gate ingest email ------------------------------

def test_muted_kind_suppresses_email_but_still_stores_the_event(client, monkeypatch):
    sent = []
    monkeypatch.setattr(m, "is_email_configured", lambda: True)
    monkeypatch.setattr(m, "send_email", lambda **kw: sent.append(kw) or True)
    client.put("/alerts/preferences", headers=_hdr(), json={"muted_kinds": ["robust_z"]})

    with Session(engine) as s:
        rule = AlertRule(user_id=USER_ID, name="btc", ticker="BTC-USD",
                         alert_type="anomaly", is_active=True,
                         extra_config={"detector": "qpulse"})
        s.add(rule)
        s.commit()
        s.refresh(rule)
        rid = rule.id
    try:
        r = client.post("/qpulse/ingest", headers={"X-Qpulse-Key": KEY}, json={
            "source": "qpulse", "feed": "crypto", "asset_class": "crypto",
            "alerts": [{"symbol": "BTC/USD", "ts_ns": 1, "kind": "robust_z",
                        "price": 1.0, "score": 9.0, "severity": "ANOMALY"}]})
        assert r.json()["events_persisted"] == 1, "event must still be stored"
        assert sent == [], "muted kind was emailed anyway"
    finally:
        with Session(engine) as s:
            for e in s.exec(select(AlertEvent).where(AlertEvent.alert_id == rid)).all():
                s.delete(e)
            obj = s.get(AlertRule, rid)
            if obj:
                s.delete(obj)
            s.commit()


# --- bulk monitoring ------------------------------------------------------

def test_monitor_holdings_creates_rules_and_is_idempotent(client):
    with Session(engine) as s:
        pf = Portfolio(user_id=USER_ID, name="Test PF")
        s.add(pf)
        s.commit()
        s.refresh(pf)
        for t in ("AAPL", "MSFT"):
            s.add(Position(portfolio_id=pf.id, ticker=t, weight=0.5))
        s.commit()
        pid = pf.id
    try:
        first = client.post("/alerts/monitor-holdings", headers=_hdr(),
                            json={"portfolio_id": pid}).json()
        assert set(first["created"]) == {"AAPL", "MSFT"}

        second = client.post("/alerts/monitor-holdings", headers=_hdr(),
                             json={"portfolio_id": pid}).json()
        assert second["created"] == [], "duplicate rules would double every alert"
        assert set(second["already_monitored"]) == {"AAPL", "MSFT"}

        listed = client.get("/qpulse/watchlist", params={"feed": "iex"},
                            headers={"X-Qpulse-Key": KEY}).json()["symbols"]
        assert {"AAPL", "MSFT"} <= set(listed), "holdings did not reach the watchlist"
    finally:
        with Session(engine) as s:
            for r in s.exec(select(AlertRule).where(AlertRule.user_id == USER_ID)).all():
                s.delete(r)
            for p in s.exec(select(Position).where(Position.portfolio_id == pid)).all():
                s.delete(p)
            obj = s.get(Portfolio, pid)
            if obj:
                s.delete(obj)
            s.commit()


def test_monitor_holdings_rejects_another_users_portfolio(client):
    with Session(engine) as s:
        pf = Portfolio(user_id=OTHER_ID, name="Theirs")
        s.add(pf)
        s.commit()
        s.refresh(pf)
        pid = pf.id
    try:
        assert client.post("/alerts/monitor-holdings", headers=_hdr(),
                           json={"portfolio_id": pid}).status_code == 404
    finally:
        with Session(engine) as s:
            obj = s.get(Portfolio, pid)
            if obj:
                s.delete(obj)
            s.commit()
