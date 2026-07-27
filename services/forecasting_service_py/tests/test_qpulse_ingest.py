"""Tests for POST /qpulse/ingest — the external Qpulse anomaly-detector webhook.

NOTE: importing app.main is heavy (TensorFlow + sentence-transformers load on
import), so this module is slower than the pure-logic tests. Run on its own:
    pytest tests/test_qpulse_ingest.py
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.main as m
from app.db.database import engine, init_db
from app.db.models import AlertEvent, AlertRule, User

KEY = "test-key-do-not-use-in-prod"
USER_ID = 90201
OTHER_USER_ID = 90202


@pytest.fixture(scope="module", autouse=True)
def _users():
    init_db()
    with Session(engine) as s:
        for uid in (USER_ID, OTHER_USER_ID):
            if not s.get(User, uid):
                s.add(User(id=uid, email=f"u{uid}@qmetrum.dev", is_active=True))
        s.commit()


@pytest.fixture
def client(monkeypatch):
    # Set the key on the module, not the environment: main.py reads it at import.
    monkeypatch.setattr(m, "QPULSE_INGEST_KEY", KEY)
    # no context-manager -> skip lifespan/startup workers (the alert scheduler)
    return TestClient(m.app)


@pytest.fixture
def rule():
    """An active anomaly rule on BTC-USD owned by USER_ID, cleaned up after."""
    with Session(engine) as s:
        r = AlertRule(
            user_id=USER_ID, name="btc anomaly", ticker="BTC-USD",
            alert_type="anomaly", is_active=True,
            extra_config={"detector": "qpulse", "cooldown_seconds": 900},
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        rid = r.id
    yield rid
    with Session(engine) as s:
        for ev in s.exec(select(AlertEvent).where(AlertEvent.alert_id == rid)).all():
            s.delete(ev)
        obj = s.get(AlertRule, rid)
        if obj:
            s.delete(obj)
        s.commit()


def _batch(symbol="BTC/USD", kind="robust_z", asset_class="crypto"):
    return {
        "source": "qpulse",
        "feed": "crypto",
        "asset_class": asset_class,
        "alerts": [{
            "symbol": symbol, "ts_ns": 1700000000000000000, "kind": kind,
            "price": 42000.5, "score": 7.2, "severity": "high",
            "narrative": "BTC-USD moved 7.2 sigma",
            "details": {"z": 7.2},
        }],
    }


def test_503_when_key_unconfigured(monkeypatch):
    monkeypatch.setattr(m, "QPULSE_INGEST_KEY", "")
    c = TestClient(m.app)
    r = c.post("/qpulse/ingest", json=_batch(), headers={"X-Qpulse-Key": "anything"})
    assert r.status_code == 503


def test_401_on_wrong_key(client):
    r = client.post("/qpulse/ingest", json=_batch(), headers={"X-Qpulse-Key": "wrong"})
    assert r.status_code == 401


def test_401_when_header_missing(client):
    assert client.post("/qpulse/ingest", json=_batch()).status_code == 401


def test_422_on_oversized_batch(client):
    body = _batch()
    body["alerts"] = body["alerts"] * (m.QPULSE_INGEST_MAX_BATCH + 1)
    r = client.post("/qpulse/ingest", json=body, headers={"X-Qpulse-Key": KEY})
    assert r.status_code == 422


def test_fanout_persists_event_visible_only_to_owner(client, rule):
    r = client.post("/qpulse/ingest", json=_batch(), headers={"X-Qpulse-Key": KEY})
    assert r.status_code == 200
    body = r.json()
    assert body["received"] == 1
    assert body["matched_rules"] == 1
    assert body["events_persisted"] == 1

    # BTC/USD must have been normalised to BTC-USD to match the rule.
    with Session(engine) as s:
        ev = s.exec(select(AlertEvent).where(AlertEvent.alert_id == rule)).one()
        assert ev.ticker == "BTC-USD"
        assert ev.triggered is True
        assert ev.payload["detector_source"] == "qpulse"
        assert ev.payload["qpulse"]["symbol_raw"] == "BTC/USD"
        assert ev.payload["qpulse"]["score"] == 7.2

    owner = client.get("/alerts/events", params={"detector_source": "qpulse"},
                       headers={"X-User-Id": str(USER_ID)})
    assert owner.status_code == 200
    assert any(i["alert_id"] == rule for i in owner.json()["items"])

    other = client.get("/alerts/events", params={"detector_source": "qpulse"},
                       headers={"X-User-Id": str(OTHER_USER_ID)})
    assert not any(i["alert_id"] == rule for i in other.json()["items"])


def test_second_alert_suppressed_by_cooldown(client, rule):
    h = {"X-Qpulse-Key": KEY}
    assert client.post("/qpulse/ingest", json=_batch(), headers=h).json()["events_persisted"] == 1
    second = client.post("/qpulse/ingest", json=_batch(), headers=h).json()
    assert second["events_persisted"] == 0
    assert second["suppressed"] and second["suppressed"][0]["symbol"] == "BTC-USD"


def test_unmatched_symbol_persists_nothing(client, rule):
    body = _batch(symbol="DOGE/USD")
    r = client.post("/qpulse/ingest", json=body, headers={"X-Qpulse-Key": KEY}).json()
    assert r["events_persisted"] == 0
    assert r["matched_rules"] == 0
    assert r["unmatched_symbols"] == ["DOGE-USD"]


def test_reference_gate_is_symbol_specific(client, rule):
    """BTC was gated; ETH was not. The gate must not generalise by asset class."""
    h = {"X-Qpulse-Key": KEY}
    client.post("/qpulse/ingest", json=_batch(kind="robust_z"), headers=h)
    with Session(engine) as s:
        ev = s.exec(select(AlertEvent).where(AlertEvent.alert_id == rule)).one()
        assert ev.payload["gated_on_reference_catalog"] is True
        assert "BTC daily-bar" in ev.payload["reference_gate"]

    # Same kind, same asset class, different symbol -> no gate claimed.
    with Session(engine) as s:
        eth = AlertRule(user_id=USER_ID, name="eth", ticker="ETH-USD",
                        alert_type="anomaly", is_active=True,
                        extra_config={"detector": "qpulse"})
        s.add(eth)
        s.commit()
        s.refresh(eth)
        eth_id = eth.id
    try:
        client.post("/qpulse/ingest", json=_batch(symbol="ETH/USD", kind="robust_z"),
                    headers=h)
        with Session(engine) as s:
            ev = s.exec(select(AlertEvent).where(AlertEvent.alert_id == eth_id)).one()
            assert ev.payload["gated_on_reference_catalog"] is False, \
                "ETH inherited a gate that was measured on BTC alone"
            assert ev.payload["reference_gate"] is None
    finally:
        with Session(engine) as s:
            for ev in s.exec(select(AlertEvent).where(AlertEvent.alert_id == eth_id)).all():
                s.delete(ev)
            obj = s.get(AlertRule, eth_id)
            if obj:
                s.delete(obj)
            s.commit()


def test_plain_anomaly_rule_is_not_written_to(client):
    """A rule that never opted in stays owned by the built-in z-score."""
    with Session(engine) as s:
        r = AlertRule(user_id=USER_ID, name="plain", ticker="BTC-USD",
                      alert_type="anomaly", is_active=True, extra_config={})
        s.add(r)
        s.commit()
        s.refresh(r)
        rid = r.id
    try:
        resp = client.post("/qpulse/ingest", json=_batch(),
                           headers={"X-Qpulse-Key": KEY}).json()
        assert resp["matched_rules"] == 0
        assert resp["events_persisted"] == 0
        with Session(engine) as s:
            assert s.exec(select(AlertEvent).where(AlertEvent.alert_id == rid)).all() == []
    finally:
        with Session(engine) as s:
            obj = s.get(AlertRule, rid)
            if obj:
                s.delete(obj)
            s.commit()


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_values_rejected(client, rule, bad):
    """json.loads accepts NaN/Infinity; persisting them would break later reads."""
    body = f'{{"source":"qpulse","asset_class":"crypto","alerts":[{{"symbol":"BTC/USD",' \
           f'"ts_ns":1,"kind":"robust_z","price":1.0,"score":{bad}}}]}}'
    r = client.post("/qpulse/ingest", content=body,
                    headers={"X-Qpulse-Key": KEY, "Content-Type": "application/json"})
    assert r.status_code == 422
    with Session(engine) as s:
        assert s.exec(select(AlertEvent).where(AlertEvent.alert_id == rule)).all() == []


def test_non_ascii_key_does_not_500(client):
    """Starlette decodes headers as latin-1, so a raw non-ASCII byte reaches the
    handler as a non-ASCII str — which makes compare_digest raise TypeError and
    return an unauthenticated 500 unless the comparison is done on bytes."""
    r = client.post("/qpulse/ingest", json=_batch(),
                    headers={b"X-Qpulse-Key": b"k\xe9y"})
    assert r.status_code == 401


def test_multiple_alerts_same_rule_one_survives_and_rest_reported(client, rule):
    """Intra-batch cooldown must be an explicit, reported decision."""
    body = _batch()
    body["alerts"] = [dict(body["alerts"][0]), dict(body["alerts"][0])]
    body["alerts"][1]["kind"] = "cusum"
    r = client.post("/qpulse/ingest", json=body, headers={"X-Qpulse-Key": KEY}).json()
    assert r["events_persisted"] == 1
    assert len(r["suppressed"]) == 1
    assert r["suppressed"][0]["kind"] == "cusum"


def test_spread_widen_is_not_gated(client, rule):
    """The frozen v1 artifact has zero spread_widen alerts — nothing was gated."""
    client.post("/qpulse/ingest", json=_batch(kind="spread_widen"),
                headers={"X-Qpulse-Key": KEY})
    with Session(engine) as s:
        ev = s.exec(select(AlertEvent).where(AlertEvent.alert_id == rule)).one()
        assert ev.payload["gated_on_reference_catalog"] is False


def test_skip_happens_before_any_price_fetch(rule, monkeypatch):
    """The skip must precede the vendor call, or every scheduler tick pays for it
    and the 'no price data' early return loses the skip marker entirely."""
    calls = []
    monkeypatch.setattr(m, "get_price_series_cached",
                        lambda *a, **k: calls.append(a) or [])
    with Session(engine) as s:
        result = m._evaluate_alert_rule(s.get(AlertRule, rule))
    assert result.get("skipped") is True
    assert calls == [], "price series fetched for an externally-evaluated rule"


def test_feed_filter_finds_matches_beyond_one_page(client, rule):
    """A fixed scan window would return an EMPTY feed, not a truncated one."""
    with Session(engine) as s:
        base = datetime.utcnow()
        s.add(AlertEvent(alert_id=rule, ticker="BTC-USD", alert_type="anomaly",
                         triggered=True, evaluated_at=base - timedelta(days=2),
                         payload={"detector_source": "qpulse", "reference_gate": None,
                                  "gated_on_reference_catalog": False,
                                  "qpulse": {"kind": "cusum", "score": 1.0}}))
        for i in range(600):
            s.add(AlertEvent(alert_id=rule, ticker="BTC-USD", alert_type="price_threshold",
                             triggered=True, evaluated_at=base - timedelta(minutes=i),
                             payload={"zscore": 1.0}))
        s.commit()

    items = client.get("/alerts/events",
                       params={"limit": 25, "triggered_only": True,
                               "detector_source": "qpulse"},
                       headers={"X-User-Id": str(USER_ID)}).json()["items"]
    assert len(items) == 1, "qpulse event lost behind a page of other events"


def test_naive_scheduler_skips_qpulse_rules(rule):
    """The built-in z-score must not evaluate or persist for a Qpulse-fed rule.

    Without this the naive branch writes a competing event every scheduler tick,
    consuming the shared cooldown and suppressing real Qpulse alerts.
    """
    with Session(engine) as s:
        obj = s.get(AlertRule, rule)
        result = m._evaluate_alert_rule(obj)
    assert result.get("skipped") is True
    assert result["triggered"] is False

    summary = m._evaluate_alerts_internal(alert_ids=[rule], persist=True)
    assert summary is not None
    with Session(engine) as s:
        events = s.exec(select(AlertEvent).where(AlertEvent.alert_id == rule)).all()
        assert events == [], "naive scheduler persisted a row for a Qpulse rule"


def test_cooldown_does_not_leak_across_rules(client):
    """Two rules on the same ticker each get their own event."""
    with Session(engine) as s:
        a = AlertRule(user_id=USER_ID, name="a", ticker="ETH-USD", alert_type="anomaly",
                      is_active=True, extra_config={"detector": "qpulse"})
        b = AlertRule(user_id=OTHER_USER_ID, name="b", ticker="ETH-USD",
                      alert_type="anomaly", is_active=True,
                      extra_config={"detector": "qpulse"})
        s.add(a)
        s.add(b)
        s.commit()
        s.refresh(a)
        s.refresh(b)
        ids = [a.id, b.id]
    try:
        r = client.post("/qpulse/ingest", json=_batch(symbol="ETH/USD"),
                        headers={"X-Qpulse-Key": KEY}).json()
        assert r["matched_rules"] == 2
        assert r["events_persisted"] == 2
    finally:
        with Session(engine) as s:
            for rid in ids:
                for ev in s.exec(select(AlertEvent).where(AlertEvent.alert_id == rid)).all():
                    s.delete(ev)
                obj = s.get(AlertRule, rid)
                if obj:
                    s.delete(obj)
            s.commit()
