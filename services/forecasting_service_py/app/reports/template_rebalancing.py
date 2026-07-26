"""
Template 4: REBALANCING PROPOSAL
Purpose: Advisor proposes portfolio changes with the COMPUTED impact on
risk/return: current vs proposed metrics from each allocation's own history,
optional simulated scenario stress for both weight sets, and an AI narrative
grounded only in those numbers.
Maps to: /reports/rebalancing (engine runs on both allocations).
"""

import numpy as np
from io import BytesIO
from xml.sax.saxutils import escape

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image

from app.reports.report_styles import *


def make_before_after_risk(current_metrics, proposed_metrics):
    """Grouped bar chart: current vs proposed for key risk metrics."""
    fig, ax = plt.subplots(figsize=(6.8, 2.6))

    # (label, metric key, is_percentage); percentages are plotted as magnitudes
    metrics = [
        ("Ann. volatility", "annualized_vol", True),
        ("Max drawdown", "max_drawdown", True),
        ("VaR (95%)", "var_95", True),
        ("Sharpe ratio", "sharpe", False),
        ("Sortino ratio", "sortino", False),
    ]
    labels = [m[0] for m in metrics]

    def _vals(src):
        out = []
        for _, key, is_pct in metrics:
            v = float(src.get(key) or 0.0)
            out.append(abs(v) * 100 if is_pct else v)
        return out

    current = _vals(current_metrics)
    proposed = _vals(proposed_metrics)

    x = np.arange(len(labels))
    w = 0.32
    bars1 = ax.bar(x - w/2, current, w, color="#8B95A2", edgecolor="white", linewidth=0.5, label="Current")
    bars2 = ax.bar(x + w/2, proposed, w, color="#0F8B6E", edgecolor="white", linewidth=0.5, label="Proposed")

    # Format by what the metric IS, not by its magnitude (a Sharpe of 1.2 is
    # a ratio, not 1.2%).
    for bars in [bars1, bars2]:
        for bar, (_, _, is_pct) in zip(bars, metrics):
            val = bar.get_height()
            fmt = f"{val:.1f}%" if is_pct else f"{val:.2f}"
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
    ax.set_title("Risk profile: current vs. proposed (volatility, drawdown and VaR shown as magnitudes)",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=10)
    ax.legend(fontsize=7.5, loc="upper right", framealpha=0.9, edgecolor="#DDE1E6")

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def make_scenario_impact(scenarios):
    """Butterfly chart: simulated current vs proposed median return per scenario."""
    fig, ax = plt.subplots(figsize=(6.8, 2.4))

    names = [s["name"] + (" (reference)" if s.get("is_base") else "") for s in scenarios]
    curr = [float(s["current_return_pct"]) for s in scenarios]
    prop = [float(s["proposed_return_pct"]) for s in scenarios]

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
    ax.set_title("Scenario stress test: simulated outcomes, current vs. proposed",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=10)
    ax.set_xlabel("Simulated median return vs base scenario (%)", fontsize=8, color="#5A6270")
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
        "trades": [{"ticker","action","shares" (int or None),"value",
                    "from_weight","to_weight"}],
        # Optional: only rendered when REAL simulated runs exist for BOTH
        # allocations; the section is omitted otherwise, never fabricated.
        "scenarios": [{"name","current_return_pct","proposed_return_pct","is_base"}],
        "rationale": str,
        "tax_considerations": str or None,
        # Optional AI narrative grounded in the numbers above.
        "narrative": {"proposal_summary","trade_commentary","considerations"},
    }
    """
    d = data
    narrative = d.get("narrative") or {}
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                            topMargin=60, bottomMargin=60, leftMargin=54, rightMargin=54)
    story = []

    cur_m = d["current_metrics"]
    prop_m = d["proposed_metrics"]
    vol_change_pp = (prop_m["annualized_vol"] - cur_m["annualized_vol"]) * 100
    sharpe_change = prop_m["sharpe"] - cur_m["sharpe"]

    def on_first(c, doc_obj):
        draw_cover_page(c, doc_obj,
            firm_name=d["firm_name"], client_name=d["client_name"],
            report_date=d["report_date"],
            report_type="REBALANCING PROPOSAL",
            subtitle=f"Prepared for review: {d['report_date'].strftime('%B %d, %Y')}",
            cover_metrics=[
                ("PORTFOLIO", f"${d['portfolio_value']:,.0f}"),
                ("VOL CHANGE", f"{vol_change_pp:+.1f}pp"),
                ("SHARPE CHANGE", f"{sharpe_change:+.2f}"),
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
    story.append(Paragraph(escape(d["rationale"]), s_body))
    story.append(Spacer(1, 6))

    # Callout states the COMPUTED effect, whatever its direction; it never
    # asserts an improvement the numbers do not show.
    facts_sentence = (
        f"<b>Computed impact:</b> Based on each allocation's own price history, this proposal "
        f"changes annualized volatility by {vol_change_pp:+.2f} percentage points "
        f"({cur_m['annualized_vol']*100:.1f}% to {prop_m['annualized_vol']*100:.1f}%) and moves "
        f"the Sharpe ratio from {cur_m['sharpe']:.2f} to {prop_m['sharpe']:.2f} "
        f"({sharpe_change:+.2f})."
    )
    if abs(vol_change_pp) < 0.005 and abs(sharpe_change) < 0.005:
        story.append(callout_box(
            facts_sentence + " On these measures the proposed allocation is essentially "
            "unchanged from the current one.",
            bg_color=AMBER_LIGHT, border_color=AMBER,
        ))
    elif vol_change_pp < 0 and sharpe_change > 0:
        story.append(callout_box(
            facts_sentence + " On these measures the proposal lowers risk while improving "
            "risk-adjusted return."
        ))
    elif vol_change_pp >= 0 and sharpe_change <= 0:
        story.append(callout_box(
            facts_sentence + " On these measures the proposal raises volatility without "
            "improving risk-adjusted return; the rationale above should justify that trade-off.",
            bg_color=RED_LIGHT, border_color=RED,
        ))
    elif vol_change_pp < 0:
        story.append(callout_box(
            facts_sentence + " The proposal lowers volatility but also lowers the Sharpe "
            "ratio: less risk, at some cost to risk-adjusted return.",
            bg_color=AMBER_LIGHT, border_color=AMBER,
        ))
    else:
        story.append(callout_box(
            facts_sentence + " The proposal improves the Sharpe ratio but raises volatility: "
            "better risk-adjusted return, with more day-to-day movement.",
            bg_color=AMBER_LIGHT, border_color=AMBER,
        ))
    story.append(Spacer(1, 8))

    if narrative.get("proposal_summary"):
        story.append(Paragraph("What the numbers show", s_subheading))
        story.append(Paragraph(escape(narrative["proposal_summary"]), s_body_sm))
        story.append(Spacer(1, 4))

    ba_buf = make_before_after_risk(cur_m, prop_m)
    story.append(Image(ba_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.38))

    story.append(PageBreak())

    # Page 3: Trades + optional scenario stress
    story.append(Paragraph("PROPOSED TRADES", s_section))
    story.append(Paragraph("What changes", s_heading))

    # Share counts only when a real last price was available; the column is
    # dropped entirely when no trade has one.
    has_shares = any(t.get("shares") is not None for t in d["trades"])
    if has_shares:
        t_data = [["Ticker", "Action", "Est. shares", "Value", "Current wt.", "Target wt."]]
        col_widths = [0.10, 0.14, 0.14, 0.20, 0.21, 0.21]
    else:
        t_data = [["Ticker", "Action", "Value", "Current wt.", "Target wt."]]
        col_widths = [0.12, 0.16, 0.24, 0.24, 0.24]
    for t in d["trades"]:
        row = [t["ticker"], t["action"]]
        if has_shares:
            row.append(f"{t['shares']:,.0f}" if t.get("shares") is not None else "n/a")
        row += [
            f"${t['value']:,.0f}",
            f"{t['from_weight']*100:.0f}%", f"{t['to_weight']*100:.0f}%",
        ]
        t_data.append(row)
    story.append(styled_table(t_data, col_widths))
    if has_shares:
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            "Share counts are estimates from each security's most recent available price and "
            "the stated portfolio value; actual execution quantities will differ with market "
            "prices at the time of trading. Where no recent price was available the count is "
            "shown as n/a.",
            s_disclaimer,
        ))
    if narrative.get("trade_commentary"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(escape(narrative["trade_commentary"]), s_body_sm))
    story.append(Spacer(1, 12))

    # Scenario stress: rendered only when BOTH allocations were actually
    # simulated under the same scenario set; omitted otherwise.
    scenarios = d.get("scenarios") or []
    if scenarios:
        story.append(Paragraph("SCENARIO STRESS TEST", s_section))
        story.append(Paragraph("Simulated outcomes for both allocations", s_subheading))
        story.append(Paragraph(
            "Both allocations were simulated under the same scenario set with the portfolio's "
            "MPS-copula Monte Carlo engine. Each figure is that allocation's median simulated "
            "return measured against its own base scenario. No scenario probabilities are "
            "estimated or shown.",
            s_body_sm
        ))
        sc_buf = make_scenario_impact(scenarios)
        story.append(Image(sc_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.35))
        story.append(Spacer(1, 6))

        sc_table = [["Scenario", "Current", "Proposed", "Difference"]]
        for s in scenarios:
            c = float(s["current_return_pct"])
            p = float(s["proposed_return_pct"])
            sc_table.append([
                s["name"] + (" (reference)" if s.get("is_base") else ""),
                f"{c:+.1f}%", f"{p:+.1f}%", f"{p - c:+.1f}pp",
            ])
        story.append(styled_table(sc_table, [0.40, 0.20, 0.20, 0.20]))
        story.append(Spacer(1, 10))

    # Tax considerations (advisor-supplied)
    if d.get("tax_considerations"):
        story.append(Paragraph("TAX CONSIDERATIONS", s_section))
        story.append(Paragraph(escape(d["tax_considerations"]), s_body))
        story.append(Spacer(1, 6))

    # Considerations: model-derived options for the advisor to evaluate,
    # replacing the old canned implementation plan.
    if narrative.get("considerations"):
        story.append(Paragraph("CONSIDERATIONS", s_section))
        story.append(Paragraph("Model-derived observations to evaluate", s_subheading))
        for c in narrative["considerations"]:
            story.append(Paragraph(f"•  {escape(c)}", s_body_sm))

    if any(narrative.get(k) for k in ("proposal_summary", "trade_commentary", "considerations")):
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Narrative commentary in this proposal was AI-generated strictly from the computed "
            "figures shown in this document. It is informational only, is not investment advice, "
            "and lists options for the advisor's professional evaluation, not instructions to "
            "transact.",
            s_disclaimer,
        ))

    story.extend(standard_disclaimer(d["firm_name"], d["advisor_name"]))

    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return output_path
