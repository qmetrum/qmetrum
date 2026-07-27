"""The alert explainer must describe a Qpulse detector event honestly.

Pure prompt-construction tests — no LLM call, so these run fast.
"""
from __future__ import annotations

from app.agents import alert_explainer


def _event(kind="robust_z", gated=True, gate="BTC daily-bar crisis catalog (v1)",
           feed="crypto", severity="WARNING", score=7.2):
    return {
        "id": 1,
        "evaluated_at": "2026-07-27T10:00:00",
        "triggered": True,
        "payload": {
            "detector_source": "qpulse",
            "reference_gate": gate if gated else None,
            "gated_on_reference_catalog": gated,
            "qpulse": {
                "kind": kind, "score": score, "severity": severity,
                "narrative": f"{severity}: deviation on BTC/USD",
                "price": 42000.5, "feed": feed, "asset_class": "crypto",
            },
        },
    }


def _prompt(event, exposures=None):
    return alert_explainer.build_prompt(
        rule_name="BTC anomaly", ticker="BTC-USD", alert_type="anomaly",
        direction="above", threshold=0.0, latest_event=event,
        exposures=exposures if exposures is not None
        else [{"portfolio_name": "Growth", "weight": 0.12}],
    )


def test_qpulse_event_is_described_not_treated_as_threshold_rule():
    p = _prompt(_event())
    assert "robust_z" in p
    assert "7.20" in p
    # The fabricated "direction above, threshold 0.00" line must be gone.
    assert "threshold 0.00" not in p
    assert "no fixed threshold" in p


def test_gated_detector_names_the_catalog_and_limits_the_claim():
    p = _prompt(_event(gated=True))
    assert "BTC daily-bar crisis catalog (v1)" in p
    assert "unmeasured" in p.lower()


def test_ungated_detector_is_flagged_experimental():
    p = _prompt(_event(kind="spread_widen", gated=False, gate=None))
    assert "experimental" in p.lower()
    assert "NOT been scored" in p


def test_synthetic_feed_is_flagged():
    p = _prompt(_event(feed="synthetic"))
    assert "synthetic" in p.lower()
    assert "not live market data" in p.lower()


def test_csv_replay_feed_is_flagged():
    assert "replayed" in _prompt(_event(feed="csv")).lower()


def test_system_prompt_forbids_inventing_a_track_record():
    p = _prompt(_event())
    assert "never imply an accuracy" in p.lower()
    assert "not a prediction" in p.lower()


def test_exposure_context_is_preserved():
    p = _prompt(_event())
    assert "Growth" in p and "12.0%" in p


def test_no_holdings_says_impact_limited():
    p = _prompt(_event(), exposures=[])
    assert "not currently held" in p


def test_legacy_threshold_alert_is_unchanged():
    """The naive path must keep its original prompt shape."""
    legacy = {
        "id": 2, "evaluated_at": "2026-07-27T10:00:00", "triggered": True,
        "payload": {"zscore": 3.1, "value": 431.2, "threshold": 2.5},
    }
    p = _prompt(legacy)
    assert "direction above, threshold 0.00" in p
    assert "value=431.2" in p
    assert "Detector event" not in p
