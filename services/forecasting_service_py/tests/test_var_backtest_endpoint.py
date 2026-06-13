"""HTTP integration tests for POST /portfolios/{id}/var_backtest.

Exercises the full wiring against a seeded SQLite DB: dev-mode auth
(X-User-Id), ownership 404, loading stored positions, the RiskSimulationCache
round-trip, and both methods. The price fetch is monkeypatched so no network
is hit.

NOTE: importing app.main is heavy (TensorFlow + sentence-transformers load on
import), so this module is slower than the pure-logic tests. Run on its own:
    python -m pytest tests/test_var_backtest_endpoint.py -q
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.logic.var_backtest_runner as runner
import app.main as m
from app.db.database import engine, init_db
from app.db.models import Portfolio, Position, User

USER_ID = 1
OTHER_USER_ID = 2


def _synthetic_series(n_days=900, seed=0):
    rng = np.random.default_rng(seed)
    biz = pd.bdate_range("2021-01-01", periods=n_days)
    mkt = rng.standard_normal(n_days) * 0.01

    def make(vol, beta, s):
        g = np.random.default_rng(s)
        rets = beta * mkt + g.standard_normal(n_days) * vol
        price = 100 * np.exp(np.cumsum(rets))
        return [{"date": d.strftime("%Y-%m-%d"), "price": float(p)}
                for d, p in zip(biz, price)]

    return {"AAA": make(0.012, 1.0, 1), "BBB": make(0.018, 1.2, 2),
            "CCC": make(0.009, 0.6, 3), "DDD": make(0.025, 0.8, 4)}


@pytest.fixture(scope="module")
def portfolio_id():
    init_db()
    with Session(engine) as s:
        for uid in (USER_ID, OTHER_USER_ID):
            if not s.get(User, uid):
                s.add(User(id=uid, email=f"u{uid}@qmetrum.dev", is_active=True))
        s.commit()
        pf = s.exec(select(Portfolio).where(Portfolio.user_id == USER_ID)).first()
        if not pf:
            pf = Portfolio(user_id=USER_ID, name="Test Portfolio")
            s.add(pf)
            s.commit()
            s.refresh(pf)
            for tk, w in [("AAA", 0.4), ("BBB", 0.3), ("CCC", 0.2), ("DDD", 0.1)]:
                s.add(Position(portfolio_id=pf.id, ticker=tk, weight=w))
            s.commit()
        return pf.id


@pytest.fixture
def client(monkeypatch):
    series = _synthetic_series()
    monkeypatch.setattr(runner, "get_price_series_cached",
                        lambda t, period="5y": series.get(t, []))
    return TestClient(m.app)  # no context-manager -> skip lifespan/startup workers


def _post(client, pid, body, uid=USER_ID):
    return client.post(f"/portfolios/{pid}/var_backtest", json=body,
                       headers={"X-User-Id": str(uid)})


def test_historical_endpoint_happy_path(client, portfolio_id):
    resp = _post(client, portfolio_id,
                 {"method": "historical", "n_backtest": 250, "est_window": 252,
                  "confidence": 0.95})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["method"] == "historical"
    assert body["portfolio_id"] == portfolio_id
    assert body["n_observations"] >= 200
    assert 0.0 <= body["breach_rate"] <= 0.2
    for key in ("kupiec", "christoffersen", "basel_traffic_light", "model_passes", "series"):
        assert key in body
    assert body["cache"]["hit"] is False


def test_uses_stored_positions_when_assets_omitted(client, portfolio_id):
    resp = _post(client, portfolio_id, {"method": "historical", "confidence": 0.90})
    assert resp.status_code == 200, resp.text
    assert set(resp.json()["params"]["tickers"]) == {"AAA", "BBB", "CCC", "DDD"}


def test_cache_roundtrip(client, portfolio_id):
    body = {"method": "historical", "n_backtest": 200, "est_window": 252,
            "confidence": 0.975}
    r1 = _post(client, portfolio_id, body)
    assert r1.status_code == 200, r1.text
    assert r1.json()["cache"]["hit"] is False
    r2 = _post(client, portfolio_id, body)
    assert r2.status_code == 200, r2.text
    assert r2.json()["cache"]["hit"] is True  # served from RiskSimulationCache


def test_portfolio_not_found(client):
    resp = _post(client, 99999, {"method": "historical"})
    assert resp.status_code == 404


def test_ownership_enforced(client, portfolio_id):
    # USER_ID owns the portfolio; OTHER_USER_ID must get a 404, not data.
    resp = _post(client, portfolio_id, {"method": "historical"}, uid=OTHER_USER_ID)
    assert resp.status_code == 404


def test_mps_fan_endpoint(client, portfolio_id):
    resp = _post(client, portfolio_id,
                 {"method": "mps_fan", "n_backtest": 30, "est_window": 120,
                  "n_simulations": 300})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["method"] == "mps_fan"
    assert body["n_observations"] >= 30
    assert all(v < 0 for v in body["series"]["var_threshold"])


def test_insufficient_history_returns_400(client, portfolio_id, monkeypatch):
    short = _synthetic_series(n_days=120)
    monkeypatch.setattr(runner, "get_price_series_cached",
                        lambda t, period="5y": short.get(t, []))
    # Distinct confidence -> distinct input_hash, so this is a cache miss that
    # actually recomputes against the short series (the cache key intentionally
    # does not vary with monkeypatched prices, only with MarketData freshness).
    resp = _post(client, portfolio_id,
                 {"method": "historical", "est_window": 252, "n_backtest": 250,
                  "confidence": 0.91})
    assert resp.status_code == 400
