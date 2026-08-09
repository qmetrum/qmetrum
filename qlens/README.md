# QLens

**A decision-support research lens for equities.** A small team of LLM agents argues the bull and bear case for a stock, then a judge issues a plainly-reasoned **Buy / Hold / Sell** stance — with every claim traced back to a fact.

Inspired by the multi-agent architecture of [TradingAgents](https://github.com/TauricResearch/TradingAgents), but built to a different standard: **reasoning you can audit, not returns we can't back.**

## What it does

Given a ticker (and any context you paste in), QLens:

1. **Gathers facts** — recent price action, range, and basic fundamentals — each carrying its source.
2. **Debates** — a **Bull** agent and a **Bear** agent each build their strongest case, citing those facts.
3. **Judges** — a portfolio-manager agent weighs both sides and issues a stance (**Buy / Hold / Sell**) with the key risks and *what would change its mind*.

The output is an **analytical opinion from a simulated debate — not investment advice, and not a prediction.**

## Honesty charter (non-negotiable)

QLens belongs to a product family whose one durable asset is trust. So:

- **No performance claims.** QLens never quotes a return, an accuracy, a hit-rate, or a Sharpe. It reasons; it does not advertise a record.
- **No fabricated track record.** We do not display "past QLens calls and how they did." A call's worth is the quality of the reasoning shown — not an outcome score we can't reproduce.
- **Every point is grounded.** Bull and bear claims cite the fact they rest on. Uncited assertions are dropped, not published.
- **Conviction is qualitative** (low / medium / high, from how well the evidence agrees) — explicitly *not* a probability of being right.
- **It's a stance, not advice.** Every verdict ships with that disclaimer.

## Where it fits

QLens is the **reasoning / narration layer** for the wider stack: it can explain a Qpulse regime break, deepen a Qsight per-holding view, or draft the analysis behind a client letter — always on the real holdings, always honesty-gated.

## Quickstart

```bash
pip install -r requirements.txt
export GOOGLE_API_KEY=...          # Gemini
python -m qlens.cli AAPL
python -m qlens.cli AAPL --context "Just guided revenue down 5% for next quarter."
```

Runs on Gemini flash, **on-demand** — a few calls per ticker, cents apiece. By design it is *not* meant to sweep a large universe on a schedule (that's where token cost balloons).

## Status

**v0** — bull ⇄ bear → judge, on free `yfinance` facts, with a mock-testable orchestrator. Next: the full analyst roster (fundamental / technical / sentiment / news), grounding against Qmetrum's own data, and an API surface for Qsight.
