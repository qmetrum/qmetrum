"""
Template 5: YEAR-END PORTFOLIO REVIEW
──────────────────────────────────────
Purpose: Annual review showing full-year performance, risk evolution,
model accuracy, and planning for the year ahead.
Maps to: /portfolio/analyze + historical forecast cache + /screener/run
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


def make_annual_performance(months, port_cumulative, bench_cumulative):
    fig, ax = plt.subplots(figsize=(6.8, 2.8))

    ax.plot(months, port_cumulative, color="#0F8B6E", linewidth=1.8, label="Your portfolio")
    ax.plot(months, bench_cumulative, color="#8B95A2", linewidth=1.2, linestyle="--", label="S&P 500")
    ax.fill_between(months, port_cumulative, bench_cumulative,
                    where=[p > b for p, b in zip(port_cumulative, bench_cumulative)],
                    color="#0F8B6E", alpha=0.08)
    ax.fill_between(months, port_cumulative, bench_cumulative,
                    where=[p <= b for p, b in zip(port_cumulative, bench_cumulative)],
                    color="#D85A30", alpha=0.08)

    ax.axhline(0, color="#8B95A2", linewidth=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDE1E6")
    ax.spines["bottom"].set_color("#DDE1E6")
    ax.tick_params(colors="#5A6270", labelsize=7.5)
    ax.grid(axis="y", color="#EEF0F3", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title("Cumulative return: full year",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=10)
    ax.set_ylabel("Return (%)", fontsize=8, color="#5A6270")
    ax.legend(fontsize=7, loc="upper left", framealpha=0.9, edgecolor="#DDE1E6")

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def make_monthly_returns_heatmap(monthly_returns):
    fig, ax = plt.subplots(figsize=(6.8, 1.6))

    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    vals = np.array(monthly_returns) * 100
    colors = ["#1B8553" if v > 0 else "#C0392B" for v in vals]

    bars = ax.bar(months, vals, color=colors, edgecolor="white", linewidth=0.5, width=0.65)
    for bar, val in zip(bars, vals):
        y_pos = bar.get_height() + (0.15 if val >= 0 else -0.4)
        ax.text(bar.get_x() + bar.get_width()/2, y_pos, f"{val:+.1f}%",
                ha="center", va="bottom" if val >= 0 else "top",
                fontsize=7, color="#1A1A2E", fontweight="500")

    ax.axhline(0, color="#8B95A2", linewidth=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDE1E6")
    ax.spines["bottom"].set_color("#DDE1E6")
    ax.tick_params(colors="#5A6270", labelsize=7.5)
    ax.grid(axis="y", color="#EEF0F3", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title("Monthly portfolio returns",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=8)

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def make_risk_evolution(months_labels, vol_series, fragility_series):
    fig, ax1 = plt.subplots(figsize=(6.8, 2.2))

    ax1.plot(months_labels, vol_series, color="#2B7ACC", linewidth=1.3, label="Annualized vol (%)")
    ax1.fill_between(months_labels, vol_series, alpha=0.06, color="#2B7ACC")
    ax1.set_ylabel("Volatility (%)", fontsize=8, color="#2B7ACC")
    ax1.tick_params(axis="y", colors="#2B7ACC", labelsize=7.5)

    ax2 = ax1.twinx()
    ax2.plot(months_labels, fragility_series, color="#D4920B", linewidth=1.3,
             linestyle="--", label="Fragility score")
    ax2.axhline(1.5, color="#D85A30", linewidth=0.6, linestyle=":", alpha=0.6)
    ax2.text(months_labels[-1], 1.55, " Fragile threshold", fontsize=6.5, color="#D85A30", va="bottom")
    ax2.set_ylabel("Fragility score", fontsize=8, color="#D4920B")
    ax2.tick_params(axis="y", colors="#D4920B", labelsize=7.5)

    ax1.spines["top"].set_visible(False)
    ax2.spines["top"].set_visible(False)
    ax1.spines["bottom"].set_color("#DDE1E6")
    ax1.tick_params(axis="x", colors="#5A6270", labelsize=7.5)
    ax1.grid(axis="y", color="#EEF0F3", linewidth=0.6)
    ax1.set_axisbelow(True)
    ax1.set_title("Risk regime evolution: full year",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=10)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=7,
               loc="upper right", framealpha=0.9, edgecolor="#DDE1E6")

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_yearend_report(output_path, data):
    """
    data = {
        "client_name", "advisor_name", "firm_name", "report_date",
        "review_year": int,
        "portfolio_value_start": float,
        "portfolio_value_end": float,
        "portfolio_return_ytd": float,
        "benchmark_return_ytd": float,
        "sharpe", "sortino", "max_drawdown", "annualized_vol",
        "months": [str],  # ["Jan","Feb",...]
        "portfolio_cumulative": [float],   # cumulative % return per month
        "benchmark_cumulative": [float],
        "monthly_returns": [float],  # 12 values
        "vol_series": [float],       # 12 monthly avg vol
        "fragility_series": [float], # 12 monthly avg fragility
        "model_accuracy": {"hit_rate": float, "avg_error": float, "best_model": str},
        "top_contributors": [{"ticker","name","return","contribution"}],
        "bottom_contributors": [{"ticker","name","return","contribution"}],
        "year_ahead_themes": [str],
        "proposed_changes": [str],
    }
    """
    d = data
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                            topMargin=60, bottomMargin=60, leftMargin=54, rightMargin=54)
    story = []

    total_return_str = f"{d['portfolio_return_ytd']*100:+.1f}%"
    bench_str = f"{d['benchmark_return_ytd']*100:+.1f}%"
    pnl = d["portfolio_value_end"] - d["portfolio_value_start"]

    def on_first(c, doc_obj):
        draw_cover_page(c, doc_obj,
            firm_name=d["firm_name"], client_name=d["client_name"],
            report_date=d["report_date"],
            report_type=f"{d['review_year']} YEAR-END PORTFOLIO REVIEW",
            subtitle=f"Annual performance and outlook: {d['review_year']}",
            cover_metrics=[
                ("TOTAL RETURN", total_return_str),
                ("BENCHMARK", bench_str),
                ("P&L", f"{'+'if pnl>0 else ''}${pnl:,.0f}"),
                ("ENDING VALUE", f"${d['portfolio_value_end']:,.0f}"),
            ])

    def on_later(c, doc_obj):
        draw_header_footer(c, doc_obj, firm_name=d["firm_name"], client_name=d["client_name"],
                           report_date=d["report_date"], advisor_name=d["advisor_name"])

    story.append(Spacer(1, 1))
    story.append(PageBreak())

    # Page 2: Performance Overview
    story.append(Paragraph("PERFORMANCE OVERVIEW", s_section))
    story.append(Paragraph(f"{d['review_year']} in review", s_heading))

    alpha = d["portfolio_return_ytd"] - d["benchmark_return_ytd"]
    story.append(metrics_row([
        metric_card(total_return_str, "Portfolio return", TEAL if d["portfolio_return_ytd"] > 0 else CORAL),
        metric_card(bench_str, "S&P 500", SLATE),
        metric_card(f"{alpha*100:+.1f}%", "Alpha generated", GREEN if alpha > 0 else RED),
        metric_card(f"${d['portfolio_value_end']:,.0f}", "Ending value", NAVY),
    ]))
    story.append(Spacer(1, 8))

    perf_buf = make_annual_performance(d["months"], d["portfolio_cumulative"], d["benchmark_cumulative"])
    story.append(Image(perf_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.41))
    story.append(Spacer(1, 4))

    monthly_buf = make_monthly_returns_heatmap(d["monthly_returns"])
    story.append(Image(monthly_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.23))

    story.append(PageBreak())

    # Page 3: Risk Evolution + Contributors
    story.append(Paragraph("RISK EVOLUTION", s_section))
    story.append(Paragraph("How risk changed throughout the year", s_heading))

    risk_buf = make_risk_evolution(d["months"], d["vol_series"], d["fragility_series"])
    story.append(Image(risk_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.32))
    story.append(Spacer(1, 6))

    # Risk metrics summary
    story.append(metrics_row([
        metric_card(f"{d['sharpe']:.2f}", "Sharpe ratio", TEAL),
        metric_card(f"{d['sortino']:.2f}", "Sortino ratio", TEAL),
        metric_card(f"{d['max_drawdown']*100:.1f}%", "Max drawdown", CORAL),
        metric_card(f"{d['annualized_vol']*100:.1f}%", "Annual volatility", SLATE),
    ]))
    story.append(Spacer(1, 10))

    # Top / bottom contributors
    story.append(Paragraph("TOP CONTRIBUTORS", s_section))
    tc_data = [["Ticker", "Name", "Position return", "Portfolio contribution"]]
    for h in d["top_contributors"]:
        tc_data.append([h["ticker"], h["name"], f"{h['return']*100:+.1f}%", f"{h['contribution']*100:+.2f}%"])
    story.append(styled_table(tc_data, [0.12, 0.40, 0.24, 0.24]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("BOTTOM CONTRIBUTORS", s_section))
    bc_data = [["Ticker", "Name", "Position return", "Portfolio contribution"]]
    for h in d["bottom_contributors"]:
        bc_data.append([h["ticker"], h["name"], f"{h['return']*100:+.1f}%", f"{h['contribution']*100:+.2f}%"])
    story.append(styled_table(bc_data, [0.12, 0.40, 0.24, 0.24]))

    story.append(PageBreak())

    # Page 4: Model Accuracy + Year Ahead
    story.append(Paragraph("MODEL PERFORMANCE", s_section))
    story.append(Paragraph("How accurate were our forecasts?", s_heading))

    ma = d["model_accuracy"]
    story.append(metrics_row([
        metric_card(f"{ma['hit_rate']*100:.0f}%", "Directional hit rate", TEAL),
        metric_card(f"{ma['avg_error']*100:.1f}%", "Average forecast error", SLATE),
        metric_card(ma["best_model"], "Most-selected model", NAVY),
    ]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"Over {d['review_year']}, the ensemble forecasting engine correctly predicted the "
        f"direction of 90-day forward returns <b>{ma['hit_rate']*100:.0f}%</b> of the time. "
        f"The average absolute forecast error was <b>{ma['avg_error']*100:.1f}%</b>. "
        f"The model most frequently selected by the walk-forward tournament was "
        f"<b>{ma['best_model']}</b>, reflecting the market's trend-driven character this year.",
        s_body
    ))
    story.append(Spacer(1, 14))

    # Year ahead
    story.append(Paragraph(f"{d['review_year']+1} OUTLOOK", s_section))
    story.append(Paragraph("Themes and positioning for the year ahead", s_heading))
    for i, theme in enumerate(d["year_ahead_themes"], 1):
        story.append(Paragraph(f"<b>{i}.</b>  {theme}", s_body))
    story.append(Spacer(1, 8))

    if d.get("proposed_changes"):
        story.append(Paragraph("PROPOSED ADJUSTMENTS", s_section))
        for i, change in enumerate(d["proposed_changes"], 1):
            story.append(Paragraph(f"<b>{i}.</b>  {change}", s_body))

    story.extend(standard_disclaimer(d["firm_name"], d["advisor_name"]))

    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return output_path


# ── DEMO ──
if __name__ == "__main__":
    np.random.seed(77)
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    monthly = np.array([0.028, 0.015, -0.032, 0.041, 0.018, -0.012, 0.035, -0.008, 0.022, 0.019, -0.015, 0.031])
    port_cum = (np.cumprod(1 + monthly) - 1) * 100
    bench_monthly = monthly + np.random.normal(-0.003, 0.005, 12)
    bench_cum = (np.cumprod(1 + bench_monthly) - 1) * 100

    demo = {
        "client_name": "Richardson Family Trust",
        "advisor_name": "Sarah Mitchell, CFA",
        "firm_name": "Meridian Wealth Advisors",
        "report_date": datetime(2026, 1, 5),
        "review_year": 2025,
        "portfolio_value_start": 2_200_000,
        "portfolio_value_end": 2_450_000,
        "portfolio_return_ytd": 0.1136,
        "benchmark_return_ytd": 0.0890,
        "sharpe": 0.82, "sortino": 1.14, "max_drawdown": -0.052, "annualized_vol": 0.1105,
        "months": months,
        "portfolio_cumulative": port_cum.tolist(),
        "benchmark_cumulative": bench_cum.tolist(),
        "monthly_returns": monthly.tolist(),
        "vol_series": [9.2, 10.1, 14.5, 11.8, 10.3, 9.8, 10.5, 11.2, 10.0, 9.5, 12.1, 10.8],
        "fragility_series": [0.85, 0.92, 1.45, 1.12, 0.95, 0.88, 0.97, 1.05, 0.92, 0.87, 1.15, 0.98],
        "model_accuracy": {"hit_rate": 0.72, "avg_error": 0.034, "best_model": "Prophet"},
        "top_contributors": [
            {"ticker": "VTI",  "name": "Vanguard Total Stock",  "return": 0.142, "contribution": 0.0497},
            {"ticker": "GLD",  "name": "SPDR Gold Shares",      "return": 0.185, "contribution": 0.0148},
            {"ticker": "VNQ",  "name": "Vanguard Real Estate",  "return": 0.098, "contribution": 0.0098},
        ],
        "bottom_contributors": [
            {"ticker": "BND",  "name": "Vanguard Total Bond",   "return": -0.018, "contribution": -0.0045},
            {"ticker": "VXUS", "name": "Vanguard Intl Stock",   "return":  0.032, "contribution":  0.0048},
        ],
        "year_ahead_themes": [
            "<b>Rate environment:</b> The Fed is expected to hold rates steady through H1 2026. "
            "Our models suggest maintaining current duration positioning in fixed income.",
            "<b>Volatility outlook:</b> GARCH term structure is currently flat, suggesting "
            "stable volatility near 10-11% annualized. No defensive positioning needed yet.",
            "<b>International opportunity:</b> Emerging market valuations are at a 10-year discount "
            "to developed markets. Consider increasing VXUS allocation from 15% to 18%.",
            "<b>Inflation protection:</b> TIPS breakevens suggest the market underprices 2026 "
            "inflation. Gold and VTIP allocations remain well-positioned.",
        ],
        "proposed_changes": [
            "Increase international equity (VXUS) from 15% to 18%, funded by trimming VTI from 35% to 32%.",
            "Add 2% allocation to short-duration high-yield (SHYG) for income enhancement.",
            "No changes to commodity or TIPS allocations: both performed well and remain appropriate.",
        ],
    }
    generate_yearend_report("/home/claude/reports/yearend_report.pdf", demo)
    print("Year-end report generated.")
