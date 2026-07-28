"""Tests for the rebalancing narrator (LLM mocked, no Gemini call) and for the
rebalancing PDF template building end-to-end with real-shaped data."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from app.agents import report_narrator as rn
from app.agents.llm import LlmResult
from app.reports.template_rebalancing import generate_rebalancing_report


FACTS = {
    "portfolio_name": "Growth Fund",
    "portfolio_value": 2_450_000,
    "current_metrics": {"annualized_vol": 0.1105, "max_drawdown": -0.127,
                        "var_95": -0.0168, "sharpe": 0.82, "sortino": 1.14},
    "proposed_metrics": {"annualized_vol": 0.0920, "max_drawdown": -0.098,
                         "var_95": -0.0138, "sharpe": 0.96, "sortino": 1.38},
    "trades": [
        {"ticker": "VTI", "action": "Sell", "shares": 471, "value": 122_500,
         "from_weight": 0.35, "to_weight": 0.30},
        {"ticker": "BND", "action": "Buy", "shares": None, "value": 73_500,
         "from_weight": 0.25, "to_weight": 0.28},
        {"ticker": "GLD", "action": "Hold", "shares": None, "value": 0,
         "from_weight": 0.08, "to_weight": 0.08},
    ],
    "scenarios": [
        {"name": "base", "is_base": True,
         "current_return_pct": 2.1, "proposed_return_pct": 1.8},
        {"name": "bear_10", "is_base": False,
         "current_return_pct": -9.2, "proposed_return_pct": -6.5},
    ],
    # Component risk decomposition of each book (which holding drives its risk):
    # risk share diverges from weight, and the proposal spreads the risk out.
    "risk_attribution": {
        "portfolio_vol": 0.1105, "n_obs": 380,
        "rows": [
            {"ticker": "VTI", "weight": 0.52, "risk_pct": 0.62},
            {"ticker": "GLD", "weight": 0.12, "risk_pct": 0.28},
            {"ticker": "BND", "weight": 0.36, "risk_pct": 0.10},
        ],
    },
    "proposed_risk_attribution": {
        "portfolio_vol": 0.0920, "n_obs": 380,
        "rows": [
            {"ticker": "VTI", "weight": 0.44, "risk_pct": 0.50},
            {"ticker": "GLD", "weight": 0.16, "risk_pct": 0.38},
            {"ticker": "BND", "weight": 0.40, "risk_pct": 0.12},
        ],
    },
    "rationale": "Equity drift pushed the portfolio above its risk target.",
}


def _fake(text: str) -> LlmResult:
    return LlmResult(text=text, model="gemini-2.5-flash", prompt_tokens=10,
                     output_tokens=20, latency_ms=5, cached=False, input_hash="x")


def _payload(**over):
    base = {
        "proposal_summary": "ps", "trade_commentary": "tc",
        "considerations": ["c1", "c2"],
    }
    base.update(over)
    return json.dumps(base)


# ── Narrator ──────────────────────────────────────────────────────────


def test_rebalancing_prompt_is_grounded_and_forbids_dashes():
    p = rn.build_rebalancing_prompt(FACTS)
    assert "Growth Fund" in p and "$2.45M" in p
    assert "+11.05%" in p and "+9.20%" in p          # current/proposed vol
    assert "Sharpe 0.82" in p and "Sharpe 0.96" in p
    assert "volatility -1.85pp" in p                 # computed delta
    assert "Sharpe +0.14" in p
    assert "VTI: Sell, weight 35% -> 30%, $122K" in p
    assert "GLD: Hold, weight 8% -> 8%" in p         # no invented dollar value
    assert "bear_10: current -9.2%, proposed -6.5%" in p
    assert "Equity drift" in p
    assert "NEVER use em dashes" in p


def test_rebalancing_prompt_includes_risk_concentration():
    """The current and proposed risk decompositions reach the prompt so the
    narrative can reference which holding drives the book's risk today."""
    p = rn.build_rebalancing_prompt(FACTS)
    assert "Risk contribution by holding, CURRENT allocation" in p
    assert "Risk contribution by holding, PROPOSED allocation" in p
    # The concentration story: VTI carries a risk share (62%) above its weight (52%).
    assert "VTI: weight 52%, risk share 62%" in p
    assert "VTI: weight 44%, risk share 50%" in p
    # The system prompt now instructs the narrative to cite the concentration.
    assert "contributes the MOST to the current book's volatility" in p


def test_rebalancing_prompt_omits_absent_sections():
    facts = {k: v for k, v in FACTS.items()
             if k not in ("scenarios", "rationale", "risk_attribution",
                          "proposed_risk_attribution")}
    p = rn.build_rebalancing_prompt(facts)
    assert "Scenario stress comparison" not in p
    assert "stated rationale" not in p
    assert "Risk contribution by holding" not in p


def test_run_rebalancing_strips_any_dash_that_slips_through():
    with patch.object(rn, "generate", return_value=_fake(_payload(
            proposal_summary="Vol falls — Sharpe rises – overall",
            considerations=["Check BND — no share estimate"]))):
        out, _ = rn.run_rebalancing(facts=FACTS)
    assert "—" not in json.dumps(out) and "–" not in json.dumps(out)
    assert out["proposal_summary"] == "Vol falls, Sharpe rises, overall"


