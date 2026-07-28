"""Report narrator.

Input: the REAL facts a PDF report is about to render (risk metrics, forecast
levels, scenario facts, holdings). Output: the written analysis layer of the
report, one batched LLM call: an executive summary, a commentary paragraph per
section explaining what the numbers mean and why they matter, and a short list
of considerations (possible moves for the ADVISOR to evaluate, hedged and
clearly labeled, never directives).

Style contract: plain professional English a client could read, numbers-first,
and never any em or en dashes (rendered PDFs must not contain them).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel

from app.agents.llm import generate, LlmResult


SYSTEM_PROMPT = """You are a buy-side risk analyst writing the narrative layer of a portfolio risk report for a financial advisor. You are given ONLY real computed facts about one portfolio. Write:

- executive_summary: 3-5 sentences. Lead with how the portfolio actually performed over the headline period and versus its benchmark if supplied (the number the client cares about first), then its risk posture (volatility, drawdown, regime), then the single most important takeaway.
- performance_commentary: 2-4 sentences (only if performance facts are supplied, else empty string). How the portfolio did across the periods shown, how that compares to the benchmark (outperformed or lagged, by how much), and which holdings drove the result per the attribution, including an honest note if a large residual means much of the return is unexplained by the listed positions.
- forecast_commentary: 2-4 sentences. What the median forecast path implies in return terms and, if an interval range is supplied, the plain dollar range it spans, plus what the current regime means for reliability.
- risk_commentary: 3-5 sentences. Interpret the risk table: what VaR/CVaR mean in dollar terms for THIS portfolio value, whether the Sharpe/Sortino pairing suggests the return is worth the risk, what the drawdown and fragility numbers say, and why. If a risk-contribution decomposition is supplied, name which holding contributes the MOST to portfolio volatility and note where its risk share diverges from its weight (a small position can carry outsized risk); do not merely assert dominance, cite the contribution number.
- risk_synthesis: 2-4 sentences (only if a risk reconciliation is supplied, else empty string). Tie the separate downside measures into ONE picture on a common dollar basis: the 1-day VaR, the worst simulated scenario, the realized maximum drawdown, and the forecast downside. State them in dollars for this portfolio, say which is the most severe, and if a consistency flag is supplied, surface it plainly (for example that the stress set looks milder than the drawdown already experienced).
- scenario_commentary: 2-4 sentences interpreting the scenario set as a whole (only if scenario facts are supplied): where the real downside comes from, and what the adversarial case reveals. Empty string if no scenarios supplied.
- holdings_commentary: 2-3 sentences. Concentration, diversification, and what dominates the risk given the weights.
- considerations: 2-5 short bullets. Possible moves the advisor could evaluate, each tied to a specific number in the facts (for example trimming a concentrated position, hedging a fat tail the scenarios expose, or revisiting exposure given fragility). Phrase each as an option to evaluate, never an instruction.

Rules:
- Use ONLY the supplied numbers. Never invent figures, benchmarks, or events.
- Convert percentages to dollar terms using the portfolio value where it helps.
- Plain professional English. Expand jargon on first use.
- These are model-derived observations for a professional to evaluate, not advice. No promises, no certainty language.
- NEVER use em dashes or en dashes anywhere in the text. Use commas, colons, or periods instead.
- Do not overstate. Match the framework's own thresholds: a fragility below 1.5 is NOT "fragile" or "disproportionate sensitivity"; reflect the supplied fragility description. A directional accuracy whose confidence interval includes 50% is NOT a reliable edge; say so honestly.

