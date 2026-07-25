"""Regression: the nightly-batch cache must never serve a request that carries
custom scenarios.

The nightly blob is computed with scenarios=[] and contains only the default
scenario set (base, bull_10, bear_10, high_vol_regime, low_vol_regime). Before
the gate, both portfolio-forecast endpoints fell back to it on a bare
portfolio/tickers match, silently swapping the user's scenario set for the
nightly defaults — the Scenario Builder then charted (and the AI explainer
explained) scenarios the user never configured.

NOTE: importing app.main is heavy; run on its own:
    python -m pytest tests/test_nightly_cache_scenario_gate.py -q
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import app.main as m
from app.db.database import engine, init_db
from app.db.models import Portfolio, PortfolioReportDataCache, Position, User

# Dedicated user so this module's portfolio never collides with other test
# modules that select "the first portfolio owned by user 1" from the shared DB.
USER_ID = 7

NIGHTLY_BLOB = {
    "tickers": ["AAA", "BBB"],
    "weights": {"AAA": 0.6, "BBB": 0.4},
    "portfolio_prices": [100.0] * 100,
    "forecast_result": {
        "forecast_prices": [100.0, 101.0],
        "forecast_dates": ["2026-07-01", "2026-07-02"],
    },
    "portfolio_summary_extras": {
        "scenarios": {
            "base": {"central": [100.0, 101.0]},
            "bull_10": {"central": [110.0, 111.0]},
        },
        "scenarios_legacy": {"base": [100.0, 101.0], "bull_10": [110.0, 111.0]},
    },
}

CUSTOM_SCENARIO = {
    "name": "Mild Recession",
    "initial_shock_pct": -0.05,
    "return_scale": 1.3,
    "drift_shift": -0.001,
}

SENTINEL_RESULT = {
    "sentinel": "live-compute-ran",
    "portfolio_summary": {
        "scenarios": {
            "base": {"central": [100.0, 101.0]},
            "Mild Recession": {"central": [95.0, 94.0]},
        },
        "forecast_dates": ["2026-07-01", "2026-07-02"],
    },
}


@pytest.fixture(scope="module")
def portfolio_id():
    init_db()
    with Session(engine) as s:
        if not s.get(User, USER_ID):
            s.add(User(id=USER_ID, email=f"u{USER_ID}@qmetrum.dev", is_active=True))
            s.commit()
        pf = Portfolio(user_id=USER_ID, name="Nightly Gate Portfolio")
        s.add(pf)
        s.commit()
        s.refresh(pf)
        for tk, w in [("AAA", 0.6), ("BBB", 0.4)]:
            s.add(Position(portfolio_id=pf.id, ticker=tk, weight=w))
        s.add(PortfolioReportDataCache(
            portfolio_id=pf.id, input_hash="nightly-gate-test", result_blob=NIGHTLY_BLOB))
        s.commit()
        return pf.id


@pytest.fixture
def client():
    return TestClient(m.app)  # no context-manager -> skip lifespan/startup workers


def _post_v2(client, pid, body):
    return client.post(
        f"/portfolios/{pid}/forecast?async_mode=false",
        json=body, headers={"X-User-Id": str(USER_ID)})


def test_default_request_still_served_from_nightly(client, portfolio_id):
    resp = _post_v2(client, portfolio_id, {"horizon_days": 90})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "cache"
    assert body["result"]["cache"]["cache_type"] == "nightly_batch"
    assert "bull_10" in body["result"]["portfolio_summary"]["scenarios"]


def test_custom_scenarios_bypass_nightly_cache(client, portfolio_id, monkeypatch):
    monkeypatch.setattr(
        m, "_compute_portfolio_forecast_result", lambda **kw: SENTINEL_RESULT)
    resp = _post_v2(client, portfolio_id,
                    {"horizon_days": 90, "scenarios": [CUSTOM_SCENARIO]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "live"                      # nightly blob NOT served
    assert body["result"]["sentinel"] == "live-compute-ran"
    assert "Mild Recession" in body["result"]["portfolio_summary"]["scenarios"]


def test_build_scenario_defs_include_flag():
    from app.logic.portfolio_logic import BUILTIN_SCENARIO_DEFS, build_scenario_defs

    # Default: builtins + customs, customs win on name collision.
    defs = build_scenario_defs([CUSTOM_SCENARIO, {"name": "bull_10", "initial_shock_pct": 0.2}])
    assert set(BUILTIN_SCENARIO_DEFS) <= set(defs)
    assert defs["bull_10"]["initial_shock_pct"] == 0.2
    assert "Mild Recession" in defs

    # Excluded: only the customs remain; nameless entries are dropped.
    defs = build_scenario_defs([CUSTOM_SCENARIO, {"name": "  "}], include_builtins=False)
    assert list(defs) == ["Mild Recession"]

    # The module constant must not be mutated by callers.
    defs = build_scenario_defs([{"name": "bull_10", "initial_shock_pct": 0.99}])
    assert BUILTIN_SCENARIO_DEFS["bull_10"]["initial_shock_pct"] == 0.10


def test_input_hash_keyed_by_builtin_flag():
    kwargs = dict(
        entity_type="portfolio", entity_id="1",
        assets=[{"ticker": "AAA", "weight": 1.0}], horizon_days=90,
        scenarios=[CUSTOM_SCENARIO], target_weights=None,
        latest_market_dates={"AAA": "2026-07-24"},
    )
    default_hash = m._portfolio_forecast_input_hash(**kwargs)
    explicit_true = m._portfolio_forecast_input_hash(**kwargs, include_builtin_scenarios=True)
    excluded = m._portfolio_forecast_input_hash(**kwargs, include_builtin_scenarios=False)
    # Back-compat: default/True keeps pre-flag hashes valid; False must differ.
    assert default_hash == explicit_true
    assert excluded != default_hash


def test_v2_forwards_builtin_flag_to_compute(client, portfolio_id, monkeypatch):
    seen = {}

    def _capture(**kw):
        seen.update(kw)
        return SENTINEL_RESULT

    monkeypatch.setattr(m, "_compute_portfolio_forecast_result", _capture)
    resp = _post_v2(client, portfolio_id,
                    {"horizon_days": 90, "scenarios": [CUSTOM_SCENARIO],
                     "include_builtin_scenarios": False})
    assert resp.status_code == 200, resp.text
    assert seen["include_builtin_scenarios"] is False


def test_excluding_builtins_bypasses_nightly_even_without_customs(client, portfolio_id, monkeypatch):
    # No custom scenarios, but builtins excluded -> the nightly blob (which
    # contains the builtins) must not be served.
    monkeypatch.setattr(
        m, "_compute_portfolio_forecast_result", lambda **kw: SENTINEL_RESULT)
    resp = _post_v2(client, portfolio_id,
                    {"horizon_days": 90, "include_builtin_scenarios": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "live"


def test_scenarioless_nightly_blob_never_served(client, monkeypatch):
    # A failed nightly analyze step writes a blob with extras.scenarios=None
    # (legacy blobs lack the key entirely). Serving it would return ZERO
    # scenarios — not even base/worst_case_cvar. Must fall through to live.
    with Session(engine) as s:
        pf = Portfolio(user_id=USER_ID, name="Broken Nightly Portfolio")
        s.add(pf)
        s.commit()
        s.refresh(pf)
        s.add(Position(portfolio_id=pf.id, ticker="EEE", weight=1.0))
        broken = dict(NIGHTLY_BLOB, tickers=["EEE"],
                      portfolio_summary_extras={"scenarios": None, "scenarios_legacy": None})
        s.add(PortfolioReportDataCache(
            portfolio_id=pf.id, input_hash="broken-nightly", result_blob=broken))
        s.commit()
        pid = pf.id

    monkeypatch.setattr(
        m, "_compute_portfolio_forecast_result", lambda **kw: SENTINEL_RESULT)
    resp = _post_v2(client, pid, {"horizon_days": 90})     # default request
    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "live"                   # blob rejected


def test_forecast_portfolio_gate(client, portfolio_id, monkeypatch):
    assets = [{"ticker": "AAA", "weight": 0.6}, {"ticker": "BBB", "weight": 0.4}]

    # Without scenarios: ticker-set match serves the nightly blob.
    resp = client.post("/forecast_portfolio", json={"assets": assets, "horizon_days": 90})
    assert resp.status_code == 200, resp.text
    assert resp.json()["cache"]["cache_type"] == "nightly_batch"

    # With scenarios: nightly must be skipped -> live PortfolioManager path.
    class _StubManager:
        def __init__(self, *a, **kw):
            pass

        def analyze_portfolio(self, **kw):
            assert any(s["name"] == "Mild Recession" for s in kw.get("scenarios") or [])
            return SENTINEL_RESULT

    monkeypatch.setattr(m, "PortfolioManager", _StubManager)
    resp = client.post("/forecast_portfolio",
                       json={"assets": assets, "horizon_days": 90,
                             "scenarios": [CUSTOM_SCENARIO]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["sentinel"] == "live-compute-ran"