def test_run_rebalancing_cache_key_tracks_facts():
    captured = {}

    def _cap(prompt, **kw):
        captured.update(kw)
        return _fake(_payload())

    with patch.object(rn, "generate", side_effect=_cap):
        rn.run_rebalancing(facts=FACTS)
    key = captured["cache_key_extra"]
    assert key["current_vol"] == pytest.approx(0.1105)
    assert key["proposed_vol"] == pytest.approx(0.0920)
    assert key["risk_share_top"] == pytest.approx(0.62)      # VTI drives current risk
    assert key["proposed_risk_share_top"] == pytest.approx(0.50)
    assert {t["t"] for t in key["trades"]} == {"VTI", "BND", "GLD"}
    assert {s["name"] for s in key["scenarios"]} == {"base", "bear_10"}
    assert captured["agent_name"] == "rebalancing_narrator"
    assert captured["schema"] is rn.RebalancingNarrative


def test_run_rebalancing_raises_on_malformed_json():
    with patch.object(rn, "generate", return_value=_fake("nope")):
        with pytest.raises(ValueError, match="malformed JSON"):
            rn.run_rebalancing(facts=FACTS)


# ── Template (end-to-end PDF build) ───────────────────────────────────


def _template_data(**over):
    data = {
        "client_name": "Growth Fund",
        "advisor_name": "Alex Advisor",
        "firm_name": "Example Advisors",
        "report_date": datetime(2026, 7, 27),
        "portfolio_value": 2_450_000,
        "current_metrics": dict(FACTS["current_metrics"]),
        "proposed_metrics": dict(FACTS["proposed_metrics"]),
        "trades": [dict(t) for t in FACTS["trades"]],
        "scenarios": [dict(s) for s in FACTS["scenarios"]],
        "risk_attribution": {
            "portfolio_vol": FACTS["risk_attribution"]["portfolio_vol"],
            "n_obs": FACTS["risk_attribution"]["n_obs"],
            "rows": [dict(r) for r in FACTS["risk_attribution"]["rows"]],
        },
        "proposed_risk_attribution": {
            "portfolio_vol": FACTS["proposed_risk_attribution"]["portfolio_vol"],
            "n_obs": FACTS["proposed_risk_attribution"]["n_obs"],
            "rows": [dict(r) for r in FACTS["proposed_risk_attribution"]["rows"]],
        },
        "rationale": FACTS["rationale"],
        "tax_considerations": "Sales may realize capital gains; review lots before executing.",
        "narrative": {
            "proposal_summary": "The proposal cuts volatility and lifts the Sharpe ratio.",
            "trade_commentary": "The largest flow is the VTI trim of $122,500.",
            "considerations": ["Evaluate the BND buy given no share estimate was available."],
        },
    }
    data.update(over)
    return data


def _assert_pdf(path):
    blob = path.read_bytes()
    assert blob.startswith(b"%PDF")
    assert len(blob) > 10_000


def test_generate_rebalancing_report_builds_pdf(tmp_path):
    out = tmp_path / "rebalance.pdf"
    generate_rebalancing_report(str(out), _template_data())
    _assert_pdf(out)


def test_generate_rebalancing_report_omits_optional_sections(tmp_path):
    """No scenarios, no narrative, no tax notes, no share estimates, no risk
    decomposition: the PDF still builds, numbers-only."""
    trades = [dict(t, shares=None) for t in FACTS["trades"]]
    out = tmp_path / "rebalance_min.pdf"
    generate_rebalancing_report(str(out), _template_data(
        scenarios=[], narrative=None, tax_considerations=None, trades=trades,
        risk_attribution=None, proposed_risk_attribution=None,
    ))
    _assert_pdf(out)


def test_generate_rebalancing_report_current_only_risk_attribution(tmp_path):
    """When only the current book's risk decomposition is available (the
    proposed one is None), the section renders the current book alone."""
    out = tmp_path / "rebalance_current_only.pdf"
    generate_rebalancing_report(str(out), _template_data(
        proposed_risk_attribution=None,
    ))
    _assert_pdf(out)


def test_generate_rebalancing_report_risk_attribution_ticker_mismatch(tmp_path):
    """A holding present in only one book (e.g. a new position introduced by
    the proposal) must render as n/a on the missing side without crashing."""
    prop = _template_data()["proposed_risk_attribution"]
    prop["rows"].append({"ticker": "IAU", "weight": 0.10, "risk_pct": 0.05})
    out = tmp_path / "rebalance_mismatch.pdf"
    generate_rebalancing_report(str(out), _template_data(
        proposed_risk_attribution=prop,
    ))
    _assert_pdf(out)


def test_generate_rebalancing_report_handles_worsening_proposal(tmp_path):
    """A proposal that raises vol and lowers Sharpe must still build (the
    callout states the actual effect instead of claiming improvement)."""
    out = tmp_path / "rebalance_worse.pdf"
    generate_rebalancing_report(str(out), _template_data(
        proposed_metrics={"annualized_vol": 0.1400, "max_drawdown": -0.190,
                          "var_95": -0.0210, "sharpe": 0.70, "sortino": 0.95},
    ))
    _assert_pdf(out)


def test_generate_rebalancing_report_handles_unchanged_proposal(tmp_path):
    """Identical current and proposed metrics (the vacuous-proposal case) must
    build and not crash the conditional callout."""
    out = tmp_path / "rebalance_same.pdf"
    generate_rebalancing_report(str(out), _template_data(
        proposed_metrics=dict(FACTS["current_metrics"]),
    ))
    _assert_pdf(out)