Return JSON with exactly those fields (performance_commentary and risk_synthesis included).
"""


class ReportNarrative(BaseModel):
    executive_summary: str
    performance_commentary: str = ""
    forecast_commentary: str
    risk_commentary: str
    risk_synthesis: str = ""
    scenario_commentary: str
    holdings_commentary: str
    considerations: list[str]


def _strip_dashes(text: str) -> str:
    """Belt and braces: the prompt forbids em/en dashes, but never trust a
    model with typography. Replace any that slip through."""
    return text.replace(" — ", ", ").replace("—", ", ") \
               .replace(" – ", ", ").replace("–", "-")


def _fmt_money(v: float) -> str:
    sign = "-" if v < 0 else ""
    mag = abs(v)
    if mag >= 1_000_000:
        return f"{sign}${mag / 1_000_000:.2f}M"
    if mag >= 1_000:
        return f"{sign}${mag / 1_000:.0f}K"
    return f"{sign}${mag:,.0f}"


def _pct(v: Optional[float], scale: float = 100.0) -> str:
    if v is None:
        return "n/a"
    return f"{v * scale:+.2f}%"


def build_prompt(facts: dict[str, Any]) -> str:
    rm = facts.get("risk_metrics") or {}
    lines = [
        f"Portfolio: {facts.get('portfolio_name', 'Portfolio')}",
        f"Portfolio value: {_fmt_money(float(facts.get('portfolio_value', 0)))}",
        f"Horizon: {facts.get('horizon_days', 90)} days",
        "",
        "Risk metrics:",
        f"  annualized volatility {_pct(rm.get('annualized_vol'))}, "
        f"Sharpe {rm.get('sharpe_ratio', 0):.2f}, Sortino {rm.get('sortino_ratio', 0):.2f}",
        f"  VaR95 1-day {_pct(rm.get('var_95_daily'))}, CVaR95 {_pct(rm.get('cvar_95_daily'))}, "
        f"max drawdown {_pct(rm.get('max_drawdown'))}",
        f"  beta {rm.get('beta', 0):.2f}, fragility {rm.get('fragility_score', 0):.2f}, "
        f"regime {str(rm.get('regime', 'Normal')).replace('_', ' ')}",
    ]
    ra = facts.get("risk_attribution") or {}
    if ra.get("rows"):
        lines += ["", f"Risk contribution (portfolio volatility {ra['portfolio_vol'] * 100:.1f}%, "
                      f"{ra.get('n_obs', 0)} obs; risk share vs weight):"]
        for r in ra["rows"][:8]:
            lines.append(f"  {r['ticker']}: weight {r['weight'] * 100:.0f}%, risk share {r['risk_pct'] * 100:.0f}%")
    rr = facts.get("risk_reconciliation") or {}
    if rr.get("var_1d_dollars") is not None or rr.get("worst_scenario_dollars") is not None:
        lines += ["", "Downside on one basis (dollars for this portfolio):"]
        if rr.get("var_1d_dollars") is not None:
            lines.append(f"  1-day VaR95: {_fmt_money(rr['var_1d_dollars'])} ({_pct(rr.get('var_1d_pct'))})")
        if rr.get("worst_scenario_dollars") is not None:
            lines.append(f"  worst scenario ({(rr.get('worst_scenario') or {}).get('name')}): {_fmt_money(rr['worst_scenario_dollars'])}")
        if rr.get("max_drawdown_dollars") is not None:
            lines.append(f"  realized max drawdown: {_fmt_money(rr['max_drawdown_dollars'])} ({_pct(rr.get('max_drawdown_pct'))})")
        if rr.get("forecast_downside_dollars") is not None:
            lines.append(f"  forecast downside (low end): {_fmt_money(rr['forecast_downside_dollars'])}")
        lines.append(f"  fragility reading: {rr.get('fragility_label', 'n/a')}")
        for fl in rr.get("flags", []):
            lines.append(f"  CONSISTENCY FLAG: {fl}")
    tr = facts.get("track_record") or {}
    if tr.get("hit_rate") is not None:
        lines += ["", "Forecast track record (walk-forward validation):",
                  f"  directional accuracy {tr['hit_rate'] * 100:.0f}% over {tr['n_steps']} steps, "
                  f"95% CI {tr['ci_low'] * 100:.0f}% to {tr['ci_high'] * 100:.0f}%, coin-flip baseline 50%, "
                  f"{'statistically above' if tr.get('beats_coinflip') else 'NOT distinguishable from'} chance"]
    perf = facts.get("performance") or {}
    if perf.get("periods"):
        lines += ["", f"Realized performance (benchmark: {perf.get('benchmark_label') or 'none available'}):"]
        for p in perf["periods"]:
            b = p.get("benchmark")
            rel = p.get("relative")
            lines.append(
                f"  {p['label']}: portfolio {p['portfolio'] * 100:+.1f}%"
                + (f", benchmark {b * 100:+.1f}%, relative {rel * 100:+.1f}pp" if b is not None else ", benchmark n/a")
            )
        attr = perf.get("attribution") or []
        if attr:
            lines.append(f"  attribution over {perf.get('attribution_window')} (weight x return):")
            for c in attr[:8]:
                lines.append(f"    {c['ticker']}: weight {c['weight'] * 100:.0f}%, return {c['return'] * 100:+.1f}%, contribution {c['contribution'] * 100:+.1f}pp")
            if perf.get("attribution_residual") is not None:
                lines.append(f"    unexplained residual: {perf['attribution_residual'] * 100:+.1f}pp (return not captured by the listed positions)")
    fc = facts.get("forecast") or {}
    if fc.get("return_pct") is not None:
        line = f"  projected return over the horizon {fc['return_pct']:+.2f}%"
        if fc.get("range_low_pct") is not None and fc.get("range_high_pct") is not None:
            line += f", likely range about {fc['range_low_pct']:+.1f}% to {fc['range_high_pct']:+.1f}%"
        else:
            line += ", no model interval available"
        lines += ["", "Forecast (median path):", line]
    scen = facts.get("scenarios") or []
    if scen:
        lines += ["", "Scenario facts (simulated, vs the base scenario):"]
        for s in scen:
            lines.append(
                f"  {s['name']}: return {s['return_pct']:+.1f}%"
                + (f", dollar impact {_fmt_money(s['dollar_impact'])}" if s.get("dollar_impact") is not None else "")
                + (f", pessimistic tail {s['downside_pct']:+.1f}%" if s.get("downside_pct") is not None else "")
            )
    holds = facts.get("holdings") or []
    if holds:
        lines += ["", "Holdings (ticker, weight, sector):"]
        for h in holds[:20]:
            lines.append(f"  {h.get('ticker')}: {float(h.get('weight', 0)) * 100:.0f}%, {h.get('sector', 'n/a')}")
    return f"{SYSTEM_PROMPT}\n\n" + "\n".join(lines) + "\n\nWrite the narrative now as JSON."


def run(*, facts: dict[str, Any]) -> tuple[dict[str, Any], LlmResult]:
    prompt = build_prompt(facts)
    rm = facts.get("risk_metrics") or {}
    result = generate(
        prompt,
        agent_name="report_narrator",
        schema=ReportNarrative,
        cache_key_extra={
            "portfolio_name": facts.get("portfolio_name"),
            "portfolio_value": round(float(facts.get("portfolio_value", 0)), 2),
            "vol": round(float(rm.get("annualized_vol") or 0), 4),
            "var": round(float(rm.get("var_95_daily") or 0), 4),
            "forecast_return": round(float((facts.get("forecast") or {}).get("return_pct") or 0), 2),
            "perf": [
                {"w": p["label"], "r": round(float(p["portfolio"]), 4)}
                for p in ((facts.get("performance") or {}).get("periods") or [])
            ],
            "scenarios": [
                {"name": s["name"], "ret": round(float(s.get("return_pct") or 0), 2)}
                for s in (facts.get("scenarios") or [])
            ],
        },
    )
    try:
        parsed = json.loads(result.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"report narrator returned malformed JSON: {exc}")
    if not isinstance(parsed, dict):
        raise ValueError("report narrator returned malformed JSON: not an object")
    out = {
        k: _strip_dashes(str(parsed.get(k) or ""))
        for k in ("executive_summary", "performance_commentary", "forecast_commentary",
                  "risk_commentary", "risk_synthesis", "scenario_commentary", "holdings_commentary")
    }
    out["considerations"] = [
        _strip_dashes(str(c)) for c in (parsed.get("considerations") or []) if str(c).strip()
    ]
    return out, result


# Rebalancing proposal narrator: same contract (one batched call, grounded only
# in supplied facts, options-to-evaluate framing), specialized for the
# current-vs-proposed comparison a rebalancing report is about.

REBALANCING_SYSTEM_PROMPT = """You are a buy-side risk analyst writing the narrative layer of a portfolio rebalancing proposal for a financial advisor. You are given ONLY real computed facts: the current allocation's risk metrics, the proposed allocation's risk metrics, the exact metric changes, and the trade list that moves one to the other. Write:

