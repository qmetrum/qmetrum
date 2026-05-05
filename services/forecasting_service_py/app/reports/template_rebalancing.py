"""
Template 4: REBALANCING PROPOSAL
─────────────────────────────────
Purpose: Advisor proposes portfolio changes with projected impact on risk/return.
Maps to: /portfolio/analyze with target_weights + scenario engine.
"""

import numpy as np
from io import BytesIO
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image

from app.reports.report_styles import *


def make_before_after_risk(current_metrics, proposed_metrics):
    """Grouped bar chart: current vs proposed for key risk metrics."""
    fig, ax = plt.subplots(figsize=(6.8, 2.6))

    labels = ["Ann. volatility", "Max drawdown", "VaR (95%)", "Sharpe ratio"]
    current = [
        current_metrics["annualized_vol"] * 100,
        abs(current_metrics["max_drawdown"]) * 100,
        abs(current_metrics["var_95"]) * 100,
        current_metrics["sharpe"],
    ]
    proposed = [
        proposed_metrics["annualized_vol"] * 100,
        abs(proposed_metrics["max_drawdown"]) * 100,
        abs(proposed_metrics["var_95"]) * 100,
        proposed_metrics["sharpe"],
    ]

    x = np.arange(len(labels))
    w = 0.32
    bars1 = ax.bar(x - w/2, current, w, color="#8B95A2", edgecolor="white", linewidth=0.5, label="Current")
    bars2 = ax.bar(x + w/2, proposed, w, color="#0F8B6E", edgecolor="white", linewidth=0.5, label="Proposed")

    for bars in [bars1, bars2]:
        for bar in bars:
            val = bar.get_height()
            fmt = f"{val:.1f}%" if val > 1 else f"{val:.2f}"
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                    fmt, ha="center", va="bottom", fontsize=7, color="#1A1A2E", fontweight="500")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDE1E6")
    ax.spines["bottom"].set_color("#DDE1E6")
    ax.tick_params(colors="#5A6270", labelsize=7.5)
    ax.grid(axis="y", color="#EEF0F3", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title("Risk profile: current vs. proposed",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=10)
    ax.legend(fontsize=7.5, loc="upper right", framealpha=0.9, edgecolor="#DDE1E6")

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def make_scenario_impact(scenarios):
    """Butterfly chart: current return vs proposed return per scenario."""
    fig, ax = plt.subplots(figsize=(6.8, 2.4))

    names = [s["name"] for s in scenarios]
    curr = [s["current_return"] * 100 for s in scenarios]
    prop = [s["proposed_return"] * 100 for s in scenarios]

    y = np.arange(len(names))
    h = 0.3
    ax.barh(y - h/2, curr, h, color="#8B95A2", edgecolor="white", linewidth=0.5, label="Current")
    ax.barh(y + h/2, prop, h, color="#0F8B6E", edgecolor="white", linewidth=0.5, label="Proposed")

    for i, (c, p) in enumerate(zip(curr, prop)):
        ax.text(max(c, p) + 0.8, i, f"{'+'if p-c>0 else ''}{p-c:.1f}pp",
                va="center", fontsize=7, color="#0F8B6E" if p > c else "#D85A30", fontweight="600")

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=8)
    ax.axvline(0, color="#8B95A2", linewidth=0.8)
    ax.invert_yaxis()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDE1E6")
    ax.spines["bottom"].set_color("#DDE1E6")
    ax.tick_params(colors="#5A6270", labelsize=7.5)
    ax.grid(axis="x", color="#EEF0F3", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title("Scenario outcomes: improvement from rebalance",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=10)
    ax.set_xlabel("Projected 12-month return (%)", fontsize=8, color="#5A6270")
    ax.legend(fontsize=7.5, loc="lower right", framealpha=0.9, edgecolor="#DDE1E6")

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_rebalancing_report(output_path, data):
    """
    data = {
        "client_name", "advisor_name", "firm_name", "report_date",
        "portfolio_value",
        "current_metrics": {annualized_vol, max_drawdown, var_95, sharpe, sortino},
        "proposed_metrics": {same keys},
        "trades": [{"ticker","action","shares","value","from_weight","to_weight"}],
        "scenarios": [{"name","current_return","proposed_return"}],
        "rationale": str,
        "tax_considerations": str,
        "implementation_notes": [str],
    }
    """
    d = data
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                            topMargin=60, bottomMargin=60, leftMargin=54, rightMargin=54)
    story = []

    vol_reduction = (d["current_metrics"]["annualized_vol"] - d["proposed_metrics"]["annualized_vol"]) * 100
    sharpe_improvement = d["proposed_metrics"]["sharpe"] - d["current_metrics"]["sharpe"]

    def on_first(c, doc_obj):
        draw_cover_page(c, doc_obj,
            firm_name=d["firm_name"], client_name=d["client_name"],
            report_date=d["report_date"],
            report_type="REBALANCING PROPOSAL",
            subtitle=f"Prepared for review — {d['report_date'].strftime('%B %d, %Y')}",
            cover_metrics=[
                ("PORTFOLIO", f"${d['portfolio_value']:,.0f}"),
                ("VOL REDUCTION", f"{vol_reduction:+.1f}%"),
                ("SHARPE CHANGE", f"{sharpe_improvement:+.2f}"),
                ("TRADES", f"{len(d['trades'])}"),
            ])

    def on_later(c, doc_obj):
        draw_header_footer(c, doc_obj, firm_name=d["firm_name"], client_name=d["client_name"],
                           report_date=d["report_date"], advisor_name=d["advisor_name"])

    story.append(Spacer(1, 1))
    story.append(PageBreak())

    # Page 2: Rationale + Risk comparison
    story.append(Paragraph("PROPOSAL OVERVIEW", s_section))
    story.append(Paragraph("Why rebalance now?", s_heading))
    story.append(Paragraph(d["rationale"], s_body))
    story.append(Spacer(1, 6))

    story.append(callout_box(
        f"<b>Projected improvement:</b> This rebalance reduces annualized volatility by "
        f"{abs(vol_reduction):.1f} percentage points while improving the Sharpe ratio from "
        f"{d['current_metrics']['sharpe']:.2f} to {d['proposed_metrics']['sharpe']:.2f}. "
        f"You get better risk-adjusted returns with less downside exposure.",
    ))
    story.append(Spacer(1, 8))

    ba_buf = make_before_after_risk(d["current_metrics"], d["proposed_metrics"])
    story.append(Image(ba_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.38))

    story.append(PageBreak())

    # Page 3: Trades + Scenario Impact
    story.append(Paragraph("PROPOSED TRADES", s_section))
    story.append(Paragraph("What changes", s_heading))

    t_data = [["Ticker", "Action", "Shares", "Value", "Current wt.", "Target wt."]]
    for t in d["trades"]:
        t_data.append([
            t["ticker"], t["action"],
            f"{t['shares']:,.0f}", f"${t['value']:,.0f}",
            f"{t['from_weight']*100:.0f}%", f"{t['to_weight']*100:.0f}%",
        ])
    story.append(styled_table(t_data, [0.10, 0.14, 0.14, 0.20, 0.21, 0.21]))
    story.append(Spacer(1, 12))

    # Scenario impact
    story.append(Paragraph("SCENARIO STRESS TEST", s_section))
    story.append(Paragraph("How the proposal performs under stress", s_subheading))
    sc_buf = make_scenario_impact(d["scenarios"])
    story.append(Image(sc_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.35))
    story.append(Spacer(1, 10))

    # Tax + implementation
    if d.get("tax_considerations"):
        story.append(Paragraph("TAX CONSIDERATIONS", s_section))
        story.append(Paragraph(d["tax_considerations"], s_body))
        story.append(Spacer(1, 6))

    if d.get("implementation_notes"):
        story.append(Paragraph("IMPLEMENTATION PLAN", s_section))
        for i, note in enumerate(d["implementation_notes"], 1):
            story.append(Paragraph(f"<b>{i}.</b>  {note}", s_body))

    story.extend(standard_disclaimer(d["firm_name"], d["advisor_name"]))

    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return output_path


