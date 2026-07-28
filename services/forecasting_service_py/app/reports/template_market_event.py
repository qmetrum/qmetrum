"""
Template 3: MARKET EVENT REPORT
Purpose: Sent to clients during market turbulence (sell-offs, rate decisions,
geopolitical events). Shows the portfolio's REAL move through an event window
sliced from actual trading dates, a date-aligned benchmark when one is
available (omitted otherwise, never padded), and an outlook grounded in the
engine's actual forecast with an AI narrative layered on top when available.
Maps to: /reports/market-event.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image

from app.reports.report_styles import *


def _style_event_ax(ax, title):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDE1E6")
    ax.spines["bottom"].set_color("#DDE1E6")
    ax.tick_params(colors="#5A6270", labelsize=7.5)
    ax.grid(axis="y", color="#EEF0F3", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title(title, fontsize=10, fontweight="600", color="#1A1A2E", loc="left", pad=10)


def _fig_to_buf(fig):
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#FFFFFF", edgecolor="none", pad_inches=0.15)
    buf.seek(0)
    plt.close(fig)
    return buf


def make_event_impact_chart(dates, portfolio_vals, benchmark_vals, event_date,
                            event_name, benchmark_label=None):
    """Indexed performance through the REAL event window. The benchmark line
    is drawn only when a date-aligned series was supplied."""
    fig, ax = plt.subplots(figsize=(6.8, 2.8))
    _style_event_ax(ax, "Portfolio performance through the event window")

    ax.plot(dates, portfolio_vals, color="#0F8B6E", linewidth=1.5, label="Your portfolio")
    if benchmark_vals is not None:
        ax.plot(dates, benchmark_vals, color="#8B95A2", linewidth=1.2, linestyle="--",
                label=benchmark_label or "Benchmark")

    ax.axvline(event_date, color="#D85A30", linewidth=1.2, linestyle="-", alpha=0.8)
    ax.annotate(f" {event_name}", (event_date, max(portfolio_vals) * 0.99),
                fontsize=7.5, color="#D85A30", fontweight="600", va="top")

    ax.set_ylabel("Indexed (100 = window start)", fontsize=8, color="#5A6270")
    ax.legend(fontsize=7, loc="lower left", framealpha=0.9, edgecolor="#DDE1E6")
    fig.autofmt_xdate()
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %d"))
    return _fig_to_buf(fig)


def make_drawdown_comparison(portfolio_dd, benchmark_dd, dates, benchmark_label=None):
    """Drawdown inside the event window; benchmark drawn only when aligned
    benchmark data was supplied."""
    fig, ax = plt.subplots(figsize=(6.8, 1.8))
    _style_event_ax(ax, "Drawdown through the event window")

    ax.fill_between(dates, portfolio_dd, 0, color="#0F8B6E", alpha=0.15, label="Your portfolio")
    ax.plot(dates, portfolio_dd, color="#0F8B6E", linewidth=1.0)
    if benchmark_dd is not None:
        ax.fill_between(dates, benchmark_dd, 0, color="#C0392B", alpha=0.08,
                        label=benchmark_label or "Benchmark")
        ax.plot(dates, benchmark_dd, color="#C0392B", linewidth=0.8, linestyle="--")

    ax.set_ylabel("Drawdown (%)", fontsize=8, color="#5A6270")
    ax.legend(fontsize=7, loc="lower left", framealpha=0.9, edgecolor="#DDE1E6")
    fig.autofmt_xdate()
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %d"))
    return _fig_to_buf(fig)


def generate_market_event_report(output_path, data):
    """
    data = {
        "client_name", "advisor_name", "firm_name", "report_date",
        "portfolio_value": float,
        "event_name": str, "event_date": datetime, "event_summary": str,
        # Measured from the last close BEFORE the event through the window end.
        "portfolio_return_event": float,           # e.g. -0.032
        "benchmark_return_event": float or None,   # None -> benchmark omitted everywhere
        "benchmark_label": str or None,
        "portfolio_drawdown_peak": float,          # deepest in-window drawdown, e.g. -0.041
        "regime": str,
        "fragility_score": float,
        "holdings_impact": [{"ticker", "name", "return" (float or None),
                             "contribution" (float or None)}],
        # The engine's ACTUAL forecast facts (None -> outlook says none available).
        "forecast_facts": {"model", "horizon_days", "return_pct",
                           "band_pct" (float or None)} or None,
        # Every downside measure on ONE dollar basis, to place beside the
        # measured event impact (None -> the "Risk in one view" box shows only
        # the event impact). The worst-scenario row is absent for this briefing
        # (no simulated scenario set is supplied).
        "risk_reconciliation": {"var_1d_pct","var_1d_dollars","max_drawdown_pct",
                                "max_drawdown_dollars","worst_scenario",
                                "worst_scenario_dollars","forecast_downside_pct",
                                "forecast_downside_dollars","fragility_label",
                                "flags"} or None,
        # Directional accuracy with a 95% CI and the coin-flip baseline, so the
        # forward outlook is not read as more reliable than validation supports
        # (None -> the track-record line is omitted).
        "track_record": {"hit_rate","n_steps","ci_low","ci_high",
                         "beats_coinflip","best_model"} or None,
        # AI narrative grounded in the numbers above (None -> numbers-only).
        "narrative": {"event_commentary", "benchmark_commentary", "risk_synthesis",
                      "outlook", "considerations"} or None,
        # REAL trading-date window sliced around the event.
        "dates": [datetime], "portfolio_index": [float],
        "benchmark_index": [float] or None,
        "portfolio_dd": [float], "benchmark_dd": [float] or None,
    }
    """
    d = data
    narrative = d.get("narrative") or {}
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                            topMargin=60, bottomMargin=60, leftMargin=54, rightMargin=54)
    story = []

    dates = d["dates"]
    window_start, window_end = dates[0], dates[-1]
    has_bench = (d.get("benchmark_return_event") is not None
                 and d.get("benchmark_index") is not None)
    bench_label = d.get("benchmark_label") or "Benchmark"

    port_ret_str = f"{d['portfolio_return_event']*100:+.1f}%"
    bench_ret_str = (f"{d['benchmark_return_event']*100:+.1f}%" if has_bench else "n/a")

    cover_metrics = [("EVENT IMPACT", port_ret_str)]
    if has_bench:
        cover_metrics.append(("BENCHMARK", bench_ret_str))
    else:
        cover_metrics.append(("PORTFOLIO VALUE", f"${d['portfolio_value']:,.0f}"))
    cover_metrics += [
        ("REGIME", humanize_label(d["regime"])),
        ("FRAGILITY", f"{d['fragility_score']:.2f}"),
    ]

    def on_first(c, doc_obj):
        draw_cover_page(c, doc_obj,
            firm_name=d["firm_name"], client_name=d["client_name"],
            report_date=d["report_date"],
            report_type="MARKET EVENT BRIEFING",
            subtitle=f"{d['event_name']}: {d['event_date'].strftime('%B %d, %Y')}",
            cover_metrics=cover_metrics)

    def on_later(c, doc_obj):
        draw_header_footer(c, doc_obj, firm_name=d["firm_name"], client_name=d["client_name"],
                           report_date=d["report_date"], advisor_name=d["advisor_name"])

    story.append(Spacer(1, 1))
    story.append(PageBreak())

    # Page 2: Event Summary
    story.append(Paragraph("EVENT SUMMARY", s_section))
    story.append(Paragraph(escape(d["event_name"]), s_heading))
    story.append(Paragraph(escape(d["event_summary"]), s_body))
    story.append(Spacer(1, 4))

    # Headline metrics
    if has_bench:
        outperformance = d["portfolio_return_event"] - d["benchmark_return_event"]
        story.append(metrics_row([
            metric_card(port_ret_str, "Your portfolio",
                        TEAL if outperformance > 0 else CORAL),
            metric_card(bench_ret_str, f"{bench_label} benchmark", SLATE),
            metric_card(f"{outperformance*100:+.1f}%", "Relative performance",
                        GREEN if outperformance > 0 else RED),
            metric_card(humanize_label(d["regime"]), "Current regime",
                        AMBER if d["regime"] != "Normal" else TEAL),
        ]))
    else:
        story.append(metrics_row([
            metric_card(port_ret_str, "Your portfolio",
                        TEAL if d["portfolio_return_event"] >= 0 else CORAL),
            metric_card(f"{d['portfolio_drawdown_peak']*100:.1f}%", "Peak drawdown", CORAL),
            metric_card(humanize_label(d["regime"]), "Current regime",
                        AMBER if d["regime"] != "Normal" else TEAL),
            metric_card(f"{d['fragility_score']:.2f}", "Fragility score", SLATE),
        ]))
    story.append(Spacer(1, 8))

    # Measured-impact callout: states the computed numbers, whatever their
    # direction; it never asserts that diversification "worked as designed".
    dollar_move = d["portfolio_return_event"] * d["portfolio_value"]
    move_sentence = (
        f"<b>Measured from the last close before the event through "
        f"{window_end.strftime('%B %d, %Y')}, the portfolio moved "
        f"{d['portfolio_return_event']*100:+.2f}%</b>, roughly "
        f"{'-' if dollar_move < 0 else '+'}${abs(dollar_move):,.0f} on a portfolio of "
        f"${d['portfolio_value']:,.0f}."
    )
    if has_bench:
        rel = d["portfolio_return_event"] - d["benchmark_return_event"]
        if abs(rel) < 0.0005:
            tail = (f" Over the same window the {bench_label} benchmark moved "
                    f"{d['benchmark_return_event']*100:+.2f}%, essentially in line "
                    f"with the portfolio.")
        else:
            tail = (f" Over the same window the {bench_label} benchmark moved "
                    f"{d['benchmark_return_event']*100:+.2f}%: the portfolio "
                    f"{'outperformed' if rel > 0 else 'underperformed'} it by "
                    f"{abs(rel)*100:.1f} percentage points.")
        if rel >= 0:
            story.append(callout_box(move_sentence + tail))
        else:
            story.append(callout_box(move_sentence + tail,
                                     bg_color=AMBER_LIGHT, border_color=AMBER))
    else:
        story.append(callout_box(
            move_sentence + " No date-aligned benchmark data was available for this "
            "window, so no benchmark comparison is shown.",
            bg_color=BLUE_LIGHT, border_color=BLUE,
        ))

    if narrative.get("event_commentary"):
        story.append(Spacer(1, 6))
        story.append(Paragraph("What happened", s_subheading))
        story.append(Paragraph(escape(narrative["event_commentary"]), s_body_sm))

    story.append(Spacer(1, 8))

    # Event window chart (real trading dates)
    story.append(Paragraph("EVENT WINDOW", s_section))
    story.append(Paragraph(
        f"{len(dates)} trading days: {window_start.strftime('%b %d, %Y')} to "
        f"{window_end.strftime('%b %d, %Y')}", s_subheading))
    impact_buf = make_event_impact_chart(
        dates, d["portfolio_index"],
        d["benchmark_index"] if has_bench else None,
        d["event_date"], d["event_name"], benchmark_label=bench_label)
    story.append(Image(impact_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.41))
    story.append(Paragraph(
        "Dates on this chart are the portfolio's actual trading days. Impact figures "
        "in this briefing are measured from the last close before the event through "
        f"{window_end.strftime('%B %d, %Y')}.",
        s_disclaimer,
    ))

    story.append(PageBreak())

    # Page 3: Detailed impact
    story.append(Paragraph("DRAWDOWN ANALYSIS", s_section))
    story.append(Paragraph("How deep did it go?", s_heading))
    dd_buf = make_drawdown_comparison(
        d["portfolio_dd"],
        d["benchmark_dd"] if has_bench else None,
        dates, benchmark_label=bench_label)
    story.append(Image(dd_buf, width=PAGE_WIDTH, height=PAGE_WIDTH * 0.26))
    story.append(Paragraph(
        f"The portfolio's deepest decline within this window was "
        f"{d['portfolio_drawdown_peak']*100:.1f}% below its running peak.",
        s_body_sm))
    if narrative.get("benchmark_commentary"):
        story.append(Paragraph(escape(narrative["benchmark_commentary"]), s_body_sm))
    story.append(Spacer(1, 10))

    # Holdings impact table
    story.append(Paragraph("HOLDINGS IMPACT", s_section))
    story.append(Paragraph("Contribution by position", s_subheading))
    hi_data = [["Ticker", "Name", "Position return", "Portfolio contribution"]]
    for h in d["holdings_impact"]:
        hi_data.append([
            h["ticker"], h["name"],
            f"{h['return']*100:+.1f}%" if h.get("return") is not None else "n/a",
            f"{h['contribution']*100:+.2f}%" if h.get("contribution") is not None else "n/a",
        ])
    story.append(styled_table(hi_data, [0.12, 0.40, 0.24, 0.24]))
    notes = ["Position returns cover the same span as the headline event impact: from "
             "the last close before the event through the end of the window shown above. "
             "Contributions are weight-multiplied returns."]
    if any(h.get("return") is None for h in d["holdings_impact"]):
        notes.append("Positions marked n/a had no price data available inside the event window.")
    story.append(Paragraph(" ".join(notes), s_disclaimer))
    story.append(Spacer(1, 12))

    # Risk in one view: the measured event impact placed on the SAME dollar
    # basis as the portfolio's standing risk measures (1-day VaR, realized
    # maximum drawdown) and, when the model supplied an interval, the forecast
    # downside, so a client can see how this event compares to what the
    # portfolio already carries rather than reading each number in isolation.
    # Any internal-consistency flag is surfaced plainly. The event-impact row is
    # always shown; the other rows appear only when the reconciliation supplied
    # a real figure (omit-when-None).
    rr = d.get("risk_reconciliation") or {}
    event_ret = d["portfolio_return_event"]
    event_dollars = event_ret * d["portfolio_value"]

    def _dol(v):
        return f"{'+' if v > 0 else '-'}${abs(v):,.0f}" if v is not None else "n/a"

    def _pf(v):   # fractional inputs (event move, VaR, realized drawdown)
        return f"{v * 100:+.2f}%" if v is not None else "n/a"

    def _pp(v):   # already-percent inputs (worst scenario, forecast low end)
        return f"{v:+.1f}%" if v is not None else "n/a"

    story.append(Paragraph("RISK IN ONE VIEW", s_section))
    story.append(Paragraph("This event against the portfolio's standing risk", s_subheading))
    rv_rows = [["Downside measure", "Percentage", "Dollar impact"]]
    rv_rows.append(["Measured event impact", _pf(event_ret), _dol(event_dollars)])
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
    if narrative.get("risk_synthesis"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(escape(narrative["risk_synthesis"]), s_body_sm))
    recon_note = (
        "The event impact is measured from the last close before the event through the end "
        "of the window. The 1-day Value at Risk and realized maximum drawdown are the "
        "portfolio's standing risk measures over the engine's analysis window, not figures "
        "from this event. Dollar figures use the portfolio value shown on the cover."
    )
    if rr.get("fragility_label"):
        recon_note += f" Fragility reading: {escape(str(rr['fragility_label']))}."
    story.append(Paragraph(recon_note, s_disclaimer))
    for fl in rr.get("flags", []):
        story.append(Paragraph(f"Note: {escape(str(fl))}", s_disclaimer))
    story.append(Spacer(1, 12))

    # Forward outlook: only the engine's actual outputs, never a canned
    # recovery sentence. The AI narrative (when available) is grounded in the
    # same facts and clearly disclaimed below.
    story.append(Paragraph("FORWARD OUTLOOK", s_section))
    story.append(Paragraph("What the models show from here", s_subheading))
    story.append(Paragraph(
        f"The risk engine classifies the current regime as <b>{escape(humanize_label(d['regime']))}</b> "
        f"with a fragility score of <b>{d['fragility_score']:.2f}</b> (current volatility "
        f"relative to its long-term median; above 1.5 is flagged fragile).",
        s_body))
    ff = d.get("forecast_facts")
    if ff:
        band_note = (
            f", with a 95% interval width of {ff['band_pct']:.1f}% of the median at the horizon"
            if ff.get("band_pct") is not None
            else "; the model produced no confidence interval for this run"
        )
        story.append(Paragraph(
            f"The winning forecast model ({escape(str(ff['model']))}) projects a median "
            f"return of <b>{ff['return_pct']:+.1f}%</b> over the next {ff['horizon_days']} "
            f"trading days from the latest close{band_note}.",
            s_body))
    else:
        story.append(Paragraph(
            "No model forecast was available for this run, so no projection is shown.",
            s_body))

    # Model track record (directional accuracy). Suppressed by default:
    # daily directional accuracy is ~coin-flip for any honest forecaster and
    # reads as unflattering without being meaningful. Set show_track_record to
    # re-enable.
    tr = d.get("track_record") or {}
    if d.get("show_track_record") and tr.get("hit_rate") is not None:
        verdict = ("statistically above the 50% coin-flip baseline"
                   if tr.get("beats_coinflip")
                   else "not statistically distinguishable from a 50% coin flip")
        story.append(Paragraph(
            f"<b>Model track record.</b> On walk-forward validation the winning model "
            f"({escape(str(tr.get('best_model', 'ensemble')))}) called direction correctly "
            f"{tr['hit_rate'] * 100:.0f}% of the time over {tr['n_steps']} steps "
            f"(95% confidence interval {tr['ci_low'] * 100:.0f}% to {tr['ci_high'] * 100:.0f}%), "
            f"{verdict}. Treat the projection above as one input, not a certainty.",
            s_body_sm))

    if narrative.get("outlook"):
        story.append(Paragraph(escape(narrative["outlook"]), s_body_sm))
    story.append(Spacer(1, 6))

    # Considerations: model-derived options for the advisor to evaluate,
    # replacing the old canned action items. Omitted when no narrative exists.
    if narrative.get("considerations"):
        story.append(Paragraph("CONSIDERATIONS", s_section))
        story.append(Paragraph("Model-derived observations to evaluate", s_subheading))
        for c in narrative["considerations"]:
            story.append(Paragraph(f"•  {escape(c)}", s_body_sm))

    if any(narrative.get(k) for k in
           ("event_commentary", "benchmark_commentary", "risk_synthesis",
            "outlook", "considerations")):
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Narrative commentary in this briefing was AI-generated strictly from the "
            "measured event-window figures and model outputs shown in this document. It is "
            "informational only, is not investment advice, and lists options for the "
            "advisor's professional evaluation, not instructions to transact.",
            s_disclaimer))

    story.extend(standard_disclaimer(d["firm_name"], d["advisor_name"]))

    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return output_path