- proposal_summary: 3-5 sentences. What the proposal changes at the allocation level, what it does to the risk profile (volatility, drawdown, VaR, Sharpe, Sortino), and the single most important trade-off. Report the ACTUAL direction of every change: when a metric worsens under the proposal, say so plainly. If a risk-contribution decomposition for the CURRENT allocation is supplied, name the holding that contributes the MOST to the current book's volatility and note where its risk share diverges from its weight (a small position can carry outsized risk); when the PROPOSED allocation's decomposition is also supplied, say how the proposal shifts that concentration. Cite the risk-share numbers, do not merely assert dominance.
- trade_commentary: 2-4 sentences on the trade set: where money moves from and to, which trades dominate by dollar value, and what the shift means for concentration.
- considerations: 2-5 short bullets. Points the advisor could evaluate before executing, each tied to a specific number in the facts (for example a metric that moves the wrong way, one trade dominating the dollar flow, or execution friction on the amounts shown). Phrase each as an option to evaluate, never an instruction.

Rules:
- Use ONLY the supplied numbers. Never invent figures, prices, tax rates, or events.
- Never claim the proposal improves a metric unless the supplied change actually improves it.
- Convert percentages to dollar terms using the portfolio value where it helps.
- Plain professional English. Expand jargon on first use.
- These are model-derived observations for a professional to evaluate, not advice. No promises, no certainty language.
- NEVER use em dashes or en dashes anywhere in the text. Use commas, colons, or periods instead.

Return JSON with exactly those three fields.
"""


class RebalancingNarrative(BaseModel):
    proposal_summary: str
    trade_commentary: str
    considerations: list[str]


def _metric_block(label: str, m: dict[str, Any]) -> list[str]:
    return [
        f"{label}:",
        f"  annualized volatility {_pct(m.get('annualized_vol'))}, "
        f"Sharpe {float(m.get('sharpe') or 0):.2f}, Sortino {float(m.get('sortino') or 0):.2f}",
        f"  VaR95 1-day {_pct(m.get('var_95'))}, max drawdown {_pct(m.get('max_drawdown'))}",
    ]


def build_rebalancing_prompt(facts: dict[str, Any]) -> str:
    cm = facts.get("current_metrics") or {}
    pm = facts.get("proposed_metrics") or {}

    def _delta(key: str, scale: float = 100.0, suffix: str = "pp", nd: int = 2) -> str:
        c, p = cm.get(key), pm.get(key)
        if c is None or p is None:
            return "n/a"
        return f"{(float(p) - float(c)) * scale:+.{nd}f}{suffix}"

    lines = [
        f"Portfolio: {facts.get('portfolio_name', 'Portfolio')}",
        f"Portfolio value: {_fmt_money(float(facts.get('portfolio_value', 0)))}",
        "",
    ]
    lines += _metric_block("Current allocation metrics", cm)
    lines += _metric_block("Proposed allocation metrics", pm)
    lines += [
        "Changes (proposed minus current):",
        f"  volatility {_delta('annualized_vol')}, VaR95 {_delta('var_95')}, "
        f"max drawdown {_delta('max_drawdown')}",
        f"  Sharpe {_delta('sharpe', scale=1.0, suffix='')}, "
        f"Sortino {_delta('sortino', scale=1.0, suffix='')}",
    ]
    ra = facts.get("risk_attribution") or {}
    if ra.get("rows"):
        lines += ["", f"Risk contribution by holding, CURRENT allocation (annualized "
                      f"volatility {ra['portfolio_vol'] * 100:.1f}%, {ra.get('n_obs', 0)} obs; "
                      f"risk share vs weight, sorted by risk share):"]
        for r in ra["rows"][:8]:
            lines.append(f"  {r['ticker']}: weight {r['weight'] * 100:.0f}%, "
                         f"risk share {r['risk_pct'] * 100:.0f}%")
    pra = facts.get("proposed_risk_attribution") or {}
    if pra.get("rows"):
        lines += ["", f"Risk contribution by holding, PROPOSED allocation (annualized "
                      f"volatility {pra['portfolio_vol'] * 100:.1f}%, {pra.get('n_obs', 0)} obs; "
                      f"risk share vs weight):"]
        for r in pra["rows"][:8]:
            lines.append(f"  {r['ticker']}: weight {r['weight'] * 100:.0f}%, "
                         f"risk share {r['risk_pct'] * 100:.0f}%")
    trades = facts.get("trades") or []
    if trades:
        lines += ["", "Trades (dollar values at the stated portfolio value):"]
        for t in trades:
            row = (
                f"  {t.get('ticker')}: {t.get('action')}, weight "
                f"{float(t.get('from_weight') or 0) * 100:.0f}% -> "
                f"{float(t.get('to_weight') or 0) * 100:.0f}%"
            )
            if float(t.get("value") or 0) > 0:
                row += f", {_fmt_money(float(t['value']))}"
            lines.append(row)
    scen = facts.get("scenarios") or []
    if scen:
        lines += ["", "Scenario stress comparison (simulated median return vs each "
                      "allocation's base scenario; no probabilities are modeled):"]
        for s in scen:
            lines.append(
                f"  {s['name']}: current {float(s.get('current_return_pct') or 0):+.1f}%, "
                f"proposed {float(s.get('proposed_return_pct') or 0):+.1f}%"
            )
    rationale = str(facts.get("rationale") or "").strip()
    if rationale:
        lines += ["", "Advisor's stated rationale (verbatim, context only):", f"  {rationale}"]
    return f"{REBALANCING_SYSTEM_PROMPT}\n\n" + "\n".join(lines) + "\n\nWrite the narrative now as JSON."


def run_rebalancing(*, facts: dict[str, Any]) -> tuple[dict[str, Any], LlmResult]:
    prompt = build_rebalancing_prompt(facts)
    cm = facts.get("current_metrics") or {}
    pm = facts.get("proposed_metrics") or {}
    ra = facts.get("risk_attribution") or {}
    pra = facts.get("proposed_risk_attribution") or {}
    result = generate(
        prompt,
        agent_name="rebalancing_narrator",
        schema=RebalancingNarrative,
        cache_key_extra={
            "portfolio_name": facts.get("portfolio_name"),
            "portfolio_value": round(float(facts.get("portfolio_value", 0)), 2),
            "current_vol": round(float(cm.get("annualized_vol") or 0), 4),
            "proposed_vol": round(float(pm.get("annualized_vol") or 0), 4),
            "current_sharpe": round(float(cm.get("sharpe") or 0), 3),
            "proposed_sharpe": round(float(pm.get("sharpe") or 0), 3),
            "risk_share_top": (round(float(ra["rows"][0]["risk_pct"]), 3)
                               if ra.get("rows") else None),
            "proposed_risk_share_top": (round(float(pra["rows"][0]["risk_pct"]), 3)
                                        if pra.get("rows") else None),
            "trades": [
                {"t": t.get("ticker"), "a": t.get("action"),
                 "w": round(float(t.get("to_weight") or 0), 4)}
                for t in (facts.get("trades") or [])
            ],
            "scenarios": [
                {"name": s["name"],
                 "c": round(float(s.get("current_return_pct") or 0), 2),
                 "p": round(float(s.get("proposed_return_pct") or 0), 2)}
                for s in (facts.get("scenarios") or [])
            ],
        },
    )
    try:
        parsed = json.loads(result.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"rebalancing narrator returned malformed JSON: {exc}")
    if not isinstance(parsed, dict):
        raise ValueError("rebalancing narrator returned malformed JSON: not an object")
    out = {
        k: _strip_dashes(str(parsed.get(k) or ""))
        for k in ("proposal_summary", "trade_commentary")
    }
    out["considerations"] = [
        _strip_dashes(str(c)) for c in (parsed.get("considerations") or []) if str(c).strip()
    ]
    return out, result


# Market event narrator: same contract (one batched call, grounded only in
# supplied facts, options-to-evaluate framing), specialized for what happened
# to one portfolio through one REAL event window and what the engine's actual
# forecast says from here.

MARKET_EVENT_SYSTEM_PROMPT = """You are a buy-side risk analyst writing the narrative layer of a market event briefing for a financial advisor's client. You are given ONLY real computed facts about one portfolio through one event window: the portfolio's move measured from the last close before the event, its peak drawdown inside the window, per-holding returns and weighted contributions, optionally the same figures for a benchmark, the current volatility regime, and optionally the engine's actual forecast. Write:

