"""
Template 5: YEAR-END PORTFOLIO REVIEW
Purpose: Annual review showing the year's REAL performance (months without
price data are omitted, never zero-filled), risk evolution, walk-forward model
validation when real figures exist (omitted otherwise), and an AI year-ahead
narrative grounded in the current regime and fragility, clearly disclaimed.
Maps to: /reports/year-end.
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


def _nan_array(values):
    """Convert a list with None gaps into a float array with NaN gaps."""
    return np.array([np.nan if v is None else float(v) for v in (values or [])],
                    dtype=float)


def make_annual_performance(months, port_cumulative, bench_cumulative,
                            benchmark_label=None):
    """Cumulative return lines over the review year. Months without data are
    gaps, and the benchmark line is drawn only when a real series was
    supplied, labeled with whichever benchmark actually supplied it."""
    fig, ax = plt.subplots(figsize=(6.8, 2.8))

    port = _nan_array(port_cumulative)
    ax.plot(months, port, color="#0F8B6E", linewidth=1.8, label="Your portfolio")
    if bench_cumulative is not None:
        bench = _nan_array(bench_cumulative)
        ax.plot(months, bench, color="#8B95A2", linewidth=1.2, linestyle="--",
                label=benchmark_label or "Benchmark")
        both = np.isfinite(port) & np.isfinite(bench)
        ax.fill_between(months, port, bench, where=(both & (port > bench)),
                        color="#0F8B6E", alpha=0.08)
        ax.fill_between(months, port, bench, where=(both & (port <= bench)),
                        color="#D85A30", alpha=0.08)

    ax.axhline(0, color="#8B95A2", linewidth=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDE1E6")
    ax.spines["bottom"].set_color("#DDE1E6")
    ax.tick_params(colors="#5A6270", labelsize=7.5)
    ax.grid(axis="y", color="#EEF0F3", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title("Cumulative return over the review year",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=10)
    ax.set_ylabel("Return (%)", fontsize=8, color="#5A6270")
    ax.legend(fontsize=7, loc="upper left", framealpha=0.9, edgecolor="#DDE1E6")

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def make_monthly_returns_heatmap(months, monthly_returns):
    """Monthly return bars. Months without data draw no bar and no label:
    a missing month is never rendered as a 0.0% observation."""
    fig, ax = plt.subplots(figsize=(6.8, 1.6))

    vals = _nan_array(monthly_returns) * 100
    # Register every month on the categorical axis, then draw only real bars.
    ax.bar(months, np.zeros(len(months)), color="none", edgecolor="none")
    for i, val in enumerate(vals):
        if not np.isfinite(val):
            continue
        color = "#1B8553" if val > 0 else "#C0392B"
        bar = ax.bar(months[i], val, color=color, edgecolor="white",
                     linewidth=0.5, width=0.65)[0]
        y_pos = bar.get_height() + (0.15 if val >= 0 else -0.4)
        ax.text(bar.get_x() + bar.get_width() / 2, y_pos, f"{val:+.1f}%",
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
    """Monthly realized vol and fragility. Missing months are gaps; either
    series is omitted entirely when it has no real data."""
    fig, ax1 = plt.subplots(figsize=(6.8, 2.2))

    vols = _nan_array(vol_series)
    frag = _nan_array(fragility_series)
    has_vol = bool(len(vols)) and bool(np.isfinite(vols).any())
    has_frag = bool(len(frag)) and bool(np.isfinite(frag).any())

    lines1, labels1, lines2, labels2 = [], [], [], []
    if has_vol:
        ax1.plot(months_labels, vols, color="#2B7ACC", linewidth=1.3,
                 label="Annualized vol (%)")
        ax1.fill_between(months_labels, np.nan_to_num(vols, nan=0.0),
                         where=np.isfinite(vols), alpha=0.06, color="#2B7ACC")
        ax1.set_ylabel("Volatility (%)", fontsize=8, color="#2B7ACC")
        ax1.tick_params(axis="y", colors="#2B7ACC", labelsize=7.5)
        lines1, labels1 = ax1.get_legend_handles_labels()
    else:
        # Keep the categorical x-axis even when only fragility exists.
        ax1.plot(months_labels, np.full(len(months_labels), np.nan))
        ax1.set_yticks([])

    if has_frag:
        ax2 = ax1.twinx()
        ax2.plot(months_labels, frag, color="#D4920B", linewidth=1.3,
                 linestyle="--", label="Fragility score")
        ax2.axhline(1.5, color="#D85A30", linewidth=0.6, linestyle=":", alpha=0.6)
        ax2.text(len(months_labels) - 1, 1.55, " Fragile threshold",
                 fontsize=6.5, color="#D85A30", va="bottom", ha="right")
        ax2.set_ylabel("Fragility score", fontsize=8, color="#D4920B")
        ax2.tick_params(axis="y", colors="#D4920B", labelsize=7.5)
        ax2.spines["top"].set_visible(False)
        lines2, labels2 = ax2.get_legend_handles_labels()

    ax1.spines["top"].set_visible(False)
    ax1.spines["bottom"].set_color("#DDE1E6")
    ax1.tick_params(axis="x", colors="#5A6270", labelsize=7.5)
    ax1.grid(axis="y", color="#EEF0F3", linewidth=0.6)
    ax1.set_axisbelow(True)
    ax1.set_title("Risk regime evolution over the review year",
                 fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=10)
    if lines1 or lines2:
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
        # Dollar values are rendered ONLY when the caller supplied them.
        "portfolio_value_start": float or None,
        "portfolio_value_end": float or None,
        "portfolio_return_ytd": float,       # over the covered months
        "coverage_label": str,               # e.g. "January to December 2025"
        "full_year": bool,
        # None -> benchmark omitted everywhere, never a flat fake line.
        "benchmark_return_ytd": float or None,
        "benchmark_label": str or None,
        # Trailing engine analysis window, labeled honestly via metrics_window_label.
        "sharpe", "sortino", "max_drawdown", "annualized_vol",
        "metrics_window_label": str,
        "regime": str, "fragility_score": float,
        "months": [str],                          # 12 month labels
        "portfolio_cumulative": [float or None],  # cumulative % per month
        "benchmark_cumulative": [float or None] or None,
        "monthly_returns": [float or None],       # None -> month omitted
        "vol_series": [float or None] or None,
        "fragility_series": [float or None] or None,
        # Real walk-forward validation figures, or None -> section omitted.
        "model_accuracy": {"hit_rate", "avg_error", "n_steps", "best_model"} or None,
        # Component decomposition of portfolio volatility (share of risk vs
        # weight), or None -> the risk-contribution table is omitted.
        "risk_attribution": {"portfolio_vol", "n_obs",
                             "rows": [{"ticker","weight","risk_pct"}]} or None,
        # Directional accuracy with a 95% CI vs the 50% coin-flip baseline, or
        # None -> the model track-record line is omitted.
        "track_record": {"hit_rate","n_steps","ci_low","ci_high",
                         "beats_coinflip","best_model"} or None,
        # Every downside measure on one dollar basis (rendered only when real
        # scenarios AND a portfolio value were supplied), or None -> omitted.
        "risk_reconciliation": {"var_1d_pct","var_1d_dollars","max_drawdown_pct",
                               "max_drawdown_dollars","worst_scenario",
                               "worst_scenario_dollars","forecast_downside_pct",
                               "forecast_downside_dollars","fragility_label",
                               "flags"} or None,
        "top_contributors": [{"ticker","name","return","contribution"}],
        "bottom_contributors": [{"ticker","name","return","contribution"}],
        # AI narrative grounded in the numbers above (None -> numbers-only).
        "narrative": {"year_summary", "risk_commentary", "model_commentary",
                      "year_ahead", "considerations"} or None,
        # Advisor-authored adjustments passed through the API (never canned).
        "proposed_changes": [str] or None,
    }
    """
    d = data
    narrative = d.get("narrative") or {}
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                            topMargin=60, bottomMargin=60, leftMargin=54, rightMargin=54)
    story = []

    year = d["review_year"]
    total_return_str = f"{d['portfolio_return_ytd']*100:+.1f}%"
    has_bench = d.get("benchmark_return_ytd") is not None
    bench_label = d.get("benchmark_label") or "Benchmark"
    bench_str = f"{d['benchmark_return_ytd']*100:+.1f}%" if has_bench else "n/a"
    value_start = d.get("portfolio_value_start")
    value_end = d.get("portfolio_value_end")
    has_values = bool(value_start) and bool(value_end)

    # Cover metrics: only real figures. Dollar cards appear only when the
    # caller supplied both values; otherwise current risk state fills in.
    cover_metrics = [("TOTAL RETURN", total_return_str)]
    if has_bench:
        cover_metrics.append((bench_label.upper(), bench_str))
    if has_values:
        pnl = value_end - value_start
        cover_metrics += [
            ("P&L", f"{'+' if pnl > 0 else ''}${pnl:,.0f}"),
            ("ENDING VALUE", f"${value_end:,.0f}"),
        ]
    else:
        cover_metrics += [
            ("REGIME", humanize_label(d.get("regime", "Normal"))),
            ("FRAGILITY", f"{d.get('fragility_score', 0):.2f}"),
        ]

    def on_first(c, doc_obj):
        draw_cover_page(c, doc_obj,
            firm_name=d["firm_name"], client_name=d["client_name"],
            report_date=d["report_date"],
            report_type=f"{year} YEAR-END PORTFOLIO REVIEW",
            subtitle=f"Annual performance and outlook: {year}",
            cover_metrics=cover_metrics[:4])

    def on_later(c, doc_obj):
        draw_header_footer(c, doc_obj, firm_name=d["firm_name"], client_name=d["client_name"],
                           report_date=d["report_date"], advisor_name=d["advisor_name"])

    story.append(Spacer(1, 1))
    story.append(PageBreak())

    # Page 2: Performance Overview
    story.append(Paragraph("PERFORMANCE OVERVIEW", s_section))
    story.append(Paragraph(f"{year} in review", s_heading))

    perf_cards = [
        metric_card(total_return_str, "Portfolio return",
                    TEAL if d["portfolio_return_ytd"] > 0 else CORAL),
    ]
    if has_bench:
        # Honest label: a simple return difference, not risk-adjusted alpha.
        rel = d["portfolio_return_ytd"] - d["benchmark_return_ytd"]
        perf_cards.append(metric_card(bench_str, bench_label, SLATE))
        perf_cards.append(metric_card(f"{rel*100:+.1f}%", "Return vs benchmark",
                                      GREEN if rel > 0 else RED))
    if value_end:
        perf_cards.append(metric_card(f"${value_end:,.0f}", "Ending value", NAVY))
    story.append(metrics_row(perf_cards))
    story.append(Spacer(1, 4))

    coverage_notes = []
    if not d.get("full_year", True):
        coverage_notes.append(
            f"Return figures cover {d['coverage_label']}: months without portfolio "
            "price data are omitted from this review, never shown as 0.0%.")
    if not has_bench:
        coverage_notes.append(
            "No benchmark data was available for the covered months, so no "
            "benchmark comparison is shown.")
    if coverage_notes:
        story.append(Paragraph(" ".join(coverage_notes), s_disclaimer))
    story.append(Spacer(1, 4))

    if narrative.get("year_summary"):
        story.append(Paragraph(escape(narrative["year_summary"]), s_body))
        story.append(Spacer(1, 4))

    perf_buf = make_annual_performance(
        d["months"], d["portfolio_cumulative"],
        d.get("benchmark_cumulative") if has_bench else None,
        benchmark_label=bench_label)
    story.append(Image(perf_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.41))
    story.append(Spacer(1, 4))

    monthly_buf = make_monthly_returns_heatmap(d["months"], d["monthly_returns"])
    story.append(Image(monthly_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.23))
    if any(r is None for r in d["monthly_returns"]):
        story.append(Paragraph(
            "Months without sufficient price data draw no bar.", s_disclaimer))

    story.append(PageBreak())

    # Page 3: Risk Evolution + Contributors
    story.append(Paragraph("RISK EVOLUTION", s_section))
    story.append(Paragraph("How risk changed throughout the year", s_heading))

    vol_series = d.get("vol_series") or []
    fragility_series = d.get("fragility_series") or []
    has_risk_series = (any(v is not None for v in vol_series)
                       or any(f is not None for f in fragility_series))
    if has_risk_series:
        risk_buf = make_risk_evolution(d["months"], vol_series, fragility_series)
        story.append(Image(risk_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.32))
    else:
        story.append(Paragraph(
            f"Monthly volatility and fragility series were not available for {year}, "
            "so no risk-evolution chart is shown.", s_body_sm))
    story.append(Spacer(1, 6))

    if narrative.get("risk_commentary"):
        story.append(Paragraph(escape(narrative["risk_commentary"]), s_body_sm))
        story.append(Spacer(1, 4))

    # Risk metrics: computed over the engine's trailing analysis window and
    # labeled as such; they are NOT calendar-year statistics.
    story.append(metrics_row([
        metric_card(f"{d['sharpe']:.2f}", "Sharpe ratio", TEAL),
        metric_card(f"{d['sortino']:.2f}", "Sortino ratio", TEAL),
        metric_card(f"{d['max_drawdown']*100:.1f}%", "Max drawdown", CORAL),
        metric_card(f"{d['annualized_vol']*100:.1f}%", "Annual volatility", SLATE),
    ]))
    story.append(Paragraph(
        f"Sharpe, Sortino, max drawdown, and annualized volatility are computed over "
        f"the {d.get('metrics_window_label', 'engine analysis window')}, "
        f"not over calendar {year} alone.",
        s_disclaimer))
    story.append(Spacer(1, 8))

    # Risk contribution by holding: which position actually drove portfolio
    # RISK over the year (component decomposition of volatility). A holding's
    # share of risk can exceed its weight when it is more volatile or more
    # correlated with the rest of the book. Omitted when unavailable.
    ra = d.get("risk_attribution") or {}
    if ra.get("rows"):
        story.append(Paragraph("Risk contribution by holding", s_subheading))
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
        story.append(Spacer(1, 8))

    # Risk in one view: every downside measure on a common dollar basis, so the
    # 1-day VaR, worst simulated scenario, realized drawdown, and forecast
    # downside can be compared directly. Rendered only when a real scenario run
    # AND a portfolio value were supplied; any consistency flag is surfaced.
    rr = d.get("risk_reconciliation") or {}
    _recon_keys = ("var_1d_dollars", "worst_scenario_dollars",
                   "max_drawdown_dollars", "forecast_downside_dollars")
    if any(rr.get(k) is not None for k in _recon_keys):
        def _dol(v):
            return f"{'+' if v > 0 else '-'}${abs(v):,.0f}" if v is not None else "n/a"

        def _pf(v):  # fractional inputs (VaR, drawdown)
            return f"{v * 100:+.2f}%" if v is not None else "n/a"

        def _pp(v):  # already-percent inputs (scenario, forecast low end)
            return f"{v:+.1f}%" if v is not None else "n/a"

        story.append(Paragraph("Risk in one view", s_subheading))
        rv_rows = [["Downside measure", "Percentage", "Dollar impact"]]
        if rr.get("var_1d_dollars") is not None:
            rv_rows.append(["1-day Value at Risk (95%)", _pf(rr.get("var_1d_pct")),
                            _dol(rr["var_1d_dollars"])])
        ws = rr.get("worst_scenario") or {}
        if rr.get("worst_scenario_dollars") is not None:
            rv_rows.append([
                f"Worst simulated scenario ({humanize_label(ws.get('name', ''))})",
                _pp(ws.get("return_pct")), _dol(rr["worst_scenario_dollars"])])
        if rr.get("max_drawdown_dollars") is not None:
            rv_rows.append(["Realized maximum drawdown", _pf(rr.get("max_drawdown_pct")),
                            _dol(rr["max_drawdown_dollars"])])
        if rr.get("forecast_downside_dollars") is not None:
            rv_rows.append(["Forecast downside (low end)", _pp(rr.get("forecast_downside_pct")),
                            _dol(rr["forecast_downside_dollars"])])
        story.append(styled_table(rv_rows, [0.46, 0.24, 0.30]))
        story.append(Paragraph(
            f"Dollar figures use the supplied portfolio value. Scenario figures are "
            f"simulated median outcomes versus the base scenario, not probabilities. "
            f"Fragility reading: {escape(str(rr.get('fragility_label', 'n/a')))}.",
            s_disclaimer))
        for fl in rr.get("flags", []):
            story.append(Paragraph(f"Note: {escape(str(fl))}", s_disclaimer))
        story.append(Spacer(1, 8))

    # Top / bottom contributors: only holdings with real price data appear.
    top_contribs = d.get("top_contributors") or []
    bottom_contribs = d.get("bottom_contributors") or []
    if top_contribs:
        story.append(Paragraph("TOP CONTRIBUTORS", s_section))
        tc_data = [["Ticker", "Name", "Position return", "Portfolio contribution"]]
        for h in top_contribs:
            tc_data.append([h["ticker"], h["name"], f"{h['return']*100:+.1f}%",
                            f"{h['contribution']*100:+.2f}%"])
        story.append(styled_table(tc_data, [0.12, 0.40, 0.24, 0.24]))
        story.append(Spacer(1, 8))

    if bottom_contribs:
        story.append(Paragraph("BOTTOM CONTRIBUTORS", s_section))
        bc_data = [["Ticker", "Name", "Position return", "Portfolio contribution"]]
        for h in bottom_contribs:
            bc_data.append([h["ticker"], h["name"], f"{h['return']*100:+.1f}%",
                            f"{h['contribution']*100:+.2f}%"])
        story.append(styled_table(bc_data, [0.12, 0.40, 0.24, 0.24]))

    if top_contribs or bottom_contribs:
        story.append(Paragraph(
            f"Position returns are measured from each holding's first to last "
            f"available close inside {year}; contributions are weight-multiplied "
            "returns. Holdings without price data in the year are not shown.",
            s_disclaimer))

    story.append(PageBreak())

    # Page 4: Model performance (ONLY when real walk-forward validation figures
    # exist; the old hardcoded 72% / 3.4% cards and the canned interpretive
    # sentence are gone) + Year Ahead.
    ma = d.get("model_accuracy")
    if ma:
        story.append(Paragraph("MODEL PERFORMANCE", s_section))
        story.append(Paragraph("How the forecasting engine validated", s_heading))
        story.append(metrics_row([
            metric_card(f"{ma['hit_rate']*100:.0f}%", "Directional accuracy", TEAL),
            metric_card(f"{ma['avg_error']*100:.1f}%", "Mean absolute error", SLATE),
            metric_card(escape(str(ma["best_model"])), "Winning model", NAVY),
        ]))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"These figures come from the engine's walk-forward validation tournament, "
            f"run on the portfolio's trailing price history at the time this report was "
            f"generated. Across <b>{int(ma.get('n_steps') or 0)}</b> validation points, "
            f"the winning model (<b>{escape(str(ma['best_model']))}</b>) matched the "
            f"direction of the next move <b>{ma['hit_rate']*100:.0f}%</b> of the time, "
            f"with a mean absolute forecast error of <b>{ma['avg_error']*100:.1f}%</b>. "
            f"They measure model validation on historical data, not realized forecast "
            f"accuracy over calendar {year}.",
            s_body
        ))
        if narrative.get("model_commentary"):
            story.append(Paragraph(escape(narrative["model_commentary"]), s_body_sm))

        # Model track record: the same directional accuracy placed against its
        # 95% confidence interval and the 50% coin-flip baseline, so a hit rate
        # near 50% is not read as a reliable edge (nor a real edge dismissed).
        tr = d.get("track_record") or {}
        if tr.get("hit_rate") is not None:
            verdict = ("statistically above the 50% coin-flip baseline"
                       if tr.get("beats_coinflip")
                       else "not statistically distinguishable from a 50% coin flip")
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                f"<b>Model track record.</b> Adjusting for sample size, the "
                f"{tr['hit_rate'] * 100:.0f}% directional accuracy over {tr['n_steps']} "
                f"validation steps carries a 95% confidence interval of "
                f"{tr['ci_low'] * 100:.0f}% to {tr['ci_high'] * 100:.0f}%, which is {verdict}. "
                f"Forecasting market direction is genuinely hard; treat any projection as one "
                f"input, not a certainty.",
                s_body_sm))
        story.append(Spacer(1, 14))

    # Year ahead: current measured risk state plus the AI narrative grounded in
    # it. The old canned macro themes are gone.
    story.append(Paragraph(f"{year + 1} OUTLOOK", s_section))
    story.append(Paragraph("Positioning context for the year ahead", s_heading))
    story.append(Paragraph(
        f"As of {d['report_date'].strftime('%B %d, %Y')}, the risk engine classifies "
        f"the portfolio's regime as <b>{escape(humanize_label(d.get('regime', 'Normal')))}</b> "
        f"with a fragility score of <b>{d.get('fragility_score', 0):.2f}</b> (current "
        f"volatility relative to its long-term median; above 1.5 is flagged fragile).",
        s_body))
    if narrative.get("year_ahead"):
        story.append(Paragraph(escape(narrative["year_ahead"]), s_body))
    story.append(Spacer(1, 8))

    if narrative.get("considerations"):
        story.append(Paragraph("CONSIDERATIONS", s_section))
        story.append(Paragraph("Model-derived observations to evaluate", s_subheading))
        for c in narrative["considerations"]:
            story.append(Paragraph(f"•  {escape(c)}", s_body_sm))
        story.append(Spacer(1, 8))

    # Advisor-authored adjustments passed through the API; never canned.
    proposed = [str(c) for c in (d.get("proposed_changes") or []) if str(c).strip()]
    if proposed:
        story.append(Paragraph("PROPOSED ADJUSTMENTS", s_section))
        story.append(Paragraph("Provided by your advisor", s_subheading))
        for i, change in enumerate(proposed, 1):
            story.append(Paragraph(f"<b>{i}.</b>  {escape(change)}", s_body))
        story.append(Spacer(1, 6))

    if any(narrative.get(k) for k in
           ("year_summary", "risk_commentary", "model_commentary",
            "year_ahead", "considerations")):
        story.append(Paragraph(
            "Narrative commentary in this review was AI-generated strictly from the "
            "measured figures shown in this document. It is informational only, is not "
            "investment advice, and lists options for the advisor's professional "
            "evaluation, not instructions to transact.",
            s_disclaimer))

    story.extend(standard_disclaimer(d["firm_name"], d["advisor_name"]))

    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return output_path
