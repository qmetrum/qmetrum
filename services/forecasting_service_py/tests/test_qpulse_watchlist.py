"""GET /qpulse/watchlist — the symbol list Qpulse configures itself from."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.main as m
from app.db.database import engine, init_db
from app.db.models import AlertRule, Asset, User

KEY = "watchlist-test-key"
USER_ID = 90401


@pytest.fixture(scope="module", autouse=True)
def _user():
    init_db()
    with Session(engine) as s:
        if not s.get(User, USER_ID):
            s.add(User(id=USER_ID, email=f"u{USER_ID}@qmetrum.dev", is_active=True))
            s.commit()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(m, "QPULSE_INGEST_KEY", KEY)
    return TestClient(m.app)


@pytest.fixture
def rules():
    """A mix of crypto and equity rules, plus decoys that must be excluded."""
    made = []
    with Session(engine) as s:
        specs = [
            ("BTC-USD", "anomaly", True, {"detector": "qpulse"}),
            ("ETH-USD", "anomaly", True, {"detector": "qpulse"}),
            ("AAPL", "anomaly", True, {"detector": "qpulse"}),
            ("MSFT", "anomaly", True, {"detector": "qpulse"}),
            ("TSLA", "anomaly", False, {"detector": "qpulse"}),   # inactive
            ("NVDA", "anomaly", True, {}),                        # not opted in
            ("SPY", "price_threshold", True, {"detector": "qpulse"}),  # wrong type
        ]
        for ticker, atype, active, cfg in specs:
            r = AlertRule(user_id=USER_ID, name=f"{ticker} r", ticker=ticker,
                          alert_type=atype, is_active=active, extra_config=cfg)
            s.add(r)
            made.append(r)
        s.commit()
        ids = [r.id for r in made]
        # BTC classified in the registry; ETH deliberately left unclassified so
        # the symbol-shape fallback is exercised.
        if not s.get(Asset, "BTC-USD"):
            s.add(Asset(symbol="BTC-USD", asset_class="CRYPTO"))
        s.commit()
    yield
    with Session(engine) as s:
        for rid in ids:
            obj = s.get(AlertRule, rid)
            if obj:
                s.delete(obj)
        s.commit()


def _get(client, feed):
    return client.get("/qpulse/watchlist", params={"feed": feed},
                      headers={"X-Qpulse-Key": KEY})


def test_requires_the_shared_secret(client):
    assert client.get("/qpulse/watchlist").status_code == 401
    assert client.get("/qpulse/watchlist",
                      headers={"X-Qpulse-Key": "nope"}).status_code == 401


def test_503_when_unconfigured(monkeypatch):
    monkeypatch.setattr(m, "QPULSE_INGEST_KEY", "")
    assert TestClient(m.app).get(
        "/qpulse/watchlist", headers={"X-Qpulse-Key": "x"}).status_code == 503


def test_crypto_feed_returns_slash_pairs_only(client, rules):
    body = _get(client, "crypto").json()
    assert set(body["symbols"]) >= {"BTC/USD", "ETH/USD"}
    assert all("/" in s for s in body["symbols"]), body["symbols"]
    assert "AAPL" not in body["symbols"]


def test_equity_feed_returns_plain_tickers_only(client, rules):
    body = _get(client, "iex").json()
    assert {"AAPL", "MSFT"} <= set(body["symbols"])
    assert all("/" not in s for s in body["symbols"]), body["symbols"]
    assert "BTC/USD" not in body["symbols"] and "BTC-USD" not in body["symbols"]


def test_unclassified_crypto_falls_back_to_symbol_shape(client, rules):
    """ETH-USD has no Asset row; the -USD suffix must still route it to crypto."""
    assert "ETH/USD" in _get(client, "crypto").json()["symbols"]
    assert "ETH-USD" not in _get(client, "iex").json()["symbols"]


def test_excludes_inactive_unopted_and_wrong_type(client, rules):
    everything = set(_get(client, "crypto").json()["symbols"]) | \
                 set(_get(client, "iex").json()["symbols"])
    assert "TSLA" not in everything, "inactive rule leaked in"
    assert "NVDA" not in everything, "rule without detector=qpulse leaked in"
    assert "SPY" not in everything, "price_threshold rule leaked in"


def test_watchlist_matches_what_ingest_will_accept(client, rules):
    """The subscription must not drift from the set ingest writes to."""
    listed = _get(client, "iex").json()["symbols"]
    assert "AAPL" in listed
    r = client.post("/qpulse/ingest", headers={"X-Qpulse-Key": KEY}, json={
        "source": "qpulse", "feed": "iex", "asset_class": "equities",
        "alerts": [{"symbol": "AAPL", "ts_ns": 1, "kind": "robust_z",
                    "price": 1.0, "score": 5.0}]})
    assert r.json()["matched_rules"] >= 1

    # NVDA is excluded from the watchlist, and ingest must equally refuse it.
    assert "NVDA" not in listed
    r2 = client.post("/qpulse/ingest", headers={"X-Qpulse-Key": KEY}, json={
        "source": "qpulse", "feed": "iex", "asset_class": "equities",
        "alerts": [{"symbol": "NVDA", "ts_ns": 1, "kind": "robust_z",
                    "price": 1.0, "score": 5.0}]})
    assert r2.json()["matched_rules"] == 0


def test_truncation_is_reported_not_silent(client, rules, monkeypatch):
    monkeypatch.setattr(m, "QPULSE_WATCHLIST_MAX", 1)
    body = _get(client, "iex").json()
    assert body["truncated"] is True
    assert len(body["symbols"]) == 1


def test_empty_when_no_rules(client):
    body = _get(client, "crypto").json()
    assert body["count"] == len(body["symbols"])