- event_commentary: 3-5 sentences. What happened to THIS portfolio through the event window: the move since the last close before the event, how deep the peak drawdown went, and which holdings drove or cushioned the result. Use dollar terms via the portfolio value where it helps.
- benchmark_commentary: 2-3 sentences comparing the portfolio's event-window move and drawdown against the benchmark figures supplied. Empty string if no benchmark facts are supplied.
- risk_synthesis: 2-4 sentences (only if a risk reconciliation is supplied, else empty string). Tie the event-window move together with the portfolio's standing downside measures on ONE common dollar basis: the 1-day VaR, the realized maximum drawdown, and the forecast downside where supplied. State them in dollars for this portfolio, say which is the most severe, and put the event impact in that context (for example whether this event stayed within or exceeded the portfolio's realized maximum drawdown already seen). If a consistency flag is supplied, surface it plainly.
- outlook: 2-4 sentences grounded ONLY in the supplied forecast and regime facts: what the model's median path implies over the stated horizon in return terms, what the interval width says about confidence, and what the regime and fragility score mean for reliability. If no forecast facts are supplied, say that a model forecast is not available for this run and describe only the regime and fragility facts.
- considerations: 2-5 short bullets. Possible moves the advisor could evaluate, each tied to a specific number in the facts (for example a holding whose event return dominated the loss, a fragility score near the 1.5 threshold, or a wide forecast interval). Phrase each as an option to evaluate, never an instruction.

Rules:
- Use ONLY the supplied numbers. Never invent figures, dates, causes, or market details beyond the event description given.
- Never claim a recovery or a further decline unless the supplied forecast facts actually show one.
- Convert percentages to dollar terms using the portfolio value where it helps.
- Plain professional English. Expand jargon on first use.
- These are model-derived observations for a professional to evaluate, not advice. No promises, no certainty language.
- NEVER use em dashes or en dashes anywhere in the text. Use commas, colons, or periods instead.

