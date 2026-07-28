"""Tests for holdings CSV parsing + the /portfolios/import endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.services.holdings_import import parse_holdings_csv


# --------------------------------------------------------------- parser (pure)

def test_parses_standard_schwab_like_csv():
    csv = (
        "Symbol,Quantity,Cost Basis,Date Acquired,Security Type\n"
        "AAPL,100,\"$15,000.00\",01/15/2023,Equity\n"
        "MSFT,50,\"$10,000\",2022-06-01,Equity\n"
    )
    out = parse_holdings_csv(csv)
    h = {x["ticker"]: x for x in out["holdings"]}
    assert h["AAPL"]["quantity"] == 100 and h["AAPL"]["cost_basis"] == 15000.0
    assert h["AAPL"]["purchase_date"] == "2023-01-15"
    assert h["MSFT"]["purchase_date"] == "2022-06-01"
    assert out["skipped"] == []


def test_unit_cost_multiplies_by_quantity():
    csv = "Ticker,Shares,Average Cost\nGOOGL,10,120.50\n"
    out = parse_holdings_csv(csv)
    assert out["holdings"][0]["cost_basis"] == pytest.approx(1205.0)


def test_skips_total_and_cash_junk_rows():
    csv = ("symbol,qty\nAAPL,10\nCash,,\nTOTAL,10\n")
    out = parse_holdings_csv(csv)
    assert [x["ticker"] for x in out["holdings"]] == ["AAPL"]
    assert any("Cash" in s["reason"] or "TOTAL" in s["reason"] for s in out["skipped"])


def test_accounting_negatives_and_semicolon_delimiter():
    csv = "symbol;quantity;cost basis\nSPY;5;(1,000.00)\n"
    out = parse_holdings_csv(csv)
    assert out["holdings"][0]["cost_basis"] == pytest.approx(-1000.0)


def test_missing_ticker_column_reports_clearly():
    out = parse_holdings_csv("shares,price\n10,20\n")
    assert out["holdings"] == []
    assert "ticker" in out["warnings"][0].lower()


def test_weight_column_captured_when_no_quantity():
    csv = "symbol,allocation\nAAPL,60%\nBND,40%\n"
    out = parse_holdings_csv(csv)
    assert out["holdings"][0]["_weight"] == pytest.approx(60.0)
    assert out["holdings"][1]["_weight"] == pytest.approx(40.0)


# --------------------------------------------------------------- endpoint

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


def _upload(client, csv_text, name="Imported"):
    return client.post(
        "/portfolios/import",
        files={"file": ("holdings.csv", csv_text, "text/csv")},
        data={"name": name},
        headers={"X-User-Id": "1"},
    )


def test_import_derives_market_value_weights(client):
    csv = "Symbol,Quantity,Cost Basis\nAAA,100,5000\nBBB,100,5000\n"
    # AAA @ $200, BBB @ $50 -> MV 20000 vs 5000 -> weights 0.8 / 0.2
    prices = {"AAA": [{"date": "2026-01-01", "price": 200.0}],
              "BBB": [{"date": "2026-01-01", "price": 50.0}]}
    import app.main as m
    with patch.object(m, "get_price_series_cached", side_effect=lambda t, **k: prices.get(t.upper(), [])):
        r = _upload(client, csv)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["import_report"]["weight_basis"] == "market_value"
    w = {a["ticker"]: a["weight"] for a in body["assets"]}
    assert w["AAA"] == pytest.approx(0.8, abs=0.01)
    assert w["BBB"] == pytest.approx(0.2, abs=0.01)
    # quantity + cost basis preserved
    q = {a["ticker"]: a for a in body["assets"]}
    assert q["AAA"]["quantity"] == 100 and q["AAA"]["cost_basis"] == 5000


def test_import_equal_weight_fallback_when_no_prices_or_weights(client):
    csv = "Symbol\nAAA\nBBB\nCCC\n"
    import app.main as m
    with patch.object(m, "get_price_series_cached", side_effect=lambda t, **k: []):
        r = _upload(client, csv)
    assert r.status_code == 200, r.text
    assert r.json()["import_report"]["weight_basis"] == "equal_weight"
    ws = [a["weight"] for a in r.json()["assets"]]
    assert all(abs(w - 1/3) < 0.01 for w in ws)


def test_import_rejects_unreadable_file(client):
    r = _upload(client, "no,useful,columns\n1,2,3\n")
    assert r.status_code == 400
