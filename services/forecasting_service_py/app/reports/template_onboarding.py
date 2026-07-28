"""
Template 2: NEW CLIENT ONBOARDING REPORT
Purpose: First meeting with a new client. Shows the current portfolio's
MEASURED risk profile vs. the client's stated risk tolerance and target
volatility, the allocation as it stands today (no invented "recommended"
allocation), and an AI narrative grounded only in the computed numbers.
Maps to: /reports/onboarding.
"""

from io import BytesIO
from xml.sax.saxutils import escape

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image

from app.reports.report_styles import *


def _fig_to_image(fig, dpi=180):
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def make_risk_tolerance_gauge(actual_vol, target_vol):
    """Visual gauge showing actual risk vs. the client's stated target.

    The axis extends to cover both markers (the old chart hard-capped at 35%,
    so a higher actual volatility plotted off-chart)."""
    fig, ax = plt.subplots(figsize=(6.8, 2.0))

    x_max = max(35.0, float(actual_vol) * 1.15, float(target_vol) * 1.15)
    zones = [
        (0, 6,     "#E8F5EC", "Conservative"),
        (6, 12,    "#EAF2FB", "Moderate"),
        (12, 20,   "#FDF5E6", "Growth"),
        (20, x_max, "#FDECEC", "Aggressive"),
    ]
    for lo, hi, color, label in zones:
        ax.barh(0, hi - lo, left=lo, height=0.6, color=color, edgecolor="#DDE1E6", linewidth=0.5)
        ax.text((lo + hi) / 2, 0, label, ha="center", va="center", fontsize=7.5,
                color="#5A6270", fontweight="500")

    # Target marker
    ax.plot(target_vol, 0, marker="D", markersize=10, color="#2B7ACC", zorder=5)
    ax.annotate("Target", (target_vol, 0), textcoords="offset points",
                xytext=(0, 22), ha="center", fontsize=7.5, color="#2B7ACC", fontweight="600",
                arrowprops=dict(arrowstyle="-", color="#2B7ACC", lw=0.8))

    # Actual marker
    ax.plot(actual_vol, 0, marker="o", markersize=12, color="#D85A30", zorder=6,
            markeredgecolor="white", markeredgewidth=1.5)
    ax.annotate("Actual", (actual_vol, 0), textcoords="offset points",
                xytext=(0, -24), ha="center", fontsize=7.5, color="#D85A30", fontweight="600",
                arrowprops=dict(arrowstyle="-", color="#D85A30", lw=0.8))

    ax.set_xlim(0, x_max)
    ax.set_ylim(-0.8, 0.8)
    ax.set_xlabel("Annualized volatility (%)", fontsize=8, color="#5A6270")
    ax.set_title("Risk alignment: stated tolerance vs. portfolio reality",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=10)
    ax.set_yticks([])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color("#DDE1E6")
    ax.tick_params(colors="#5A6270", labelsize=7.5)

    return _fig_to_image(fig)


def make_allocation_chart(allocation):
    """Horizontal bar chart of the CURRENT allocation by asset type.

    The x-axis is sized to the largest weight plus label headroom, so any
    weight renders fully with its value label visible (the old side-by-side
    chart clipped bars above 55% and also drew a fabricated "recommended"
    allocation that was a copy of the current one)."""
    fig, ax = plt.subplots(figsize=(6.8, 2.2))

    items = sorted(allocation.items(), key=lambda kv: -float(kv[1]))
    categories = [str(k) for k, _ in items]
    vals = [float(v) * 100 for _, v in items]
    palette = ["#2B7ACC", "#0F8B6E", "#5A6270", "#D4920B", "#D85A30", "#7C5CBF"]
    colors = [palette[i % len(palette)] for i in range(len(categories))]

    bars = ax.barh(categories, vals, color=colors, height=0.55,
                   edgecolor="white", linewidth=0.5)
    x_max = max(vals) if vals else 0.0
    ax.set_xlim(0, max(x_max * 1.18 + 2.0, 10.0))
    ax.set_title("Current allocation by asset type", fontsize=10, fontweight="600",
                 color="#1A1A2E", loc="left", pad=10)
    ax.set_xlabel("Weight (%)", fontsize=8, color="#5A6270")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDE1E6")
    ax.spines["bottom"].set_color("#DDE1E6")
    ax.tick_params(colors="#5A6270", labelsize=7.5)
    ax.grid(axis="x", color="#EEF0F3", linewidth=0.6)
    ax.set_axisbelow(True)
    for bar, val in zip(bars, vals):
        ax.text(bar.get_width() + max(x_max * 0.015, 0.4),
                bar.get_y() + bar.get_height() / 2,
                f"{val:.0f}%", va="center", fontsize=7.5, color="#1A1A2E")

    ax.invert_yaxis()
    return _fig_to_image(fig)