Return JSON with exactly those five fields (risk_synthesis included).
"""


class MarketEventNarrative(BaseModel):
    event_commentary: str
    benchmark_commentary: str
    risk_synthesis: str = ""
    outlook: str
    considerations: list[str]


def build_market_event_prompt(facts: dict[str, Any]) -> str:
    port = facts.get("portfolio") or {}
    lines = [
        f"Portfolio: {facts.get('portfolio_name', 'Portfolio')}",
        f"Portfolio value: {_fmt_money(float(facts.get('portfolio_value', 0)))}",
        f"Event: {facts.get('event_name', 'Market event')} on {facts.get('event_date', 'n/a')}",
        f"Event window: {facts.get('window_start', 'n/a')} to {facts.get('window_end', 'n/a')} "
        f"({int(facts.get('trading_days') or 0)} trading days). "
        "Impact is measured from the last close before the event.",
        "",
        "Portfolio through the window:",
        f"  return since the last close before the event {_pct(port.get('event_return'))}, "
        f"peak drawdown in the window {_pct(port.get('peak_drawdown'))}",
    ]
    bench = facts.get("benchmark") or {}
    if bench.get("event_return") is not None:
        lines += [
            "",
            f"Benchmark ({bench.get('label') or 'benchmark'}) through the same window:",
            f"  return since the last close before the event {_pct(bench.get('event_return'))}"
            + (f", peak drawdown {_pct(bench.get('peak_drawdown'))}"
               if bench.get("peak_drawdown") is not None else ""),
        ]
    risk = facts.get("risk") or {}
    lines += [
        "",
        f"Current regime: {risk.get('regime', 'Normal')}, fragility score "
        f"{float(risk.get('fragility_score') or 0):.2f} "
        "(current vol / long-term median vol; above 1.5 is flagged fragile)",
    ]
    rr = facts.get("risk_reconciliation") or {}
    if (rr.get("var_1d_dollars") is not None
            or rr.get("max_drawdown_dollars") is not None
            or rr.get("worst_scenario_dollars") is not None):
        lines += ["", "Downside on one basis (dollars for this portfolio), to place "
                      "alongside the event-window move above:"]
        if rr.get("var_1d_dollars") is not None:
            lines.append(f"  1-day VaR95: {_fmt_money(rr['var_1d_dollars'])} ({_pct(rr.get('var_1d_pct'))})")
        ws = rr.get("worst_scenario") or {}
        if rr.get("worst_scenario_dollars") is not None:
            lines.append(f"  worst simulated scenario ({ws.get('name')}): {_fmt_money(rr['worst_scenario_dollars'])}")
        if rr.get("max_drawdown_dollars") is not None:
            lines.append(f"  realized max drawdown: {_fmt_money(rr['max_drawdown_dollars'])} ({_pct(rr.get('max_drawdown_pct'))})")
        if rr.get("forecast_downside_dollars") is not None:
            lines.append(f"  forecast downside (low end): {_fmt_money(rr['forecast_downside_dollars'])}")
        lines.append(f"  fragility reading: {rr.get('fragility_label', 'n/a')}")
        for fl in rr.get("flags", []):
            lines.append(f"  CONSISTENCY FLAG: {fl}")
    fc = facts.get("forecast") or {}
    if fc.get("return_pct") is not None:
        lines += [
            "",
            f"Engine forecast from the latest close (model: {fc.get('model', 'unknown')}):",
            f"  median projected return over the next {int(fc.get('horizon_days') or 0)} "
            f"trading days {float(fc['return_pct']):+.2f}%"
            + (f", 95% interval width at horizon {float(fc['band_pct']):.1f}% of the median"
               if fc.get("band_pct") is not None else ", no model interval available"),
        ]
    else:
        lines += ["", "No engine forecast is available for this run."]
    impacts = [h for h in (facts.get("holdings_impact") or []) if h.get("return") is not None]
    if impacts:
        lines += ["", "Per-holding event-window returns and weighted portfolio contributions:"]
        for h in impacts[:20]:
            lines.append(
                f"  {h.get('ticker')}: return {_pct(h.get('return'))}, "
                f"contribution {_pct(h.get('contribution'))}"
            )
    summary = str(facts.get("event_summary") or "").strip()
    if summary:
        lines += ["", "Advisor's event description (verbatim, context only):", f"  {summary}"]
    return f"{MARKET_EVENT_SYSTEM_PROMPT}\n\n" + "\n".join(lines) + "\n\nWrite the narrative now as JSON."


def run_market_event(*, facts: dict[str, Any]) -> tuple[dict[str, Any], LlmResult]:
    prompt = build_market_event_prompt(facts)
    port = facts.get("portfolio") or {}
    bench = facts.get("benchmark") or {}
    fc = facts.get("forecast") or {}
    rr = facts.get("risk_reconciliation") or {}
    result = generate(
        prompt,
        agent_name="market_event_narrator",
        schema=MarketEventNarrative,
        cache_key_extra={
            "portfolio_name": facts.get("portfolio_name"),
            "portfolio_value": round(float(facts.get("portfolio_value", 0)), 2),
            "event_name": facts.get("event_name"),
            "event_date": facts.get("event_date"),
            "event_return": round(float(port.get("event_return") or 0), 4),
            "peak_drawdown": round(float(port.get("peak_drawdown") or 0), 4),
            "bench_return": (round(float(bench["event_return"]), 4)
                             if bench.get("event_return") is not None else None),
            "fragility": round(float((facts.get("risk") or {}).get("fragility_score") or 0), 2),
            "forecast_return": (round(float(fc["return_pct"]), 2)
                                if fc.get("return_pct") is not None else None),
            "recon_maxdd": (round(float(rr.get("max_drawdown_pct")), 4)
                            if rr.get("max_drawdown_pct") is not None else None),
        },
    )
    try:
        parsed = json.loads(result.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"market event narrator returned malformed JSON: {exc}")
    if not isinstance(parsed, dict):
        raise ValueError("market event narrator returned malformed JSON: not an object")
    out = {
        k: _strip_dashes(str(parsed.get(k) or ""))
        for k in ("event_commentary", "benchmark_commentary", "risk_synthesis", "outlook")
    }
    out["considerations"] = [
        _strip_dashes(str(c)) for c in (parsed.get("considerations") or []) if str(c).strip()
    ]
    return out, result


# Year-end narrator: same contract (one batched call, grounded only in
# supplied facts, options-to-evaluate framing), specialized for the annual
# review: how the year ACTUALLY went (real monthly and period returns), honest
# model-performance commentary only when real walk-forward validation figures
# exist, and year-ahead framing grounded in the current regime and fragility,
# never in invented macro themes.

YEAREND_SYSTEM_PROMPT = """You are a buy-side risk analyst writing the narrative layer of a year-end portfolio review for a financial advisor's client. You are given ONLY real computed facts about one portfolio's review period: monthly returns for the months with price data, the total return over those months, optionally a benchmark's return over the same months, risk metrics computed over the engine's stated analysis window, the monthly volatility and fragility paths, the current regime, optionally the engine's walk-forward model validation figures, and the top and bottom contributors. Write:

