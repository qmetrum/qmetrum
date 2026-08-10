"""Regime Watch alert path: the evaluator reads the precomputed snapshot and fires
on the rising edge (short corr >= own baseline + margin); the explainer narrates it
as a measurement with no accuracy/prediction language. Hermetic (seeds its own rows)."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import Session, delete, select

import app.main as m
from app.db.database import engine, init_db
from app.db.models import AlertRule, PortfolioRegimeSnapshot, Portfolio, User

UID = 7770
PID_TRIG = 7771      # short 0.60 vs baseline 0.40 -> 0.60 >= 0.40+0.15 -> fires
PID_QUIET = 7772     # short 0.20 vs baseline 0.15 -> 0.20 <  0.15+0.15 -> quiet


@pytest.fixture()
def seeded():
    init_db()
    with Session(engine) as s:
        if not s.get(User, UID):
            s.add(User(id=UID, email="regime@qmetrum.dev", is_active=True))
            s.commit()
        for pid, name in ((PID_TRIG, "Trig"), (PID_QUIET, "Quiet")):
            if not s.get(Portfolio, pid):
                s.add(Portfolio(id=pid, user_id=UID, name=name))
        s.commit()
        s.exec(delete(PortfolioRegimeSnapshot).where(
            PortfolioRegimeSnapshot.portfolio_id.in_([PID_TRIG, PID_QUIET])))
        s.commit()
        s.add(PortfolioRegimeSnapshot(portfolio_id=PID_TRIG, status="ok", short_window=60,
              baseline_window=252, short_corr=0.60, baseline_corr=0.40, delta=0.20, n_obs=60,
              as_of=datetime(2026, 4, 29), method="test", data_source="test"))
        s.add(PortfolioRegimeSnapshot(portfolio_id=PID_QUIET, status="ok", short_window=60,
              baseline_window=252, short_corr=0.20, baseline_corr=0.15, delta=0.05, n_obs=60,
              as_of=datetime(2026, 4, 29), method="test", data_source="test"))
        s.commit()
    yield


def _rule(pid, margin=0.15):
    return AlertRule(id=990000 + pid, user_id=UID, name="rw", ticker=f"__PORT_{pid}__",
                     alert_type="regime_watch", direction="above", threshold_value=0.0,
                     lookback_days=60, is_active=True,
                     extra_config={"portfolio_id": pid, "margin": margin})


def test_fires_above_baseline_plus_margin(seeded):
    r = m._evaluate_alert_rule(_rule(PID_TRIG))
    assert r["triggered"] is True
    assert r["detector_source"] == "regime_watch"
    assert r["value"] == 0.60 and r["baseline"] == 0.40 and r["portfolio_id"] == PID_TRIG


def test_quiet_within_margin(seeded):
    r = m._evaluate_alert_rule(_rule(PID_QUIET))
    assert r["triggered"] is False
    assert r["detector_source"] == "regime_watch"


def test_no_snapshot_is_untriggered(seeded):
    r = m._evaluate_alert_rule(_rule(999999))
    assert r["triggered"] is False
    assert "available" in r.get("reason", "").lower()


def test_no_vendor_call_in_regime_eval(seeded, monkeypatch):
    # The regime branch must NOT hit the price vendor (it reads the snapshot).
    def _boom(*a, **k):
        raise AssertionError("regime_watch must not call get_price_series_cached")
    monkeypatch.setattr(m, "get_price_series_cached", _boom)
    r = m._evaluate_alert_rule(_rule(PID_TRIG))
    assert r["triggered"] is True


def test_explainer_prompt_is_honest_measurement():
    from app.agents.alert_explainer import build_prompt
    ev = {"evaluated_at": "2026-04-29T00:00:00Z", "triggered": True,
          "payload": {"detector_source": "regime_watch", "triggered": True, "value": 0.6,
                      "baseline": 0.4, "delta": 0.2, "margin": 0.15, "as_of": "2026-04-29",
                      "portfolio_id": PID_TRIG}}
    p = build_prompt("Regime Watch", "__PORT_7771__", "regime_watch", "above", 0.0, ev, []).lower()
    assert "measurement" in p
    assert "not a forecast" in p
    assert "correlation" in p
    assert "threshold 0.00" not in p          # no fabricated threshold
