# Runbook — produce one concierge letter (~30 min)

Repeatable process to turn an advisor's holdings CSV into a client-ready quarterly letter, by hand, using the existing engine. Target: **≤ 30 minutes per advisor** once you've done two. If it takes an hour, you can't run 15 — tighten before scaling.

**Prereqs:** backend running (`scripts/qsight.sh up` or local `python main.py`), your `X-User-Id`/auth, and the [sample letter](./sample-quarterly-letter.md) open as the template.

---

## Step 1 — Get their book in (5 min)

Ask the advisor for a simple CSV: `ticker,weight` (or `ticker,quantity`). One model portfolio is enough — they do NOT need to send real client account numbers (and shouldn't; see the data promise in [outreach.md](./outreach.md)).

```
POST /portfolios/import          # multipart CSV → creates a portfolio, returns its id
# or the two-step preview path:
POST /portfolios/import/parse    # validate + preview the parsed holdings
POST /portfolios/import/commit   # commit the previewed holdings
```

Note the returned **portfolio_id**.

## Step 2 — Pull the real numbers (10 min)

You need real, reproducible figures. Two sources, both already honesty-hardened:

**a) The analytical quarterly (the backing document):**
```
POST /reports/portfolio/{portfolio_id}/quarterly
  body: { client_name, advisor_name, firm_name, portfolio_value? }
```
Returns the honesty-audited quarterly PDF — real returns, real GARCH vol, real drawdown, component risk attribution, forecast track-record with CIs. `portfolio_value` is optional and **never invented** — omit it and dollar figures are omitted honestly.

**b) The differentiated line — Regime Watch on their actual book:**
```
GET /portfolios/{portfolio_id}/regime_watch
```
Returns the realized equity-vs-bond correlation on THEIR holdings vs the book's own baseline:
`short_corr`, `baseline_corr`, `delta`, `n_obs`, `as_of`, `sleeve_weights`, `status`.
This is the sentence a canned newsletter and a raw ChatGPT paste cannot produce. If `status = "na"` (e.g. an all-equity book), skip the diversification section honestly — do not force it.

Copy these numbers into a scratch note. **Every figure in the letter must trace to one of these two calls.**

## Step 3 — Assemble the letter (8 min)

Open [`sample-quarterly-letter.md`](./sample-quarterly-letter.md), replace the bracketed fields and the numbers with this advisor's real ones:

- `[Client First Name]`, `[Advisor Name]`, `[Your Firm]` — from the advisor.
- Quarter/1-yr return, volatility vs all-stock, deepest dip — from Step 2a.
- The correlation line — from Step 2b (`short_corr` vs `baseline_corr`). Use the plain-English read: Δ ≥ +0.10 → "moving together more than this book's norm — diversification weakening"; Δ ≤ −0.10 → "diversifying better than norm"; else "in line with baseline."
- Keep the "measurement, not a forecast" framing and the "before fees and taxes" footnote **verbatim**.

## Step 4 — Honesty-proof it (5 min) — DO NOT SKIP

Line-by-line check before it leaves your hands:

- [ ] Every number traces to a Step-2 call. No number you can't reproduce.
- [ ] No predicted return, price target, probability, hit-rate, or "we forecast…".
- [ ] No fabricated benchmark or invented dollar value (omit dollars if `portfolio_value` was unknown).
- [ ] Correlation framed as **realized/measured**, never predictive.
- [ ] "before fees and taxes" disclosure present; dated (`as_of`).
- [ ] If Regime Watch was `na`, the diversification section is removed, not faked.
- [ ] Reads warm and human — something an advisor would actually send.

## Step 5 — Deliver as a DRAFT (2 min)

Send it framed as **"a draft for your review — you're the fiduciary; edit anything before it goes to a client."** That single framing removes the compliance objection. Then log the outcome in `results.md` (advisor, date, sent, forwarded?, WTP?, verbatim reaction).

---

**Batching tip:** do Step 1–2 for all advisors in one sitting (the engine calls are the slow part), then Step 3–5 as a writing block. That's how you hold 30 min/advisor across 15 of them.