- year_summary: 3-5 sentences. How the review period actually went: the total return over the covered months (against the benchmark when benchmark facts are supplied), which months drove or hurt the result, and what the contributor figures show about where the return came from. Use dollar terms via the supplied portfolio values where it helps.
- risk_commentary: 2-4 sentences. What the monthly volatility and fragility paths show about how risk evolved through the period, and what the stated risk metrics say. Name the window the risk metrics were computed over exactly as supplied; never present them as calendar-year statistics. If a risk-contribution decomposition is supplied, name the holding that contributed the MOST to portfolio volatility over the year and note where its share of risk diverges from its weight (a small position can carry outsized risk); cite the contribution number rather than merely asserting it. If a one-dollar-basis downside reconciliation is supplied, tie the separate measures (1-day VaR, worst simulated scenario, realized maximum drawdown, forecast downside) into one picture in dollars, say which is most severe, and surface any consistency flag plainly.
- model_commentary: 2-3 sentences, ONLY when model validation facts are supplied: what the directional accuracy and mean absolute forecast error from walk-forward validation say about how reliable the engine's forecasts have been, including the number of validation points. If a directional-accuracy confidence interval is supplied and it includes 50%, say plainly that the measured edge is not statistically distinguishable from a coin flip; do not overstate a hit rate near 50%. Empty string when no model validation facts are supplied.
- year_ahead: 3-5 sentences of positioning context for the year ahead, grounded ONLY in the supplied current regime, fragility score, and volatility facts: what the current risk state suggests is worth monitoring as the new year starts. Never predict markets, rates, inflation, or events, and never reference asset classes, products, or holdings that are not in the supplied facts.
- considerations: 2-5 short bullets. Possible moves or topics the advisor could evaluate, each tied to a specific number in the facts (for example a month that dominated the loss, a contributor concentration, a fragility reading near the 1.5 threshold, or a volatility trend). Phrase each as an option to evaluate, never an instruction.

Rules:
- Use ONLY the supplied numbers. Never invent figures, benchmarks, themes, macro forecasts, or events.
- Convert percentages to dollar terms using the supplied portfolio values where it helps; when no dollar values are supplied, stay in percentage terms.
- Plain professional English. Expand jargon on first use.
- These are model-derived observations for a professional to evaluate, not advice. No promises, no certainty language.
- NEVER use em dashes or en dashes anywhere in the text. Use commas, colons, or periods instead.

