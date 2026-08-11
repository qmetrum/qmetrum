# Concierge Test — the WTP gate

**One question this answers:** will a solo fee-only RIA *forward a QLens/Qsight-drafted quarterly client letter to a real client, and pay $50–150/mo for it?* Everything else (the correlation monitor, Regime Watch, QLens) is upstream of this. If the answer is no, no amount of more building changes the outcome. If it's yes, the engine is largely already built.

This is a **Wizard-of-Oz** test: you produce the letters by hand using the existing engine. No self-serve product, no new code. Cost is a few weeks of your time.

## Pre-registered success metric (decide this BEFORE reaching out)

Writing the bar down first is the whole discipline — it stops you reading a polite "nice, thanks" as validation.

| | Signal | Bar |
|---|---|---|
| **Primary** | Advisor actually **forwards the letter to a client** (or says they will, and later confirms) | The real proof of value |
| **Secondary** | Advisor says, unprompted or when asked, they'd **pay ~$50–150/mo** for this as a recurring service | Willingness to pay |
| **Sample** | Warm-intro advisors approached | **10–20** |
| **Stop / continue rule** | | See below |

**Decision rule (commit to it now):**
- **≥ 3 of ~15 both forward a letter AND say they'd pay** → strong signal. Build the self-serve path (task: productize).
- **1–2** → weak but alive. Do a second round with a sharper segment before deciding.
- **0 forward, 0 WTP** → the honest no. Stop the client-letter thesis; the month cost you weeks, not a year. That is a *win* — you bought the answer cheaply.

Track every conversation in `results.md` (create it as you go): advisor, date, sent?, forwarded?, WTP?, verbatim objection.

## The five steps

1. **Test the hook / build an audience** — the free [`/correlations` monitor](../../services/frontend_nextjs/src/app/correlations) as link-bait (measure: do advisors subscribe?). *(Runs in parallel; not required to start the concierge test.)*
2. **Concierge-deliver real letters** — [`runbook.md`](./runbook.md): import their book, run the engine, hand-assemble the letter, honesty-proof it, send as a **draft for their review**.
3. **Measure against the bar above.**
4. *(Only if it converts)* build the differentiator + self-serve. Regime Watch already computes the differentiated line on real holdings.
5. *(Only if it converts)* secure a distribution channel.

## Files

- [`runbook.md`](./runbook.md) — the ~30-minute-per-advisor production process.
- [`outreach.md`](./outreach.md) — warm-list template, the honest script, data-handling promise, objection handling.
- [`sample-quarterly-letter.md`](./sample-quarterly-letter.md) — the gold-standard example. Read this first; it's what you're selling.

## The non-negotiable

Every number in every letter must be **real and reproducible**, and every letter goes out framed as **"a draft for your review — you're the fiduciary."** One fabricated figure forwarded to a client destroys the honesty brand, which is the only durable asset here. See [`../pdf-report-audit.md`](../pdf-report-audit.md) — the quarterly report is already honesty-hardened; keep letters to that same bar.
