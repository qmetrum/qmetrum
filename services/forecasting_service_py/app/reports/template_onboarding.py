"""
Template 2: NEW CLIENT ONBOARDING REPORT
─────────────────────────────────────────
Purpose: First meeting with a new client. Shows their current portfolio's
risk profile vs. their stated risk tolerance. Highlights mismatches.
Maps to: /portfolio/analyze + /forecast/{ticker} endpoints.
"""

import numpy as np
from io import BytesIO
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image, Table, TableStyle
from reportlab.lib.enums import TA_CENTER

from app.reports.report_styles import *


def make_risk_tolerance_gauge(actual_vol, target_vol):
    """Visual gauge showing actual risk vs. client's stated tolerance."""
    fig, ax = plt.subplots(figsize=(6.8, 2.0))

    zones = [
        (0, 6,   "#E8F5EC", "Conservative"),
        (6, 12,  "#EAF2FB", "Moderate"),
        (12, 20, "#FDF5E6", "Growth"),
        (20, 35, "#FDECEC", "Aggressive"),
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

    ax.set_xlim(0, 35)
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

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def make_allocation_comparison(current, recommended):
    """Side-by-side horizontal bar chart: current vs. recommended allocation."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.8, 2.4), sharey=True)

    categories = list(current.keys())
    curr_vals = [current[c] * 100 for c in categories]
    rec_vals = [recommended[c] * 100 for c in categories]
    palette = ["#2B7ACC", "#0F8B6E", "#5A6270", "#D4920B", "#D85A30", "#7C5CBF"]

    for ax, vals, title, colors in [
        (ax1, curr_vals, "Current allocation", ["#8B95A2"] * len(categories)),
        (ax2, rec_vals, "Recommended allocation", palette[:len(categories)]),
    ]:
        bars = ax.barh(categories, vals, color=colors, height=0.55, edgecolor="white", linewidth=0.5)
        ax.set_title(title, fontsize=9, fontweight="600", color="#1A1A2E", loc="left")
        ax.set_xlim(0, 55)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#DDE1E6")
        ax.spines["bottom"].set_color("#DDE1E6")
        ax.tick_params(colors="#5A6270", labelsize=7.5)
        ax.grid(axis="x", color="#EEF0F3", linewidth=0.6)
        ax.set_axisbelow(True)
        for bar, val in zip(bars, vals):
            ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                    f"{val:.0f}%", va="center", fontsize=7.5, color="#1A1A2E")

    ax1.invert_yaxis()
    fig.tight_layout(w_pad=3)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_onboarding_report(output_path, data):
    """
    data = {
        "client_name": str,
        "advisor_name": str,
        "firm_name": str,
        "report_date": datetime,
        "portfolio_value": float,
        "risk_tolerance": str,          # "Moderate", "Growth", etc.
        "target_vol": float,            # e.g. 0.10
        "actual_vol": float,            # from engine
        "sharpe": float,
        "max_drawdown": float,
        "holdings": [{"ticker","name","sector","weight","value"}],
        "current_allocation": {"US Equity": 0.4, ...},
        "recommended_allocation": {"US Equity": 0.35, ...},
        "risk_findings": [str, str, ...],   # bullet points from analysis
        "next_steps": [str, str, ...],
    }
    """
    d = data
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                            topMargin=60, bottomMargin=60, leftMargin=54, rightMargin=54)
    story = []

    # Cover
    def on_first(c, doc):
        draw_cover_page(c, doc,
            firm_name=d["firm_name"], client_name=d["client_name"],
            report_date=d["report_date"],
            report_type="NEW CLIENT RISK ASSESSMENT",
            subtitle=f"Onboarding analysis — {d['report_date'].strftime('%B %d, %Y')}",
            cover_metrics=[
                ("PORTFOLIO VALUE", f"${d['portfolio_value']:,.0f}"),
                ("RISK TOLERANCE", d["risk_tolerance"]),
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
        f"Based on your stated risk tolerance of <b>{d['risk_tolerance']}</b>, we would expect "
        f"your portfolio to have an annualized volatility near <b>{d['target_vol']*100:.0f}%</b>. "
        f"Your current portfolio shows a volatility of <b>{d['actual_vol']*100:.1f}%</b>. "
        f"The gauge below shows where you stand.",
        s_body))

    gauge_buf = make_risk_tolerance_gauge(d["actual_vol"] * 100, d["target_vol"] * 100)
    story.append(Image(gauge_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.29))
    story.append(Spacer(1, 6))

    # Risk mismatch callout
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

    story.append(Spacer(1, 10))

    # Key findings
    story.append(Paragraph("KEY FINDINGS", s_section))
    story.append(Paragraph("What we found in your portfolio", s_subheading))
    for i, finding in enumerate(d.get("risk_findings", []), 1):
        story.append(Paragraph(f"<b>{i}.</b>  {finding}", s_body))

    story.append(PageBreak())

    # Page 3: Allocation Comparison
    story.append(Paragraph("ALLOCATION ANALYSIS", s_section))
    story.append(Paragraph("Current vs. recommended allocation", s_heading))

    alloc_buf = make_allocation_comparison(d["current_allocation"], d["recommended_allocation"])
    story.append(Image(alloc_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.35))
    story.append(Spacer(1, 8))

    # Holdings table
    story.append(Paragraph("Current holdings", s_subheading))
    h_data = [["Ticker", "Name", "Sector", "Weight", "Value"]]
    for h in d["holdings"]:
        h_data.append([h["ticker"], h["name"], h["sector"],
                       f"{h['weight']*100:.0f}%", f"${h['value']:,.0f}"])

    story.append(styled_table(h_data, [0.10, 0.32, 0.20, 0.14, 0.24]))
    story.append(Spacer(1, 14))

    # Next steps
    story.append(Paragraph("RECOMMENDED NEXT STEPS", s_section))
    story.append(Paragraph("Action plan", s_subheading))
    for i, step in enumerate(d.get("next_steps", []), 1):
        story.append(Paragraph(f"<b>{i}.</b>  {step}", s_body))

    # Disclaimer
    story.extend(standard_disclaimer(d["firm_name"], d["advisor_name"]))

    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return output_path


# ── DEMO ──
if __name__ == "__main__":
    demo = {
        "client_name": "David & Maria Chen",
        "advisor_name": "Sarah Mitchell, CFA",
        "firm_name": "Meridian Wealth Advisors",
        "report_date": datetime(2026, 3, 16),
        "portfolio_value": 1_850_000,
        "risk_tolerance": "Moderate",
        "target_vol": 0.10,
        "actual_vol": 0.145,
        "sharpe": 0.68,
        "max_drawdown": -0.182,
        "holdings": [
            {"ticker": "QQQ",  "name": "Invesco QQQ Trust",       "sector": "US Equity",    "weight": 0.40, "value": 740000},
            {"ticker": "AAPL", "name": "Apple Inc.",               "sector": "US Equity",    "weight": 0.15, "value": 277500},
            {"ticker": "TSLA", "name": "Tesla Inc.",               "sector": "US Equity",    "weight": 0.10, "value": 185000},
            {"ticker": "BND",  "name": "Vanguard Total Bond",     "sector": "Fixed Income", "weight": 0.20, "value": 370000},
            {"ticker": "VNQ",  "name": "Vanguard Real Estate",    "sector": "Real Estate",  "weight": 0.15, "value": 277500},
        ],
        "current_allocation": {
            "US Equity": 0.65, "Fixed Income": 0.20, "Real Estate": 0.15,
            "Intl Equity": 0.0, "Commodities": 0.0,
        },
        "recommended_allocation": {
            "US Equity": 0.35, "Fixed Income": 0.30, "Real Estate": 0.10,
            "Intl Equity": 0.15, "Commodities": 0.10,
        },
        "risk_findings": [
            "Portfolio is <b>45% more volatile</b> than your target due to concentration in tech equities (QQQ + AAPL + TSLA = 65%).",
            "Single-stock risk: AAPL and TSLA together represent 25% of assets, creating significant idiosyncratic exposure.",
            "No international diversification — 0% allocation to non-US markets vs. a recommended 15%.",
            "Fixed income allocation (20%) is below the 30% recommended for a moderate risk profile.",
            "Real estate at 15% is appropriate and provides inflation protection.",
        ],
        "next_steps": [
            "Reduce single-stock concentration by trimming AAPL and TSLA to a combined 8% maximum.",
            "Add international equity exposure (VXUS or similar) at 15% target weight.",
            "Increase bond allocation from 20% to 30% using intermediate-term core bonds.",
            "Add commodity/inflation hedge (GLD, VTIP) at 10% for tail-risk protection.",
            "Schedule 60-day follow-up to review transition progress and rerun risk analysis.",
        ],
    }
    generate_onboarding_report("/home/claude/reports/onboarding_report.pdf", demo)
    print("Onboarding report generated.")