Return JSON with exactly those five fields.
"""


class YearEndNarrative(BaseModel):
    year_summary: str
    risk_commentary: str
    model_commentary: str
    year_ahead: str
    considerations: list[str]


def build_yearend_prompt(facts: dict[str, Any]) -> str:
    rm = facts.get("risk_metrics") or {}
    lines = [
        f"Portfolio: {facts.get('portfolio_name', 'Portfolio')}",
        f"Review year: {facts.get('review_year', 'n/a')}",
        f"Covered months: {facts.get('coverage_label', 'n/a')}",
    ]
    vs, ve = facts.get("portfolio_value_start"), facts.get("portfolio_value_end")
    if vs and ve:
        lines.append(
            f"Portfolio value: {_fmt_money(float(vs))} at the start of the period, "
            f"{_fmt_money(float(ve))} at the end"
        )
    elif ve:
        lines.append(f"Portfolio value at period end: {_fmt_money(float(ve))}")
    lines += ["", f"Total return over the covered months: {_pct(facts.get('return_period'))}"]
    bench = facts.get("benchmark") or {}
    if bench.get("return_period") is not None:
        lines.append(
            f"Benchmark ({bench.get('label') or 'benchmark'}) over the same months: "
            f"{_pct(bench['return_period'])}"
        )
    else:
        lines.append("No benchmark data was available for the covered months.")
    monthly = facts.get("monthly_returns") or []
    if monthly:
        lines += ["", "Monthly portfolio returns:"]
        for m in monthly:
            lines.append(f"  {m['month']}: {_pct(m.get('return'))}")
    lines += [
        "",
        f"Risk metrics ({facts.get('metrics_window', 'engine analysis window')}):",
        f"  annualized volatility {_pct(rm.get('annualized_vol'))}, "
        f"Sharpe {float(rm.get('sharpe') or 0):.2f}, "
        f"Sortino {float(rm.get('sortino') or 0):.2f}, "
        f"max drawdown {_pct(rm.get('max_drawdown'))}",
        f"Current regime: {rm.get('regime', 'Normal')}, fragility score "
        f"{float(rm.get('fragility_score') or 0):.2f} "
        "(current vol / long-term median vol; above 1.5 is flagged fragile)",
    ]
    vols = facts.get("vol_series") or []
    if vols:
        lines += ["", "Monthly realized volatility (annualized %):"]
        for m in vols:
            lines.append(f"  {m['month']}: {float(m['vol']):.1f}%")
    frag = facts.get("fragility_series") or []
    if frag:
        lines += ["", "Monthly fragility score:"]
        for m in frag:
            lines.append(f"  {m['month']}: {float(m['fragility']):.2f}")
    ma = facts.get("model_accuracy") or {}
    if ma.get("hit_rate") is not None:
        lines += [
            "",
            "Model validation (walk-forward, run on the portfolio's trailing price "
            "history at report time, not on calendar-year forecasts):",
            f"  winning model {ma.get('best_model', 'unknown')}, directional accuracy "
            f"{float(ma['hit_rate']) * 100:.0f}% across {int(ma.get('n_steps') or 0)} "
            f"validation points, mean absolute forecast error "
            f"{float(ma.get('avg_error') or 0) * 100:.1f}%",
        ]
    else:
        lines += ["", "No model validation facts are available for this run. "
                      "Leave model_commentary empty."]
    tr = facts.get("track_record") or {}
    if tr.get("hit_rate") is not None:
        lines += [
            "",
            "Forecast track record with statistical confidence (walk-forward validation):",
            f"  directional accuracy {tr['hit_rate'] * 100:.0f}% over {tr['n_steps']} steps, "
            f"95% CI {tr['ci_low'] * 100:.0f}% to {tr['ci_high'] * 100:.0f}%, coin-flip baseline 50%, "
            f"{'statistically above' if tr.get('beats_coinflip') else 'NOT distinguishable from'} chance",
        ]
    ra = facts.get("risk_attribution") or {}
    if ra.get("rows"):
        lines += ["", f"Risk contribution by holding (portfolio annualized volatility "
                      f"{ra['portfolio_vol'] * 100:.1f}%, {ra.get('n_obs', 0)} obs; "
                      f"risk share vs weight):"]
        for r in ra["rows"][:8]:
            lines.append(f"  {r['ticker']}: weight {r['weight'] * 100:.0f}%, "
                         f"risk share {r['risk_pct'] * 100:.0f}%")
    rr_ = facts.get("risk_reconciliation") or {}
    if rr_.get("var_1d_dollars") is not None or rr_.get("worst_scenario_dollars") is not None:
        lines += ["", "Downside on one basis (dollars for this portfolio):"]
        if rr_.get("var_1d_dollars") is not None:
            lines.append(f"  1-day VaR95: {_fmt_money(rr_['var_1d_dollars'])} ({_pct(rr_.get('var_1d_pct'))})")
        if rr_.get("worst_scenario_dollars") is not None:
            lines.append(f"  worst simulated scenario ({(rr_.get('worst_scenario') or {}).get('name')}): {_fmt_money(rr_['worst_scenario_dollars'])}")
        if rr_.get("max_drawdown_dollars") is not None:
            lines.append(f"  realized max drawdown: {_fmt_money(rr_['max_drawdown_dollars'])} ({_pct(rr_.get('max_drawdown_pct'))})")
        if rr_.get("forecast_downside_dollars") is not None:
            lines.append(f"  forecast downside (low end): {_fmt_money(rr_['forecast_downside_dollars'])}")
        lines.append(f"  fragility reading: {rr_.get('fragility_label', 'n/a')}")
        for fl in rr_.get("flags", []):
            lines.append(f"  CONSISTENCY FLAG: {fl}")
    for label, key in (("Top contributors", "top_contributors"),
                       ("Bottom contributors", "bottom_contributors")):
        rows = facts.get(key) or []
        if rows:
            lines += ["", f"{label} (position return over the covered period, "
                          "weighted portfolio contribution):"]
            for h in rows:
                lines.append(
                    f"  {h.get('ticker')}: return {_pct(h.get('return'))}, "
                    f"contribution {_pct(h.get('contribution'))}"
                )
    return f"{YEAREND_SYSTEM_PROMPT}\n\n" + "\n".join(lines) + "\n\nWrite the narrative now as JSON."


def run_yearend(*, facts: dict[str, Any]) -> tuple[dict[str, Any], LlmResult]:
    prompt = build_yearend_prompt(facts)
    rm = facts.get("risk_metrics") or {}
    bench = facts.get("benchmark") or {}
    ma = facts.get("model_accuracy") or {}
    ra = facts.get("risk_attribution") or {}
    tr = facts.get("track_record") or {}
    rr_ = facts.get("risk_reconciliation") or {}
    result = generate(
        prompt,
        agent_name="yearend_narrator",
        schema=YearEndNarrative,
        cache_key_extra={
            "portfolio_name": facts.get("portfolio_name"),
            "review_year": facts.get("review_year"),
            "return_period": round(float(facts.get("return_period") or 0), 4),
            "bench_return": (round(float(bench["return_period"]), 4)
                             if bench.get("return_period") is not None else None),
            "vol": round(float(rm.get("annualized_vol") or 0), 4),
            "fragility": round(float(rm.get("fragility_score") or 0), 2),
            "hit_rate": (round(float(ma["hit_rate"]), 3)
                         if ma.get("hit_rate") is not None else None),
            "risk_share_top": (round(float(ra["rows"][0]["risk_pct"]), 3)
                               if ra.get("rows") else None),
            "track_ci_low": (round(float(tr["ci_low"]), 3)
                             if tr.get("ci_low") is not None else None),
            "recon_worst": (round(float((rr_.get("worst_scenario") or {}).get("return_pct") or 0), 2)
                            if rr_.get("worst_scenario") else None),
            "contributors": [
                h.get("ticker")
                for h in (facts.get("top_contributors") or [])
                + (facts.get("bottom_contributors") or [])
            ],
        },
    )
    try:
        parsed = json.loads(result.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"year-end narrator returned malformed JSON: {exc}")
    if not isinstance(parsed, dict):
        raise ValueError("year-end narrator returned malformed JSON: not an object")
    out = {
        k: _strip_dashes(str(parsed.get(k) or ""))
        for k in ("year_summary", "risk_commentary", "model_commentary", "year_ahead")
    }
    out["considerations"] = [
        _strip_dashes(str(c)) for c in (parsed.get("considerations") or []) if str(c).strip()
    ]
    return out, result


# Onboarding narrator: same contract (one batched call, grounded only in
# supplied facts, options-to-evaluate framing), specialized for the first
# conversation with a new client: the portfolio's MEASURED risk profile in
# plain terms against the client's STATED risk tolerance and target
# volatility, what to watch, and considerations.

ONBOARDING_SYSTEM_PROMPT = """You are a buy-side risk analyst writing the narrative layer of a new client risk assessment (onboarding) report for a financial advisor. You are given ONLY real computed facts about one portfolio: its measured risk metrics from its own price history, the client's stated risk tolerance and target annualized volatility, the computed gap between actual and target volatility, the current allocation by asset type, and the holdings. Write:

