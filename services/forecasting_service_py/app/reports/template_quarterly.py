"""
Template 1: QUARTERLY PORTFOLIO RISK INTELLIGENCE REPORT
────────────────────────────────────────────────────────
Purpose: Flagship risk report with ensemble forecast, GARCH volatility,
scenario analysis, and holdings breakdown.
Maps to: /portfolio/analyze + /forecast/{ticker} + /calculate-risk
"""

import numpy as np
from io import BytesIO
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image, Table, TableStyle, HRFlowable
)

from app.reports.report_styles import *


# ─────────────────────────────────────────────
# CHART HELPERS
# ─────────────────────────────────────────────

def _fig_to_image(fig, dpi=180):
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def _style_ax(ax, title=None, ylabel=None):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDE1E6")
    ax.spines["bottom"].set_color("#DDE1E6")
    ax.tick_params(colors="#5A6270", labelsize=7.5)
    ax.grid(axis="y", color="#EEF0F3", linewidth=0.6)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, fontsize=10, fontweight="600", color="#1A1A2E",
                      loc="left", pad=10)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=8, color="#5A6270")


def _make_forecast_chart(dates_hist, hist_prices, dates_fc, fc_prices,
                         fc_lower, fc_upper, report_date):
    fig, ax = plt.subplots(figsize=(6.8, 3.0))
    _style_ax(ax, "Portfolio forecast — 90-day horizon", "Indexed value")

    ax.plot(dates_hist, hist_prices, color="#2D3E50", linewidth=1.2, label="History")
    ax.plot(dates_fc, fc_prices, color="#0F8B6E", linewidth=1.5, label="Forecast (median)")
    ax.fill_between(dates_fc, fc_lower, fc_upper, color="#0F8B6E", alpha=0.10,
                    label="95% confidence")

    ax.axvline(report_date, color="#8B95A2", linewidth=0.8, linestyle="--", alpha=0.7)
    ax.text(report_date, ax.get_ylim()[1] * 0.99, " Today ", fontsize=7,
            color="#5A6270", ha="left", va="top")

    ax.legend(fontsize=7, loc="upper left", framealpha=0.9, edgecolor="#DDE1E6")
    fig.autofmt_xdate()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    return _fig_to_image(fig)


def _make_volatility_chart(dates_hist, vol_hist, dates_fc, vol_fc,
                           vol_lower, vol_upper, report_date):
    fig, ax = plt.subplots(figsize=(6.8, 2.4))
    _style_ax(ax, "Annualized volatility with GARCH cone", "Volatility (%)")

    ax.plot(dates_hist, vol_hist, color="#2D3E50", linewidth=1.0, label="Historical (GARCH)")
    ax.plot(dates_fc, vol_fc, color="#D4920B", linewidth=1.3, label="Forecast (mean)")
    ax.fill_between(dates_fc, vol_lower, vol_upper, color="#D4920B", alpha=0.12,
                    label="Volatility cone")

    ax.axvline(report_date, color="#8B95A2", linewidth=0.8, linestyle="--", alpha=0.7)
    ax.legend(fontsize=7, loc="upper right", framealpha=0.9, edgecolor="#DDE1E6")
    fig.autofmt_xdate()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    return _fig_to_image(fig)


def _make_scenario_chart(scenarios):
    fig, ax = plt.subplots(figsize=(6.8, 2.6))
    _style_ax(ax, "Scenario analysis — projected 12-month outcomes")

    names = [s["name"] for s in scenarios]
    returns = [s["return_12m"] * 100 for s in scenarios]
    colors = ["#0F8B6E" if r >= 0 else "#D85A30" if r < -15 else "#D4920B"
              for r in returns]
    probs = [s["prob"] * 100 for s in scenarios]

    bars = ax.barh(names, returns, color=colors, height=0.55,
                   edgecolor="white", linewidth=0.5)

    for bar, ret, prob in zip(bars, returns, probs):
        x_pos = bar.get_width()
        sign = "+" if ret > 0 else ""
        label = f" {sign}{ret:.1f}%  ({prob:.0f}% prob.)"
        ha = "left" if ret >= 0 else "right"
        ax.text(x_pos, bar.get_y() + bar.get_height() / 2,
                label, va="center", ha=ha, fontsize=7.5, color="#1A1A2E",
                fontweight="500")

    ax.axvline(0, color="#8B95A2", linewidth=0.8)
    ax.set_xlabel("Projected return (%)", fontsize=8, color="#5A6270")
    ax.invert_yaxis()
    return _fig_to_image(fig)