def generate_onboarding_report(output_path, data):
    """
    data = {
        "client_name": str,
        "advisor_name": str,
        "firm_name": str,
        "report_date": datetime,
        "portfolio_value": float,
        "risk_tolerance": str,          # the client's STATED tolerance
        "target_vol": float,            # the client's stated target, e.g. 0.10
        "actual_vol": float,            # measured, from engine
        "sharpe": float,
        "max_drawdown": float,
        "holdings": [{"ticker","name","asset_type","weight","value"}],
        "current_allocation": {"Equity": 0.65, ...},   # by asset type
        # Component risk decomposition: which holding drives portfolio RISK
        # (share of volatility vs weight). None when unavailable; omitted then.
        "risk_attribution": {"portfolio_vol", "n_obs",
                             "rows": [{"ticker","weight","risk_pct"}]} | None,
        "risk_findings": [str, ...],    # computed sentences from the router
        # Optional AI narrative grounded only in the numbers above.
        "narrative": {"risk_profile_summary","what_to_watch","considerations"},
    }
    """
    d = data
    narrative = d.get("narrative") or {}
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                            topMargin=60, bottomMargin=60, leftMargin=54, rightMargin=54)
    story = []

    # Cover
    def on_first(c, doc):
        draw_cover_page(c, doc,
            firm_name=d["firm_name"], client_name=d["client_name"],
            report_date=d["report_date"],
            report_type="NEW CLIENT RISK ASSESSMENT",
            subtitle=f"Onboarding analysis: {d['report_date'].strftime('%B %d, %Y')}",
            cover_metrics=[
                ("PORTFOLIO VALUE", f"${d['portfolio_value']:,.0f}"),
                ("RISK TOLERANCE", str(d["risk_tolerance"])),
                ("ACTUAL VOLATILITY", f"{d['actual_vol']*100:.1f}%"),
                ("MAX DRAWDOWN", f"{d['max_drawdown']*100:.1f}%"),
            ])

    def on_later(c, doc):
        draw_header_footer(c, doc, firm_name=d["firm_name"], client_name=d["client_name"],
                           report_date=d["report_date"], advisor_name=d["advisor_name"])

    story.append(Spacer(1, 1))
    story.append(PageBreak())

    # Page 2: Risk Alignment
    story.append(Paragraph("RISK ALIGNMENT", s_section))
    story.append(Paragraph("Does your portfolio match your goals?", s_heading))
    story.append(Paragraph(
        f"Your stated risk tolerance is <b>{escape(str(d['risk_tolerance']))}</b> with a target "
        f"annualized volatility of <b>{d['target_vol']*100:.0f}%</b>. Measured from its own "
        f"price history, your current portfolio shows a volatility of "
        f"<b>{d['actual_vol']*100:.1f}%</b>. The gauge below shows where you stand.",
        s_body))

    gauge_buf = make_risk_tolerance_gauge(d["actual_vol"] * 100, d["target_vol"] * 100)
    story.append(Image(gauge_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.29))
    story.append(Spacer(1, 6))

    # Risk mismatch callout (computed: actual vs stated target)
    mismatch = d["actual_vol"] - d["target_vol"]
    if abs(mismatch) > 0.02:
        direction = "more" if mismatch > 0 else "less"
        story.append(callout_box(
            f"<b>Risk mismatch detected:</b> Your portfolio is {abs(mismatch)*100:.1f}% "
            f"{direction} volatile than your target. This means your portfolio is taking "
            f"{'more risk than you may be comfortable with' if mismatch > 0 else 'less risk than needed to meet your growth goals'}.",
            bg_color=AMBER_LIGHT if mismatch > 0 else BLUE_LIGHT,
            border_color=AMBER if mismatch > 0 else BLUE,
        ))
    else:
        story.append(callout_box(
            "<b>Good alignment:</b> Your portfolio risk is well-matched to your stated tolerance.",
        ))

    story.append(Spacer(1, 8))
    story.append(metrics_row([
        metric_card(f"{d['actual_vol']*100:.1f}%", "Actual volatility", CORAL),
        metric_card(f"{d['target_vol']*100:.0f}%", "Target volatility", BLUE),
        metric_card(f"{d['sharpe']:.2f}", "Sharpe ratio", TEAL),
        metric_card(f"{d['max_drawdown']*100:.1f}%", "Max drawdown"),
    ]))
    story.append(Spacer(1, 10))

    if narrative.get("risk_profile_summary"):
        story.append(Paragraph("Your risk profile in plain terms", s_subheading))
        story.append(Paragraph(escape(narrative["risk_profile_summary"]), s_body_sm))
        story.append(Spacer(1, 6))

    # Key findings (computed by the router from the measured metrics)
    story.append(Paragraph("KEY FINDINGS", s_section))
    story.append(Paragraph("What we found in your portfolio", s_subheading))
    for i, finding in enumerate(d.get("risk_findings", []), 1):
        story.append(Paragraph(f"<b>{i}.</b>  {finding}", s_body))

    story.append(PageBreak())

    # Page 3: Current allocation (as it stands; no invented recommendation)
    story.append(Paragraph("CURRENT ALLOCATION", s_section))
    story.append(Paragraph("How the portfolio is invested today", s_heading))
    story.append(Paragraph(
        "The chart below shows the portfolio as it currently stands, grouped by asset type. "
        "This report does not include a model-generated target allocation; any reallocation "
        "would be developed and agreed with your advisor.",
        s_body))

    if d.get("current_allocation"):
        alloc_buf = make_allocation_chart(d["current_allocation"])
        story.append(Image(alloc_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.32))
        story.append(Spacer(1, 8))

    # Holdings table
    story.append(Paragraph("Current holdings", s_subheading))
    h_data = [["Ticker", "Name", "Type", "Weight", "Value"]]
    for h in d["holdings"]:
        h_data.append([h["ticker"], h["name"], h.get("asset_type", "Equity"),
                       f"{h['weight']*100:.0f}%", f"${h['value']:,.0f}"])

    story.append(styled_table(h_data, [0.10, 0.32, 0.20, 0.14, 0.24]))
    story.append(Spacer(1, 14))

    # Risk concentration: which holding actually drives the portfolio's RISK
    # (share of volatility), which can diverge sharply from its weight. For a
    # new client this is the core concentration question, so it is a computed
    # decomposition rather than an assertion. Omitted when the router could not
    # compute it (fewer than two holdings or too little aligned price history).
    ra = d.get("risk_attribution") or {}
    if ra.get("rows"):
        story.append(Paragraph("RISK CONCENTRATION", s_section))
        story.append(Paragraph("Which holding drives the portfolio's risk", s_heading))
        story.append(Paragraph(
            "Weight is how much money sits in each holding. Share of risk is how much "
            "of the portfolio's volatility each holding actually drives, computed from "
            "the real return covariance. When a holding's share of risk runs well above "
            "its weight, that position is concentrating risk out of proportion to its "
            "size, which is often the first thing worth discussing with a new client.",
            s_body))
        rc_rows = [["Holding", "Weight", "Share of risk"]]
        for r in ra["rows"]:
            rc_rows.append([r["ticker"], f"{r['weight'] * 100:.0f}%",
                            f"{r['risk_pct'] * 100:.0f}%"])
        story.append(styled_table(rc_rows, [0.44, 0.28, 0.28]))
        story.append(Paragraph(
            f"Share of the portfolio's {ra['portfolio_vol'] * 100:.1f}% annualized volatility "
            f"attributable to each holding ({ra.get('n_obs', 0)} observations). A holding's "
            f"risk share can exceed its weight when it is more volatile or more correlated "
            f"with the rest of the book.",
            s_disclaimer))
        story.append(Spacer(1, 14))

    # AI narrative: what to watch + options to evaluate (replaces the old
    # canned "recommended next steps" boilerplate; omitted when unavailable).
    if narrative.get("what_to_watch"):
        story.append(Paragraph("WHAT TO WATCH", s_section))
        story.append(Paragraph("Numbers worth monitoring as we start", s_subheading))
        story.append(Paragraph(escape(narrative["what_to_watch"]), s_body_sm))
        story.append(Spacer(1, 8))

    if narrative.get("considerations"):
        story.append(Paragraph("CONSIDERATIONS", s_section))
        story.append(Paragraph("Model-derived observations to evaluate", s_subheading))
        for c in narrative["considerations"]:
            story.append(Paragraph(f"•  {escape(c)}", s_body_sm))

    if any(narrative.get(k) for k in ("risk_profile_summary", "what_to_watch", "considerations")):
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Narrative commentary in this assessment was AI-generated strictly from the "
            "computed figures shown in this document. It is informational only, is not "
            "investment advice, and lists options for the advisor's professional evaluation, "
            "not instructions to transact.",
            s_disclaimer,
        ))

    # Disclaimer
    story.extend(standard_disclaimer(d["firm_name"], d["advisor_name"]))

    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return output_path