- risk_profile_summary: 3-5 sentences. Describe the portfolio's risk profile in plain terms and compare it against the client's stated risk tolerance and target volatility: state the actual volatility, the target, and the gap in percentage points, and say plainly whether the portfolio is running hotter than, cooler than, or in line with the stated tolerance. Use dollar terms via the portfolio value where it helps, for example what the historical maximum drawdown would have meant in dollars.
- what_to_watch: 2-4 sentences. The specific numbers worth monitoring as the relationship starts, each grounded in a supplied figure: for example the volatility gap, a position whose weight dominates the portfolio, the historical drawdown depth, a low Sharpe ratio, or a fragility score near the flagged threshold. If a risk-contribution decomposition is supplied, name the holding that contributes the MOST to the portfolio's volatility and note where its share of risk diverges from its weight (a small, volatile, or highly correlated position can carry a risk share well above its weight); cite the contribution number rather than merely asserting dominance.
- considerations: 2-5 short bullets. Possible topics or moves the advisor could evaluate with the client, each tied to a specific number in the facts (for example discussing whether the stated target still fits given the measured gap, revisiting a concentrated weight, or reviewing the tolerance banding). Phrase each as an option to evaluate, never an instruction.

Rules:
- Use ONLY the supplied numbers. Never invent figures, benchmarks, target allocations, or products.
- Never recommend a specific reallocation or security: describe what the numbers show and what could be evaluated.
- Convert percentages to dollar terms using the portfolio value where it helps.
- Plain professional English. Expand jargon on first use.
- These are model-derived observations for a professional to evaluate, not advice. No promises, no certainty language.
- NEVER use em dashes or en dashes anywhere in the text. Use commas, colons, or periods instead.

Return JSON with exactly those three fields.
"""


class OnboardingNarrative(BaseModel):
    risk_profile_summary: str
    what_to_watch: str
    considerations: list[str]


def build_onboarding_prompt(facts: dict[str, Any]) -> str:
    rm = facts.get("risk_metrics") or {}
    actual = float(rm.get("annualized_vol") or 0.0)
    target = float(facts.get("target_vol") or 0.0)
    lines = [
        f"Portfolio: {facts.get('portfolio_name', 'Portfolio')}",
        f"Portfolio value: {_fmt_money(float(facts.get('portfolio_value', 0)))}",
        f"Client's stated risk tolerance: {facts.get('risk_tolerance', 'n/a')}",
        f"Client's stated target annualized volatility: {_pct(facts.get('target_vol'))}",
        "",
        "Measured risk profile (computed from the portfolio's own price history):",
        f"  actual annualized volatility {_pct(rm.get('annualized_vol'))}, "
        f"gap vs target {(actual - target) * 100:+.2f}pp",
        f"  Sharpe {float(rm.get('sharpe_ratio') or 0):.2f}, "
        f"Sortino {float(rm.get('sortino_ratio') or 0):.2f}, "
        f"max drawdown {_pct(rm.get('max_drawdown'))}",
        f"  VaR95 1-day {_pct(rm.get('var_95_daily'))}, CVaR95 {_pct(rm.get('cvar_95_daily'))}",
        f"  beta {float(rm.get('beta') or 0):.2f}, fragility "
        f"{float(rm.get('fragility_score') or 0):.2f} "
        "(current vol / long-term median vol; above 1.5 is flagged fragile), "
        f"regime {rm.get('regime', 'Normal')}",
    ]
    alloc = facts.get("allocation") or {}
    if alloc:
        lines += ["", "Current allocation by asset type:"]
        for k, v in alloc.items():
            lines.append(f"  {k}: {float(v) * 100:.0f}%")
    ra = facts.get("risk_attribution") or {}
    if ra.get("rows"):
        lines += ["", f"Risk contribution by holding (portfolio annualized volatility "
                      f"{ra['portfolio_vol'] * 100:.1f}%, {ra.get('n_obs', 0)} obs; "
                      f"risk share vs weight, sorted by risk share):"]
        for r in ra["rows"][:8]:
            lines.append(f"  {r['ticker']}: weight {r['weight'] * 100:.0f}%, "
                         f"risk share {r['risk_pct'] * 100:.0f}%")
    holds = facts.get("holdings") or []
    if holds:
        lines += ["", "Holdings (ticker, weight, type):"]
        for h in holds[:20]:
            lines.append(
                f"  {h.get('ticker')}: {float(h.get('weight', 0)) * 100:.0f}%, "
                f"{h.get('asset_type', 'n/a')}"
            )
    return f"{ONBOARDING_SYSTEM_PROMPT}\n\n" + "\n".join(lines) + "\n\nWrite the narrative now as JSON."


def run_onboarding(*, facts: dict[str, Any]) -> tuple[dict[str, Any], LlmResult]:
    prompt = build_onboarding_prompt(facts)
    rm = facts.get("risk_metrics") or {}
    ra = facts.get("risk_attribution") or {}
    result = generate(
        prompt,
        agent_name="onboarding_narrator",
        schema=OnboardingNarrative,
        cache_key_extra={
            "portfolio_name": facts.get("portfolio_name"),
            "portfolio_value": round(float(facts.get("portfolio_value", 0)), 2),
            "risk_tolerance": facts.get("risk_tolerance"),
            "target_vol": round(float(facts.get("target_vol") or 0), 4),
            "actual_vol": round(float(rm.get("annualized_vol") or 0), 4),
            "sharpe": round(float(rm.get("sharpe_ratio") or 0), 3),
            "max_drawdown": round(float(rm.get("max_drawdown") or 0), 4),
            "fragility": round(float(rm.get("fragility_score") or 0), 2),
            "risk_share_top": (round(float(ra["rows"][0]["risk_pct"]), 3)
                               if ra.get("rows") else None),
            "holdings": [
                {"t": h.get("ticker"), "w": round(float(h.get("weight") or 0), 4)}
                for h in (facts.get("holdings") or [])
            ],
        },
    )
    try:
        parsed = json.loads(result.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"onboarding narrator returned malformed JSON: {exc}")
    if not isinstance(parsed, dict):
        raise ValueError("onboarding narrator returned malformed JSON: not an object")
    out = {
        k: _strip_dashes(str(parsed.get(k) or ""))
        for k in ("risk_profile_summary", "what_to_watch")
    }
    out["considerations"] = [
        _strip_dashes(str(c)) for c in (parsed.get("considerations") or []) if str(c).strip()
    ]
    return out, result