# ── DEMO ──
if __name__ == "__main__":
    demo = {
        "client_name": "Richardson Family Trust",
        "advisor_name": "Sarah Mitchell, CFA",
        "firm_name": "Meridian Wealth Advisors",
        "report_date": datetime(2026, 3, 16),
        "portfolio_value": 2_450_000,
        "current_metrics":  {"annualized_vol": 0.1105, "max_drawdown": -0.127, "var_95": -0.0168, "sharpe": 0.82, "sortino": 1.14},
        "proposed_metrics": {"annualized_vol": 0.0920, "max_drawdown": -0.098, "var_95": -0.0138, "sharpe": 0.96, "sortino": 1.38},
        "trades": [
            {"ticker": "VTI",  "action": "Sell",  "shares": 180, "value": 42300,  "from_weight": 0.35, "to_weight": 0.30},
            {"ticker": "VXUS", "action": "Buy",   "shares": 250, "value": 14750,  "from_weight": 0.15, "to_weight": 0.18},
            {"ticker": "BND",  "action": "Buy",   "shares": 280, "value": 20440,  "from_weight": 0.25, "to_weight": 0.28},
            {"ticker": "VTIP", "action": "Buy",   "shares": 120, "value": 5880,   "from_weight": 0.07, "to_weight": 0.09},
            {"ticker": "VNQ",  "action": "Sell",  "shares": 50,  "value": 4550,   "from_weight": 0.10, "to_weight": 0.08},
            {"ticker": "GLD",  "action": "Hold",  "shares": 0,   "value": 0,      "from_weight": 0.08, "to_weight": 0.07},
        ],
        "scenarios": [
            {"name": "Base case",       "current_return": 0.072, "proposed_return": 0.068},
            {"name": "Mild recession",  "current_return": -0.092, "proposed_return": -0.065},
            {"name": "Severe downturn", "current_return": -0.234, "proposed_return": -0.178},
            {"name": "Rate spike",      "current_return": -0.055, "proposed_return": -0.032},
        ],
        "rationale":
            "Three factors drive this rebalance. First, the portfolio has drifted 5% above its "
            "equity target due to strong US stock performance in Q1, increasing concentration risk. "
            "Second, our GARCH model indicates volatility is near its 6-month median but the term "
            "structure is inverted, suggesting a potential volatility spike ahead. Third, the current "
            "Sharpe ratio of 0.82 can be improved to an estimated 0.96 by shifting 5% from domestic "
            "equity into international bonds and inflation-protected securities.",
        "tax_considerations":
            "The VTI sale generates approximately $8,200 in long-term capital gains (holding period "
            "> 1 year, 15% LTCG rate). The VNQ sale is tax-neutral as the position is at cost basis. "
            "Net estimated tax impact: ~$1,230. We recommend executing this within the current tax "
            "year to offset against the $4,100 in harvested losses from Q4 2025.",
        "implementation_notes": [
            "Execute VTI and VNQ sells first (Day 1) to generate cash for purchases.",
            "Execute VXUS, BND, and VTIP buys on Day 2 using limit orders at market open.",
            "GLD position remains unchanged — no trade required.",
            "Confirm settlement (T+1) before updating model portfolio weights in Orion.",
            "Send updated allocation confirmation to client within 48 hours of execution.",
        ],
    }
    generate_rebalancing_report("/home/claude/reports/rebalancing_report.pdf", demo)
    print("Rebalancing report generated.")
