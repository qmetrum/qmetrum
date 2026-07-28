"""Tests for the onboarding narrator (LLM mocked, no Gemini call) and for the
onboarding PDF template building end-to-end with real-shaped data."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from app.agents import report_narrator as rn
from app.agents.llm import LlmResult
from app.reports.template_onboarding import generate_onboarding_report


FACTS = {
    "portfolio_name": "David Chen",
    "portfolio_value": 1_850_000,
    "risk_tolerance": "Moderate",
    "target_vol": 0.10,
    "risk_metrics": {"annualized_vol": 0.145, "sharpe_ratio": 0.68, "sortino_ratio": 0.91,
                     "max_drawdown": -0.182, "var_95_daily": -0.018, "cvar_95_daily": -0.027,
                     "beta": 1.08, "fragility_score": 1.21, "regime": "Normal"},
    "allocation": {"Equity": 0.65, "Fixed Income": 0.20, "Real Estate": 0.15},
    "holdings": [
        {"ticker": "QQQ", "weight": 0.40, "asset_type": "Equity"},
        {"ticker": "AAPL", "weight": 0.25, "asset_type": "Equity"},
        {"ticker": "BND", "weight": 0.20, "asset_type": "Fixed Income"},
        {"ticker": "VNQ", "weight": 0.15, "asset_type": "Real Estate"},
    ],
}


# Component risk decomposition: which holding drives portfolio RISK (share of
# volatility vs weight). QQQ carries a risk share above its weight; BND well
# below its. This is the concentration story an onboarding assessment is about.
RISK_ATTR = {
    "portfolio_vol": 0.145, "n_obs": 252,
    "rows": [
        {"ticker": "QQQ", "weight": 0.40, "risk_pct": 0.52},
        {"ticker": "AAPL", "weight": 0.25, "risk_pct": 0.30},
        {"ticker": "VNQ", "weight": 0.15, "risk_pct": 0.12},
        {"ticker": "BND", "weight": 0.20, "risk_pct": 0.06},
    ],
}


def _fake(text: str) -> LlmResult:
    return LlmResult(text=text, model="gemini-2.5-flash", prompt_tokens=10,
                     output_tokens=20, latency_ms=5, cached=False, input_hash="x")


def _payload(**over):
    base = {
        "risk_profile_summary": "rps", "what_to_watch": "wtw",
        "considerations": ["c1", "c2"],
    }
    base.update(over)
    return json.dumps(base)


# ── Narrator ──────────────────────────────────────────────────────────


def test_onboarding_prompt_is_grounded_and_forbids_dashes():
    p = rn.build_onboarding_prompt(FACTS)
    assert "David Chen" in p and "$1.85M" in p
    assert "stated risk tolerance: Moderate" in p
    assert "+10.00%" in p                       # stated target vol
    assert "+14.50%" in p                       # measured vol
    assert "gap vs target +4.50pp" in p         # real comparison, computed
    assert "Sharpe 0.68" in p and "max drawdown -18.20%" in p
    assert "fragility 1.21" in p
    assert "Equity: 65%" in p                   # allocation by asset type
    assert "QQQ: 40%, Equity" in p
    assert "NEVER use em dashes" in p


def test_onboarding_prompt_omits_absent_sections():
    facts = {k: v for k, v in FACTS.items() if k not in ("allocation", "holdings")}
    p = rn.build_onboarding_prompt(facts)
    assert "Current allocation by asset type" not in p
    assert "Holdings (ticker, weight, type)" not in p


def test_onboarding_prompt_grounds_risk_attribution():
    p = rn.build_onboarding_prompt(dict(FACTS, risk_attribution=RISK_ATTR))
    assert "Risk contribution by holding (portfolio annualized volatility 14.5%" in p
    assert "252 obs" in p
    assert "QQQ: weight 40%, risk share 52%" in p     # biggest risk driver, by number
    assert "BND: weight 20%, risk share 6%" in p      # risk share well below weight
    # The prompt must instruct naming the driver by number, not by assertion.
    assert "name the holding that contributes the MOST" in p


def test_onboarding_prompt_omits_risk_attribution_when_absent():
    p = rn.build_onboarding_prompt(FACTS)             # FACTS carries no risk_attribution
    assert "Risk contribution by holding" not in p


def test_run_onboarding_strips_any_dash_that_slips_through():
    with patch.object(rn, "generate", return_value=_fake(_payload(
            risk_profile_summary="Vol runs hot — 14.5% vs 10% – a real gap",
            considerations=["Discuss the gap — 4.5 points"]))):
        out, _ = rn.run_onboarding(facts=FACTS)
    assert "—" not in json.dumps(out) and "–" not in json.dumps(out)
    assert out["risk_profile_summary"] == "Vol runs hot, 14.5% vs 10%, a real gap"


def test_run_onboarding_cache_key_tracks_facts():
    captured = {}

    def _cap(prompt, **kw):
        captured.update(kw)
        return _fake(_payload())

    with patch.object(rn, "generate", side_effect=_cap):
        rn.run_onboarding(facts=FACTS)
    key = captured["cache_key_extra"]
    assert key["risk_tolerance"] == "Moderate"
    assert key["target_vol"] == pytest.approx(0.10)
    assert key["actual_vol"] == pytest.approx(0.145)
    assert key["risk_share_top"] is None            # no risk_attribution supplied
    assert {h["t"] for h in key["holdings"]} == {"QQQ", "AAPL", "BND", "VNQ"}
    assert captured["agent_name"] == "onboarding_narrator"
    assert captured["schema"] is rn.OnboardingNarrative


def test_run_onboarding_cache_key_tracks_top_risk_share():
    captured = {}

    def _cap(prompt, **kw):
        captured.update(kw)
        return _fake(_payload())

    with patch.object(rn, "generate", side_effect=_cap):
        rn.run_onboarding(facts=dict(FACTS, risk_attribution=RISK_ATTR))
    key = captured["cache_key_extra"]
    assert key["risk_share_top"] == pytest.approx(0.52)   # top holding's risk share


def test_run_onboarding_raises_on_malformed_json():
    with patch.object(rn, "generate", return_value=_fake("nope")):
        with pytest.raises(ValueError, match="malformed JSON"):
            rn.run_onboarding(facts=FACTS)


# ── Template (end-to-end PDF build) ───────────────────────────────────


def _template_data(**over):
    data = {
        "client_name": "David Chen",
        "advisor_name": "Alex Advisor",
        "firm_name": "Example Advisors",
        "report_date": datetime(2026, 7, 27),
        "portfolio_value": 1_850_000,
        "risk_tolerance": "Moderate",
        "target_vol": 0.10,
        "actual_vol": 0.145,
        "sharpe": 0.68,
        "max_drawdown": -0.182,
        "holdings": [
            {"ticker": "QQQ", "name": "Invesco QQQ Trust", "asset_type": "Equity",
             "weight": 0.40, "value": 740_000},
            {"ticker": "AAPL", "name": "Apple Inc.", "asset_type": "Equity",
             "weight": 0.25, "value": 462_500},
            {"ticker": "BND", "name": "Vanguard Total Bond", "asset_type": "Fixed Income",
             "weight": 0.20, "value": 370_000},
            {"ticker": "VNQ", "name": "Vanguard Real Estate", "asset_type": "Real Estate",
             "weight": 0.15, "value": 277_500},
        ],
        "current_allocation": {"Equity": 0.65, "Fixed Income": 0.20, "Real Estate": 0.15},
        # Component risk decomposition: which holding drives the portfolio's risk.
        "risk_attribution": {
            "portfolio_vol": 0.145, "n_obs": 252,
            "rows": [
                {"ticker": "QQQ", "weight": 0.40, "risk_pct": 0.52},
                {"ticker": "AAPL", "weight": 0.25, "risk_pct": 0.30},
                {"ticker": "VNQ", "weight": 0.15, "risk_pct": 0.12},
                {"ticker": "BND", "weight": 0.20, "risk_pct": 0.06},
            ],
        },
        "risk_findings": [
            "Portfolio volatility (14.5%) is 4.5% more than target (10%).",
            "Maximum drawdown of -18.2% indicates significant tail risk that may "
            "exceed comfort level for a Moderate investor.",
        ],
        "narrative": {
            "risk_profile_summary": "The portfolio runs at 14.5% volatility against a 10% target.",
            "what_to_watch": "The 4.5 point volatility gap and QQQ carrying 52% of the risk on a 40% weight.",
            "considerations": ["Evaluate whether the 10% target still fits the measured 14.5%."],
        },
    }
    data.update(over)
    return data


def _assert_pdf(path):
    blob = path.read_bytes()
    assert blob.startswith(b"%PDF")
    assert len(blob) > 10_000


def test_generate_onboarding_report_builds_pdf(tmp_path):
    out = tmp_path / "onboarding.pdf"
    generate_onboarding_report(str(out), _template_data())
    _assert_pdf(out)


def test_generate_onboarding_report_numbers_only(tmp_path):
    """No AI narrative: the PDF still builds, and the risk-contribution table
    (a computed decomposition, not narrative) still renders."""
    out = tmp_path / "onboarding_min.pdf"
    generate_onboarding_report(str(out), _template_data(narrative=None))
    _assert_pdf(out)


def test_generate_onboarding_report_omits_risk_attribution_when_none(tmp_path):
    """A single-holding or thin-history portfolio: the router returns None for
    the decomposition, so the section is omitted rather than fabricated."""
    out = tmp_path / "onboarding_no_ra.pdf"
    generate_onboarding_report(str(out), _template_data(risk_attribution=None))
    _assert_pdf(out)


def test_generate_onboarding_report_renders_risk_contribution_table(tmp_path):
    """The risk-contribution decomposition is actually built into the story: a
    styled_table with the risk header and the top driver's share of risk. Spying
    on styled_table verifies the rendering path (no PDF text extractor needed)."""
    from app.reports import template_onboarding as t

    tables = []
    orig = t.styled_table

    def _spy(data, *a, **kw):
        tables.append(data)
        return orig(data, *a, **kw)

    out = tmp_path / "onboarding_ra.pdf"
    with patch.object(t, "styled_table", side_effect=_spy):
        generate_onboarding_report(str(out), _template_data())
    _assert_pdf(out)

    risk_tables = [tbl for tbl in tables if tbl and tbl[0] == ["Holding", "Weight", "Share of risk"]]
    assert len(risk_tables) == 1
    rc = risk_tables[0]
    assert rc[1] == ["QQQ", "40%", "52%"]           # top risk driver, sorted first
    assert ["BND", "20%", "6%"] in rc               # risk share well below weight


def test_generate_onboarding_report_no_risk_table_when_absent(tmp_path):
    """When the decomposition is None, no risk-contribution table is built."""
    from app.reports import template_onboarding as t

    tables = []
    orig = t.styled_table

    def _spy(data, *a, **kw):
        tables.append(data)
        return orig(data, *a, **kw)

    out = tmp_path / "onboarding_no_ra2.pdf"
    with patch.object(t, "styled_table", side_effect=_spy):
        generate_onboarding_report(str(out), _template_data(risk_attribution=None))
    _assert_pdf(out)
    assert not any(tbl and tbl[0] == ["Holding", "Weight", "Share of risk"] for tbl in tables)


def test_generate_onboarding_report_handles_extreme_values(tmp_path):
    """A 92% weight (the old chart clipped above 55%) and 42% actual vol (the
    old gauge capped at 35%) must still build with everything on-canvas."""
    out = tmp_path / "onboarding_extreme.pdf"
    generate_onboarding_report(str(out), _template_data(
        actual_vol=0.42,
        current_allocation={"Equity": 0.92, "Fixed Income": 0.08},
    ))
    _assert_pdf(out)


def test_allocation_chart_axis_covers_any_weight():
    """The bar chart x-axis must extend past the largest weight so bars and
    their value labels are never clipped."""
    import matplotlib.pyplot as plt
    from app.reports import template_onboarding as t

    captured = {}
    orig = t._fig_to_image

    def _spy(fig, dpi=180):
        captured["xlim"] = fig.axes[0].get_xlim()
        return orig(fig, dpi=dpi)

    with patch.object(t, "_fig_to_image", side_effect=_spy):
        buf = t.make_allocation_chart({"Equity": 0.92, "Fixed Income": 0.08})
    assert buf.read(4) == b"\x89PNG"
    assert captured["xlim"][1] > 92.0


def test_gauge_axis_covers_high_volatility():
    """The gauge axis must extend past both markers instead of capping at 35."""
    from app.reports import template_onboarding as t

    captured = {}
    orig = t._fig_to_image

    def _spy(fig, dpi=180):
        captured["xlim"] = fig.axes[0].get_xlim()
        return orig(fig, dpi=dpi)

    with patch.object(t, "_fig_to_image", side_effect=_spy):
        t.make_risk_tolerance_gauge(42.0, 10.0)
    assert captured["xlim"][1] > 42.0
