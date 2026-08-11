# Outreach kit

Warm-intro only. This buyer (solo fee-only RIA) is vendor-skeptical and does not buy from ads — the whole test rides on warm relationships and a genuinely useful free deliverable.

## Who to approach (the warm list)

Fill this in first — aim for **10–20** names you can reach without a cold email:

| Source | Notes |
|---|---|
| People you already know in advisory / XYPN / NAPFA | Warmest; start here |
| r/CFP, advisor LinkedIn, FinTwit people you've genuinely engaged | Second-degree, still warm |
| Intros from the above ("who else should see this?") | Compounds if step 1 lands |

Target the **solo, fee-only** advisor specifically — they are their own compliance officer, so there's no months-long CCO review to stall on. Avoid multi-advisor RIAs for this test.

## The script (short, honest, painkiller-framed)

Sell the **time saved on a deadline they can't skip** — not the technology.

> Hi [Name] — I'm building a tool that drafts an advisor's quarterly client letter on their real book: the performance, the risk, and one genuinely useful line most tools miss — whether the client's stock/bond mix is still actually diversifying, measured on their holdings.
>
> I'd like to draft one for you, free, on a model portfolio you pick. You get a client-ready draft you can edit and send (or not) — I just want your honest reaction. Takes you 5 minutes to hand me a `ticker,weight` CSV. Worth a look?

Notes:
- Lead with the deliverable ("your quarterly letter, drafted"), not "AI" or "correlation engine."
- "free," "on a model portfolio," "you edit before anything goes out" all lower the barrier.
- Ask for the honest reaction, not a sale — the sale signal comes from whether they forward it.

## Data-handling promise (say this unprompted)

> Send a **model portfolio** — just `ticker,weight`, no client names or account numbers needed. I use it once to draft your letter, I don't share it, and I delete the file afterward.

Keep this true: use one model book per advisor, don't ask for real client PII, delete CSVs after the draft. It removes the single biggest hesitation.

## Objection handling

- **"Is this compliant to send a client?"** → "It's a draft for your review — you're the fiduciary and you edit before anything goes out. Every number is real and reproducible; nothing is predicted or invented." (This is why we target solo advisors who are their own CCO.)
- **"How is this different from [newsletter / ChatGPT]?"** → "It's on *your* actual book, and it includes a line those can't produce honestly: whether your client's diversification is still holding, measured on their real holdings vs their own baseline."
- **"What does it cost?"** → "Nothing for this — I'm testing whether it's genuinely useful. If it is, it'd be a small monthly service; I'd love to know if that's something you'd pay for." *(Then log the answer as the WTP signal.)*
- **"Can it do [tax / fees / held-away]?"** → "Not yet — this is deliberately just the quarterly letter for now. Noted, though." (Don't over-promise; scope creep kills the test.)

## After you send

Log every outcome in `results.md` against the [pre-registered bar](./README.md): did they **forward it to a client**, and would they **pay $50–150/mo**? Those two — not compliments — are the whole test.