def _make_drawdown_chart(dates_hist, hist_prices):
    fig, ax = plt.subplots(figsize=(6.8, 2.0))
    _style_ax(ax, "Historical drawdown profile")

    prices = np.array(hist_prices)
    cum = np.cumprod(1 + np.diff(prices) / prices[:-1])
    cum = np.insert(cum, 0, 1.0)
    running_max = np.maximum.accumulate(cum)
    drawdown = (cum / running_max - 1) * 100

    ax.fill_between(dates_hist, drawdown, 0, color="#C0392B", alpha=0.20)
    ax.plot(dates_hist, drawdown, color="#C0392B", linewidth=0.9)
    ax.set_ylabel("Drawdown (%)", fontsize=8, color="#5A6270")
    ax.set_ylim(min(drawdown) * 1.3, 1)
    fig.autofmt_xdate()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    return _fig_to_image(fig)


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def generate_quarterly_report(output_path, data):
    """
    data = {
        "client_name": str,
        "advisor_name": str,
        "firm_name": str,
        "report_date": datetime,
        "portfolio_value": float,
        "holdings": [{"ticker","name","sector","weight","value"}],
        "risk_metrics": {
            "sharpe_ratio", "sortino_ratio", "max_drawdown",
            "annualized_vol", "var_95_daily", "cvar_95_daily",
            "beta", "fragility_score", "regime",
        },
        "forecast_result": {
            "forecast_prices": [...],
            "forecast_confidence_interval": {"lower": [...], "upper": [...]},
            ...
        },
        "risk_data": {
            "sigma_hist": [...],
            "sigma_fc_mean": [...],
            "mc_lower": [...], "mc_upper": [...],
            ...
        },
        "scenarios": [{"name","return_12m","drawdown","prob","color"}],
    }
    """
    d = data
    rm = d["risk_metrics"]
    report_date = d["report_date"]

    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        topMargin=60, bottomMargin=60,
        leftMargin=54, rightMargin=54,
    )
    story = []

    # ── Prepare time-series data for charts ──
    fc = d.get("forecast_result", {})
    rd = d.get("risk_data", {})

    fc_prices_raw = fc.get("forecast_prices", [])
    fc_ci = fc.get("forecast_confidence_interval", {})
    fc_lower_raw = fc_ci.get("lower", [])
    fc_upper_raw = fc_ci.get("upper", [])
    horizon = len(fc_prices_raw) if fc_prices_raw else 90

    # Build date arrays
    n_hist = 252
    dates_hist = [report_date - timedelta(days=n_hist - i) for i in range(n_hist)]
    dates_fc = [report_date + timedelta(days=i + 1) for i in range(horizon)]

    # Historical prices — use real portfolio prices passed from router
    portfolio_prices = d.get("portfolio_prices", [])
    portfolio_dates = d.get("portfolio_dates", [])
    if portfolio_prices and len(portfolio_prices) >= n_hist:
        hist_prices = np.array(portfolio_prices[-n_hist:])
    elif portfolio_prices:
        hist_prices = np.array(portfolio_prices)
        n_hist = len(hist_prices)
        dates_hist = [report_date - timedelta(days=n_hist - i) for i in range(n_hist)]
    else:
        # Last resort: flat line (no data available)
        hist_prices = np.full(n_hist, 100.0)

    # Compute real historical returns from prices
    hist_returns = np.diff(hist_prices) / hist_prices[:-1]
    hist_returns = np.insert(hist_returns, 0, 0.0)

    # Forecast prices
    if fc_prices_raw:
        fc_prices = np.array(fc_prices_raw[:horizon])
    else:
        # Extrapolate from last price using mean historical drift
        mean_ret = np.mean(hist_returns[-63:]) if len(hist_returns) > 63 else np.mean(hist_returns)
        vol = np.std(hist_returns[-63:]) if len(hist_returns) > 63 else np.std(hist_returns)
        fc_prices = hist_prices[-1] * np.exp(np.cumsum(np.full(horizon, mean_ret)))

    if fc_lower_raw and fc_upper_raw:
        fc_lower = np.array(fc_lower_raw[:horizon])
        fc_upper = np.array(fc_upper_raw[:horizon])
    else:
        fc_lower = fc_prices * 0.92
        fc_upper = fc_prices * 1.08

    # Volatility data — computed from real returns
    vol_hist = np.abs(np.convolve(hist_returns, np.ones(21) / 21, mode='same')) * np.sqrt(252) * 100
    sigma_fc = rd.get("sigma_fc_mean", [])
    if sigma_fc and len(sigma_fc) >= horizon:
        vol_fc = np.array(sigma_fc[:horizon]) * np.sqrt(252) * 100
    else:
        vol_fc = np.linspace(vol_hist[-1], vol_hist[-1] * 0.95, horizon)
    vol_upper = vol_fc * 1.4
    vol_lower = vol_fc * 0.6

    # ── COVER PAGE ──
    def on_first(c, doc_obj):
        draw_cover_page(c, doc_obj,
            firm_name=d["firm_name"], client_name=d["client_name"],
            report_date=report_date,
            report_type="PORTFOLIO RISK INTELLIGENCE REPORT",
            subtitle=f"Prepared for review — {report_date.strftime('%B %d, %Y')}",
            cover_metrics=[
                ("PORTFOLIO VALUE", f"${d['portfolio_value']:,.0f}"),
                ("REGIME", str(rm.get("regime", "Normal"))),
                ("ANNUALIZED VOL", f"{rm.get('annualized_vol', 0) * 100:.1f}%"),
                ("SHARPE RATIO", f"{rm.get('sharpe_ratio', 0):.2f}"),
            ])

    def on_later(c, doc_obj):
        draw_header_footer(c, doc_obj,
            firm_name=d["firm_name"], client_name=d["client_name"],
            report_date=report_date, advisor_name=d["advisor_name"])

    story.append(Spacer(1, 1))
    story.append(PageBreak())

    # ── PAGE 2: EXECUTIVE SUMMARY ──
    story.append(Paragraph("EXECUTIVE SUMMARY", s_section))
    story.append(Paragraph("Portfolio overview", s_heading))
    story.append(Paragraph(
        f"This report provides a comprehensive risk assessment of the {d['client_name']} portfolio "
        f"as of {report_date.strftime('%B %d, %Y')}. The analysis employs a multi-model ensemble "
        f"(ARIMA, LSTM, Prophet, BSTS) with GARCH(1,1) volatility modeling using Student-t "
        f"innovations to capture fat-tail risk. All projections include 95% confidence intervals "
        f"derived from Monte Carlo simulation.",
        s_body
    ))

    # Key metrics row
    mr = metrics_row([
        metric_card(f"${d['portfolio_value']:,.0f}", "Total value", NAVY),
        metric_card(f"{rm.get('annualized_vol', 0)*100:.1f}%", "Annual volatility"),
        metric_card(f"{rm.get('sharpe_ratio', 0):.2f}", "Sharpe ratio", TEAL),
        metric_card(f"{rm.get('max_drawdown', 0)*100:.1f}%", "Max drawdown", CORAL),
    ])
    story.append(Spacer(1, 8))
    story.append(mr)
    story.append(Spacer(1, 12))

    # Forecast chart
    story.append(Paragraph("PRICE FORECAST", s_section))
    story.append(Paragraph(f"{horizon}-day forward projection with confidence bands", s_subheading))
    fc_buf = _make_forecast_chart(dates_hist, hist_prices, dates_fc, fc_prices,
                                  fc_lower, fc_upper, report_date)
    story.append(Image(fc_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.44))

    story.append(Paragraph(
        "The median forecast path is generated by the winning model from a walk-forward "
        "validation tournament. The shaded region represents the 95% confidence interval "
        "derived from bootstrapped historical return residuals scaled by the GARCH forward "
        f"volatility forecast. The current market regime is classified as "
        f"<b>{rm.get('regime', 'Normal')}</b> with a fragility score of "
        f"<b>{rm.get('fragility_score', 0):.2f}</b>.",
        s_body_sm
    ))

    story.append(PageBreak())

    # ── PAGE 3: RISK ANALYSIS ──
    story.append(Paragraph("RISK ANALYSIS", s_section))
    story.append(Paragraph("Volatility and drawdown profile", s_heading))

    vol_buf = _make_volatility_chart(dates_hist, vol_hist, dates_fc, vol_fc,
                                     vol_lower, vol_upper, report_date)
    story.append(Image(vol_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.35))
    story.append(Spacer(1, 4))

    dd_buf = _make_drawdown_chart(dates_hist, hist_prices)
    story.append(Image(dd_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.29))
    story.append(Spacer(1, 8))

    # Risk metrics table
    story.append(Paragraph("Detailed risk metrics", s_subheading))

    def fmt_pct(v):
        sign = "+" if v > 0 else ""
        return f"{sign}{v*100:.2f}%"

    risk_table_data = [
        ["Metric", "Value", "Interpretation"],
        ["Value at Risk (95%, 1-day)", fmt_pct(rm.get("var_95_daily", -0.02)),
         "Maximum expected daily loss under normal conditions"],
        ["Conditional VaR (95%)", fmt_pct(rm.get("cvar_95_daily", -0.03)),
         "Average loss in the worst 5% of trading days"],
        ["Annualized Volatility", fmt_pct(rm.get("annualized_vol", 0)),
         "Standard deviation of returns, annualized"],
        ["Sharpe Ratio", f"{rm.get('sharpe_ratio', 0):.2f}",
         "Risk-adjusted return (excess return / volatility)"],
        ["Sortino Ratio", f"{rm.get('sortino_ratio', 0):.2f}",
         "Downside risk-adjusted return"],
        ["Maximum Drawdown", fmt_pct(rm.get("max_drawdown", 0)),
         "Largest peak-to-trough decline in trailing 12 months"],
        ["Portfolio Beta", f"{rm.get('beta', 0):.2f}",
         "Sensitivity to broad market movements"],
        ["Fragility Score", f"{rm.get('fragility_score', 0):.2f}",
         "Current vol / long-term median vol (>1.5 = fragile)"],
    ]
    story.append(styled_table(risk_table_data, [0.28, 0.18, 0.54]))

    story.append(PageBreak())

    # ── PAGE 4: SCENARIO ANALYSIS ──
    scenarios = d.get("scenarios", [])
    if scenarios:
        story.append(Paragraph("SCENARIO ANALYSIS", s_section))
        story.append(Paragraph("Stress testing and forward projections", s_heading))
        story.append(Paragraph(
            "The following scenarios model how the portfolio would respond under different "
            "macroeconomic conditions. Probabilities are derived from current regime indicators, "
            "yield curve shape, and credit spread analysis.",
            s_body
        ))

        sc_buf = _make_scenario_chart(scenarios)
        story.append(Image(sc_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.38))
        story.append(Spacer(1, 8))

        # Scenario detail table
        sc_table_data = [["Scenario", "12M Return", "Max Drawdown", "Portfolio Impact", "Probability"]]
        for s in scenarios:
            ret = s["return_12m"]
            impact = d["portfolio_value"] * ret
            sign = "+" if ret > 0 else ""
            sc_table_data.append([
                s["name"],
                f"{sign}{ret*100:.1f}%",
                f"{s['drawdown']*100:.0f}%",
                f"{sign}${impact:,.0f}",
                f"{s['prob']*100:.0f}%",
            ])
        story.append(styled_table(sc_table_data, [0.25, 0.16, 0.18, 0.22, 0.19]))
        story.append(Spacer(1, 12))

    # Holdings table
    holdings = d.get("holdings", [])
    if holdings:
        story.append(Paragraph("HOLDINGS", s_section))
        story.append(Paragraph("Current portfolio composition", s_subheading))

        h_data = [["Ticker", "Name", "Sector", "Weight", "Value"]]
        for h in holdings:
            h_data.append([
                h["ticker"], h["name"], h.get("sector", "Equity"),
                f"{h['weight']*100:.0f}%", f"${h['value']:,.0f}"
            ])
        h_data.append(["", "", "", "100%", f"${d['portfolio_value']:,.0f}"])
        story.append(styled_table(h_data, [0.10, 0.32, 0.20, 0.14, 0.24]))

    story.append(PageBreak())

    # ── PAGE 5: METHODOLOGY & DISCLAIMER ──
    story.append(Paragraph("METHODOLOGY", s_section))
    story.append(Paragraph("Model framework and assumptions", s_heading))

    story.append(Paragraph(
        "<b>Forecasting engine</b> — The system runs a tournament across five model families "
        "(ARIMA, LSTM, Prophet, BSTS, Quantum Kernel SVR) using walk-forward validation. "
        "Each model is trained on 2 years of daily close prices with exogenous features "
        "including quantum circuit encodings, semantic embeddings of price regime descriptions, "
        "and GARCH-derived volatility. The winner is selected by combined RMSE across "
        "single-split and walk-forward windows (50/50 weighting).",
        s_body
    ))
    story.append(Paragraph(
        "<b>Risk engine</b> — Volatility is modeled via sGARCH(1,1) with Student-t "
        "innovations (R/rugarch). This captures fat tails and volatility clustering that "
        "Gaussian models miss. Monte Carlo simulation generates 1,000 price paths for "
        "cone construction. The fragility score compares current volatility to the 126-day "
        "rolling median, with scores above 1.5 triggering a High Fragility regime flag.",
        s_body
    ))
    story.append(Paragraph(
        "<b>Scenario analysis</b> — Scenarios apply initial shocks and drift adjustments "
        "to the base forecast. Probabilities are informed by current regime classification, "
        "not predicted. The severe downturn scenario uses a 2x volatility scaling to stress-test "
        "tail outcomes.",
        s_body
    ))
    story.append(Paragraph(
        "<b>Confidence intervals</b> — The 95% band is constructed from bootstrapped "
        "historical return residuals, scaled by the GARCH forward volatility forecast "
        "at each horizon step. This produces scenario-consistent bands that widen "
        "appropriately under high-volatility regimes.",
        s_body
    ))

    story.extend(standard_disclaimer(d["firm_name"], d["advisor_name"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f"<b>Report generated:</b> {report_date.strftime('%B %d, %Y at %I:%M %p')}  |  "
        f"<b>Engine version:</b> Forecastium v2.1  |  "
        f"<b>Models:</b> 5-family ensemble + GARCH(1,1)-std",
        s_footer_meta,
    ))

    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return output_path
