"""
Template 1: QUARTERLY PORTFOLIO RISK INTELLIGENCE REPORT
────────────────────────────────────────────────────────
Purpose: Flagship risk report with ensemble forecast, GARCH volatility,
scenario analysis, and holdings breakdown.
Maps to: /portfolio/analyze + /forecast/{ticker} + /calculate-risk
"""

import numpy as np
from io import BytesIO
from xml.sax.saxutils import escape
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
                         fc_lower, fc_upper, report_date, horizon=90):
    fig, ax = plt.subplots(figsize=(6.8, 3.0))
    _style_ax(ax, f"Portfolio forecast — {horizon}-day horizon", "Indexed value")

    ax.plot(dates_hist, hist_prices, color="#2D3E50", linewidth=1.2, label="History")
    ax.plot(dates_fc, fc_prices, color="#0F8B6E", linewidth=1.5, label="Forecast (median)")
    # Band only when the engine actually produced one — never an invented one.
    if fc_lower is not None and fc_upper is not None:
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
    _style_ax(ax, "Annualized volatility — realized and forecast", "Volatility (%)")

    ax.plot(dates_hist, vol_hist, color="#2D3E50", linewidth=1.0,
            label="Realized (21-day rolling)")
    if vol_fc is not None:
        ax.plot(dates_fc, vol_fc, color="#D4920B", linewidth=1.3, label="GARCH forecast (mean)")
    if vol_lower is not None and vol_upper is not None:
        ax.fill_between(dates_fc, vol_lower, vol_upper, color="#D4920B", alpha=0.12,
                        label="Forecast band")

    ax.axvline(report_date, color="#8B95A2", linewidth=0.8, linestyle="--", alpha=0.7)
    ax.legend(fontsize=7, loc="upper right", framealpha=0.9, edgecolor="#DDE1E6")
    fig.autofmt_xdate()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    return _fig_to_image(fig)


