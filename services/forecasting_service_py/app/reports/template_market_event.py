"""
Template 3: MARKET EVENT REPORT
────────────────────────────────
Purpose: Sent to clients during market turbulence (sell-offs, rate decisions,
geopolitical events). Calms nerves with data. Shows portfolio impact vs. benchmark.
Maps to: /forecast/{ticker} + /portfolio/analyze + /quantum-risk/portfolio
"""

import numpy as np
from io import BytesIO
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image

from app.reports.report_styles import *


def make_event_impact_chart(dates, portfolio_vals, benchmark_vals, event_date, event_name):
    fig, ax = plt.subplots(figsize=(6.8, 2.8))

    ax.plot(dates, portfolio_vals, color="#0F8B6E", linewidth=1.5, label="Your portfolio")
    ax.plot(dates, benchmark_vals, color="#8B95A2", linewidth=1.2, linestyle="--", label="S&P 500")

    ax.axvline(event_date, color="#D85A30", linewidth=1.2, linestyle="-", alpha=0.8)
    ax.annotate(f" {event_name}", (event_date, max(portfolio_vals) * 0.99),
                fontsize=7.5, color="#D85A30", fontweight="600", va="top")

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDE1E6")
    ax.spines["bottom"].set_color("#DDE1E6")
    ax.tick_params(colors="#5A6270", labelsize=7.5)
    ax.grid(axis="y", color="#EEF0F3", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title("Portfolio performance through the event window",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=10)
    ax.set_ylabel("Indexed (100 = start)", fontsize=8, color="#5A6270")
    ax.legend(fontsize=7, loc="lower left", framealpha=0.9, edgecolor="#DDE1E6")
    fig.autofmt_xdate()
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %d"))

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def make_drawdown_comparison(portfolio_dd, benchmark_dd, dates):
    fig, ax = plt.subplots(figsize=(6.8, 1.8))

    ax.fill_between(dates, portfolio_dd, 0, color="#0F8B6E", alpha=0.15, label="Your portfolio")
    ax.plot(dates, portfolio_dd, color="#0F8B6E", linewidth=1.0)
    ax.fill_between(dates, benchmark_dd, 0, color="#C0392B", alpha=0.08, label="S&P 500")
    ax.plot(dates, benchmark_dd, color="#C0392B", linewidth=0.8, linestyle="--")

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDE1E6")
    ax.spines["bottom"].set_color("#DDE1E6")
    ax.tick_params(colors="#5A6270", labelsize=7.5)
    ax.grid(axis="y", color="#EEF0F3", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title("Drawdown comparison",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=8)
    ax.set_ylabel("Drawdown (%)", fontsize=8, color="#5A6270")
    ax.legend(fontsize=7, loc="lower left", framealpha=0.9, edgecolor="#DDE1E6")
    fig.autofmt_xdate()
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %d"))

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_market_event_report(output_path, data):
    """
    data = {
        "client_name", "advisor_name", "firm_name", "report_date",
        "portfolio_value", "event_name", "event_date",
        "event_summary": str,
        "portfolio_return_event": float,     # e.g. -0.032
        "benchmark_return_event": float,     # e.g. -0.058
        "portfolio_drawdown_peak": float,
        "regime": str,
        "fragility_score": float,
        "var_95": float,
        "holdings_impact": [{"ticker","name","return","contribution"}],
        "forward_outlook": str,
        "action_items": [str, ...],
        # Time series (30-day window around event)
        "dates": [datetime],
        "portfolio_index": [float],
        "benchmark_index": [float],
        "portfolio_dd": [float],
        "benchmark_dd": [float],
    }
    """
    d = data
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                            topMargin=60, bottomMargin=60, leftMargin=54, rightMargin=54)
    story = []

    port_ret_str = f"{d['portfolio_return_event']*100:+.1f}%"
    bench_ret_str = f"{d['benchmark_return_event']*100:+.1f}%"

    def on_first(c, doc_obj):
        draw_cover_page(c, doc_obj,
            firm_name=d["firm_name"], client_name=d["client_name"],
            report_date=d["report_date"],
            report_type="MARKET EVENT BRIEFING",
            subtitle=f"{d['event_name']} — {d['event_date'].strftime('%B %d, %Y')}",
            cover_metrics=[
                ("EVENT IMPACT", port_ret_str),
                ("BENCHMARK", bench_ret_str),
                ("REGIME", d["regime"]),
                ("FRAGILITY", f"{d['fragility_score']:.2f}"),
            ])

    def on_later(c, doc_obj):
        draw_header_footer(c, doc_obj, firm_name=d["firm_name"], client_name=d["client_name"],
                           report_date=d["report_date"], advisor_name=d["advisor_name"])

    story.append(Spacer(1, 1))
    story.append(PageBreak())

    # Page 2: Event Summary
    story.append(Paragraph("EVENT SUMMARY", s_section))
    story.append(Paragraph(d["event_name"], s_heading))
    story.append(Paragraph(d["event_summary"], s_body))
    story.append(Spacer(1, 4))

    # Headline metrics
    outperformance = d["portfolio_return_event"] - d["benchmark_return_event"]
    story.append(metrics_row([
        metric_card(port_ret_str, "Your portfolio", TEAL if d["portfolio_return_event"] > d["benchmark_return_event"] else CORAL),
        metric_card(bench_ret_str, "S&P 500 benchmark", SLATE),
        metric_card(f"{outperformance*100:+.1f}%", "Relative performance",
                    GREEN if outperformance > 0 else RED),
        metric_card(d["regime"], "Current regime", AMBER if d["regime"] != "Normal" else TEAL),
    ]))
    story.append(Spacer(1, 8))

    # Reassurance callout
    if outperformance > 0:
        story.append(callout_box(
            f"<b>Your portfolio outperformed the benchmark by "
            f"{abs(outperformance)*100:.1f} percentage points</b> during this event. "
            f"Diversification across asset classes cushioned the impact as designed.",
        ))
    else:
        story.append(callout_box(
            f"<b>Your portfolio underperformed the benchmark by "
            f"{abs(outperformance)*100:.1f} percentage points.</b> "
            f"We are monitoring the situation and will recommend adjustments if the regime persists.",
            bg_color=AMBER_LIGHT, border_color=AMBER,
        ))

    story.append(Spacer(1, 8))

    # Event impact chart
    story.append(Paragraph("EVENT WINDOW", s_section))
    story.append(Paragraph("30-day performance through the event", s_subheading))
    impact_buf = make_event_impact_chart(
        d["dates"], d["portfolio_index"], d["benchmark_index"],
        d["event_date"], d["event_name"])
    story.append(Image(impact_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.41))

    story.append(PageBreak())

    # Page 3: Detailed impact
    story.append(Paragraph("DRAWDOWN ANALYSIS", s_section))
    story.append(Paragraph("How deep did it go?", s_heading))
    dd_buf = make_drawdown_comparison(d["portfolio_dd"], d["benchmark_dd"], d["dates"])
    story.append(Image(dd_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.26))
    story.append(Spacer(1, 10))

    # Holdings impact table
    story.append(Paragraph("HOLDINGS IMPACT", s_section))
    story.append(Paragraph("Contribution by position", s_subheading))
    hi_data = [["Ticker", "Name", "Position return", "Portfolio contribution"]]
    for h in d["holdings_impact"]:
        hi_data.append([
            h["ticker"], h["name"],
            f"{h['return']*100:+.1f}%",
            f"{h['contribution']*100:+.2f}%",
        ])
    story.append(styled_table(hi_data, [0.12, 0.40, 0.24, 0.24]))
    story.append(Spacer(1, 12))

    # Forward outlook
    story.append(Paragraph("FORWARD OUTLOOK", s_section))
    story.append(Paragraph("What we expect from here", s_subheading))
    story.append(Paragraph(d["forward_outlook"], s_body))
    story.append(Spacer(1, 6))

    # Action items
    story.append(Paragraph("ACTION ITEMS", s_section))
    for i, item in enumerate(d.get("action_items", []), 1):
        story.append(Paragraph(f"<b>{i}.</b>  {item}", s_body))

    story.extend(standard_disclaimer(d["firm_name"], d["advisor_name"]))

    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return output_path


# ── DEMO ──
if __name__ == "__main__":
    np.random.seed(99)
    event_date = datetime(2026, 3, 10)
    dates = [event_date - timedelta(days=15) + timedelta(days=i) for i in range(30)]
    port_ret = np.random.normal(-0.001, 0.009, 30)
    port_ret[14:18] = [-0.018, -0.012, -0.005, 0.008]  # shock + recovery
    bench_ret = np.random.normal(-0.0015, 0.012, 30)
    bench_ret[14:18] = [-0.028, -0.018, -0.010, 0.005]
    port_idx = 100 * np.cumprod(1 + port_ret)
    bench_idx = 100 * np.cumprod(1 + bench_ret)
    port_dd = ((port_idx / np.maximum.accumulate(port_idx)) - 1) * 100
    bench_dd = ((bench_idx / np.maximum.accumulate(bench_idx)) - 1) * 100

    demo = {
        "client_name": "Richardson Family Trust",
        "advisor_name": "Sarah Mitchell, CFA",
        "firm_name": "Meridian Wealth Advisors",
        "report_date": datetime(2026, 3, 16),
        "portfolio_value": 2_450_000,
        "event_name": "Fed Rate Decision Shock",
        "event_date": event_date,
        "event_summary":
            "On March 10, the Federal Reserve surprised markets with a 50bps rate hike, "
            "contrary to the widely expected 25bps move. Equity markets sold off sharply, "
            "with the S&P 500 declining 5.8% over two trading sessions. Bond yields spiked, "
            "with the 10-year reaching 4.85%. The VIX jumped from 16 to 28.",
        "portfolio_return_event": -0.032,
        "benchmark_return_event": -0.058,
        "portfolio_drawdown_peak": -0.041,
        "regime": "High_Fragility",
        "fragility_score": 1.72,
        "var_95": -0.0245,
        "holdings_impact": [
            {"ticker": "VTI",  "name": "Vanguard Total Stock",  "return": -0.055, "contribution": -0.0193},
            {"ticker": "VXUS", "name": "Vanguard Intl Stock",   "return": -0.038, "contribution": -0.0057},
            {"ticker": "BND",  "name": "Vanguard Total Bond",   "return": -0.015, "contribution": -0.0038},
            {"ticker": "VNQ",  "name": "Vanguard Real Estate",  "return": -0.042, "contribution": -0.0042},
            {"ticker": "GLD",  "name": "SPDR Gold Shares",      "return":  0.022, "contribution":  0.0018},
            {"ticker": "VTIP", "name": "Vanguard TIPS",         "return":  0.008, "contribution":  0.0006},
        ],
        "forward_outlook":
            "The GARCH model now classifies the regime as <b>High Fragility</b> (score 1.72), "
            "indicating volatility is significantly above its long-term median. Historically, "
            "this regime persists for 15-25 trading days before mean-reverting. Our ensemble model "
            "projects a gradual recovery with a median 90-day return of +3.2%, though the confidence "
            "band remains wide (−4.1% to +11.8%) reflecting elevated uncertainty.",
        "action_items": [
            "No changes recommended at this time — portfolio performed as designed.",
            "Monitor fragility score daily. If it exceeds 2.0 for 5+ consecutive sessions, "
            "we will recommend reducing equity exposure by 5%.",
            "Gold and TIPS allocations provided positive returns during the sell-off, "
            "confirming their role as portfolio stabilizers.",
            "Schedule call by March 20 to review updated projections.",
        ],
        "dates": dates,
        "portfolio_index": port_idx.tolist(),
        "benchmark_index": bench_idx.tolist(),
        "portfolio_dd": port_dd.tolist(),
        "benchmark_dd": bench_dd.tolist(),
    }
    generate_market_event_report("/home/claude/reports/market_event_report.pdf", demo)
    print("Market event report generated.")
