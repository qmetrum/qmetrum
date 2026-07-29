"""CRUD tests for saved scenario sessions."""

from __future__ import annotations

import pytest
from sqlmodel import Session


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.db.database import engine, init_db
    from app.db.models import User
    init_db()
    with Session(engine) as s:
        if not s.get(User, 1):
            s.add(User(id=1, email="u1@qmetrum.dev", is_active=True))
            s.commit()
    import app.main as m
    with TestClient(m.app) as c:
        yield c


H = {"X-User-Id": "1"}
H2 = {"X-User-Id": "2"}


def _payload():
    return {
        "name": "Q3 review",
        "portfolio_id": "3",
        "portfolio_value": 2_500_000,
        "scenarios": {"items": [{"name": "Base Case"}, {"name": "Severe Downturn"}]},
        "results": {"fanResults": {"base": {"central": [100, 101]}}, "forecastDates": ["2026-01-01", "2026-01-02"]},
    }


def test_save_list_load_delete_roundtrip(client):
    r = client.post("/scenario-sessions", json=_payload(), headers=H)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert r.json()["n_scenarios"] == 2 and r.json()["has_results"] is True

    lst = client.get("/scenario-sessions", headers=H).json()["items"]
    assert any(x["id"] == sid and x["name"] == "Q3 review" for x in lst)

    full = client.get(f"/scenario-sessions/{sid}", headers=H).json()
    assert full["scenarios"]["items"][1]["name"] == "Severe Downturn"
    assert full["results"]["fanResults"]["base"]["central"] == [100, 101]
    assert full["portfolio_value"] == 2_500_000

    d = client.delete(f"/scenario-sessions/{sid}", headers=H)
    assert d.status_code == 200 and d.json()["deleted"] is True
    assert client.get(f"/scenario-sessions/{sid}", headers=H).status_code == 404


def test_sessions_are_user_scoped(client):
    with Session(__import__("app.db.database", fromlist=["engine"]).engine) as s:
        from app.db.models import User
        if not s.get(User, 2):
            s.add(User(id=2, email="u2@qmetrum.dev", is_active=True)); s.commit()
    sid = client.post("/scenario-sessions", json=_payload(), headers=H).json()["id"]
    # user 2 cannot see or load user 1's session
    assert all(x["id"] != sid for x in client.get("/scenario-sessions", headers=H2).json()["items"])
    assert client.get(f"/scenario-sessions/{sid}", headers=H2).status_code == 404
    assert client.delete(f"/scenario-sessions/{sid}", headers=H2).status_code == 404


def test_save_requires_name(client):
    r = client.post("/scenario-sessions", json={**_payload(), "name": "  "}, headers=H)
    assert r.status_code == 400