def _make_scenario_chart(scenarios):
    fig, ax = plt.subplots(figsize=(6.8, 2.6))
    _style_ax(ax, "Scenario analysis — simulated median outcome vs base")

    names = [s["name"] for s in scenarios]
    returns = [float(s.get("return_pct") or 0.0) for s in scenarios]
    colors = ["#0F8B6E" if r >= 0 else "#D85A30" if r < -15 else "#D4920B"
              for r in returns]

    bars = ax.barh(names, returns, color=colors, height=0.55,
                   edgecolor="white", linewidth=0.5)

    for bar, ret in zip(bars, returns):
        x_pos = bar.get_width()
        sign = "+" if ret > 0 else ""
        ha = "left" if ret >= 0 else "right"
        ax.text(x_pos, bar.get_y() + bar.get_height() / 2,
                f" {sign}{ret:.1f}%", va="center", ha=ha, fontsize=7.5,
                color="#1A1A2E", fontweight="500")

    ax.axvline(0, color="#8B95A2", linewidth=0.8)
    ax.set_xlabel("Simulated return vs base scenario (%)", fontsize=8, color="#5A6270")
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
    # Engine emits upper_ci/lower_ci; accept the legacy nested key too.
    fc_ci = fc.get("forecast_confidence_interval", {}) or {}
    fc_lower_raw = fc.get("lower_ci") or fc_ci.get("lower", [])
    fc_upper_raw = fc.get("upper_ci") or fc_ci.get("upper", [])
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

    # Prefer the REAL trading dates over synthetic calendar-day axes.
    if portfolio_dates and len(portfolio_dates) >= len(hist_prices):
        try:
            dates_hist = [datetime.fromisoformat(str(x)[:10])
                          for x in portfolio_dates[-len(hist_prices):]]
        except (ValueError, TypeError):
            pass
    fc_dates_raw = fc.get("forecast_dates") or []
    if fc_dates_raw:
        try:
            parsed_fc = [datetime.fromisoformat(str(x)[:10]) for x in fc_dates_raw[:horizon]]
            if len(parsed_fc) == horizon:
                dates_fc = parsed_fc
        except (ValueError, TypeError):
            pass

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
        # No interval from the engine -> omit the band; never invent one.
        fc_lower = fc_upper = None

    # Volatility — a true rolling standard deviation of returns (the old code
    # plotted |rolling MEAN return|, i.e. drift, labeled as volatility).
    vol_hist = np.array([
        np.std(hist_returns[max(0, i - 20):i + 1]) for i in range(len(hist_returns))
    ]) * np.sqrt(252) * 100
    sigma_fc = rd.get("sigma_fc_mean", [])
    if sigma_fc and len(sigma_fc) >= horizon:
        vol_fc = np.array(sigma_fc[:horizon]) * np.sqrt(252) * 100
    else:
        vol_fc = None  # no GARCH forecast available -> omit, don't invent
    # The old ±40% "cone" was hardcoded; omit bands until the risk service
    # supplies real sigma quantiles.
    vol_upper = vol_lower = None

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
        f"(ARIMA, LSTM, Prophet, BSTS, QRC) with GARCH(1,1) volatility modeling using Student-t "
        f"innovations to capture fat-tail risk. Where the winning model supplies a 95% "
        f"interval it is shown alongside the forecast.",
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
                                  fc_lower, fc_upper, report_date, horizon=horizon)
    story.append(Image(fc_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.44))

    band_note = (
        "The shaded region is the winning model's 95% interval. "
        if fc_lower is not None else
        "No model confidence interval was available for this run, so none is shown. "
    )
    story.append(Paragraph(
        "The median forecast path is generated by the winning model from a walk-forward "
        f"validation tournament. {band_note}The current market regime is classified as "
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
        if v is None:
            return "n/a"
        sign = "+" if v > 0 else ""
        return f"{sign}{v*100:.2f}%"

    risk_table_data = [
        ["Metric", "Value", "Interpretation"],
        ["Value at Risk (95%, 1-day)", fmt_pct(rm.get("var_95_daily")),
         "Maximum expected daily loss under normal conditions"],
        ["Conditional VaR (95%)", fmt_pct(rm.get("cvar_95_daily")),
         "Average loss in the worst 5% of trading days"],
        ["Annualized Volatility", fmt_pct(rm.get("annualized_vol", 0)),
         "Standard deviation of returns, annualized"],
        ["Sharpe Ratio", f"{rm.get('sharpe_ratio', 0):.2f}",
         "Risk-adjusted return (excess return / volatility)"],
        ["Sortino Ratio", f"{rm.get('sortino_ratio', 0):.2f}",
         "Downside risk-adjusted return"],
        ["Maximum Drawdown", fmt_pct(rm.get("max_drawdown", 0)),
         "Largest peak-to-trough decline over the analysis window"],
        ["Portfolio Beta", f"{rm.get('beta', 0):.2f}",
         "Sensitivity to broad market movements"],
        ["Fragility Score", f"{rm.get('fragility_score', 0):.2f}",
         "Current vol / long-term median vol (>1.5 = fragile)"],
    ]
    story.append(styled_table(risk_table_data, [0.28, 0.18, 0.54]))

    story.append(PageBreak())

    # ── PAGE 4: SCENARIO ANALYSIS (simulated — only rendered when a real run
    # was supplied; this section never shows invented numbers) ──
    scenarios = d.get("scenarios", [])
    if scenarios:
        story.append(Paragraph("SCENARIO ANALYSIS", s_section))
        story.append(Paragraph("Simulated stress scenarios", s_heading))
        story.append(Paragraph(
            "Scenarios are simulated with the portfolio's MPS-copula Monte Carlo engine: "
            "each scenario draws 500 jointly-sampled price paths sharing the portfolio's "
            "cross-asset dependence structure, with the scenario's price shock, volatility "
            "multiple and drift re-shaping the return distribution. Returns compare each "
            "scenario's median end level against the base scenario. No scenario "
            "probabilities are estimated or shown.",
            s_body
        ))

        sc_buf = _make_scenario_chart(scenarios)
        story.append(Image(sc_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.38))
        story.append(Spacer(1, 8))

        def _cell(v, fmt="{:+.1f}%"):
            return fmt.format(v) if v is not None else "—"

        sc_table_data = [["Scenario", "Return vs base", "Pessimistic tail", "95% band width", "Dollar impact"]]
        for row in scenarios:
            ret = row.get("return_pct")
            impact = row.get("dollar_impact")
            sc_table_data.append([
                row["name"] + (" (reference)" if row.get("is_base") else ""),
                _cell(ret),
                _cell(row.get("downside_pct")),
                _cell(row.get("band_pct"), "{:.1f}%"),
                (f"{'+' if impact > 0 else ''}${impact:,.0f}" if impact is not None else "—"),
            ])
        story.append(styled_table(sc_table_data, [0.28, 0.17, 0.17, 0.17, 0.21]))
        story.append(Spacer(1, 10))

        # AI narrative — grounded in the simulated facts above, clearly labeled.
        sa = d.get("scenario_analysis") or {}
        if sa.get("summary"):
            story.append(Paragraph("AI scenario analysis", s_subheading))
            story.append(Paragraph(escape(sa["summary"]), s_body_sm))
            for e in sa.get("explanations", []):
                story.append(Paragraph(
                    f"<b>{escape(e.get('name', ''))}</b> — {escape(e.get('narrative', ''))}",
                    s_body_sm
                ))
            story.append(Paragraph(
                "The analysis above was AI-generated from the simulated results shown on this "
                "page. It is informational only and is not investment advice.",
                s_disclaimer
            ))
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
        "(ARIMA, LSTM, Prophet, BSTS, QRC — Quantum Reservoir Computing) using walk-forward validation. "
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
        "<b>Scenario analysis</b> — Scenarios are simulated with a tensor-network "
        "(MPS) copula: the portfolio's cross-asset dependence is learned from history "
        "and 500 joint return paths are sampled per scenario; each scenario's price "
        "shock, volatility multiple and drift re-shape the marginal distributions "
        "while dependence is held fixed, making scenarios directly comparable. "
        "Reported figures are percentiles of those simulated paths. Scenario "
        "probabilities are not modeled.",
        s_body
    ))
    story.append(Paragraph(
        "<b>Confidence intervals</b> — Where shown, the 95% band is the winning "
        "forecast model's own interval. When a model run does not produce an "
        "interval, the band is omitted rather than approximated.",
        s_body
    ))

    story.extend(standard_disclaimer(d["firm_name"], d["advisor_name"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f"<b>Report generated:</b> {report_date.strftime('%B %d, %Y at %I:%M %p')}  |  "
        f"<b>Engine:</b> Qsight risk intelligence  |  "
        f"<b>Models:</b> 5-family forecast ensemble + GARCH(1,1)-std risk service",
        s_footer_meta,
    ))

    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return output_path
