# Phase 2: Live account sync — scope

Goal: portfolios stay current automatically by linking a user's real brokerage/
custodial account, instead of manual entry or one-off CSV import (Phase 1).

## 0. Vendor fit — read this before committing to Plaid

Plaid is **consumer-oriented**: the *account owner* links *their own* account.
That fits a prosumer/investor app. Qsight is pitched at **advisors managing
clients' accounts**, which is a different model. Options, honestly ranked for
this use case:

- **SnapTrade** — investment/brokerage-account focused (Plaid's Investments
  coverage is thinner and consumer-skewed). Simpler, investment-native holdings
  + transactions, the account owner authorizes. **Best fit for a
  brokerage-linking flow; recommended over Plaid for this specific need.**
- **Plaid (Investments product)** — broad coverage, well-documented, but
  investments are a secondary product for them; consumer model.
- **Custodial aggregators** (Morningstar ByAllAccounts, Yodlee/MX) or **direct
  custodian APIs** (Schwab Advisor / Fidelity Institutional) — the true B2B/RIA
  path: pull *all* client accounts held at a custodian under the advisor's
  relationship. Highest fidelity, but heavyweight (contracts, onboarding,
  minimums) and overkill pre-launch.

**Recommendation:** scope the integration behind a thin internal interface so
the vendor is swappable; pilot with **SnapTrade** (or Plaid) in sandbox. The
architecture below is vendor-agnostic; "Link" = whichever provider's connect
widget.

## 1. Data flow (link + sync)

1. Frontend opens the provider's **Link widget** → user authenticates with their
   brokerage → widget returns a short-lived `public_token`.
2. Frontend posts `public_token` to backend → backend exchanges it for a
   long-lived `access_token` (+ item/account ids).
3. Backend **encrypts and stores** the access_token per user/linked-item.
4. Backend calls the provider's holdings endpoint → maps holdings to `Position`
   rows (reusing Phase 1's mapping + `_create_portfolio_from_holdings`).
5. **Ongoing sync**: provider webhook ("holdings updated") → backend refetches;
   plus a scheduled fallback refresh. Handle item re-auth (expired login/MFA)
   by flagging the link as "needs reconnect".

## 2. New pieces to build

Backend:
- Provider SDK + a thin `app/services/account_sync.py` interface (link-exchange,
  fetch-holdings, per-provider adapter) so the vendor is swappable.
- New model `LinkedAccount` (user_id, provider, item_id, account_id,
  encrypted_access_token, institution, status, last_synced_at, portfolio_id).
- Endpoints: `POST /accounts/link/token` (create Link token),
  `POST /accounts/link/exchange` (public_token -> store), `POST /accounts/{id}/sync`,
  `GET /accounts` (list linked), `DELETE /accounts/{id}` (unlink + revoke),
  `POST /webhooks/{provider}` (holdings-updated -> enqueue sync).
- Token encryption at rest (KMS or Fernet key in SSM) — do NOT store raw tokens.

Frontend:
- Load the provider's Link JS, a "Connect account" button, the Link flow,
  a "Linked accounts" panel (status, last synced, reconnect, unlink), and
  surface a synced portfolio the same way imported ones appear.

Infra/security:
- Provider secrets in SSM; encryption key in KMS/SSM.
- Webhook endpoint must be reliably reachable (see Section 5).
- Privacy policy + data-handling: you'll be storing links to real financial
  accounts. This raises the compliance bar (encryption, access controls,
  retention, breach posture).

## 3. Cost

- **Sandbox: free** — full build + test with fake institutions, no approval.
- **Production: usage-based per linked account**, roughly **$0.30-0.50 /
  account / month** for investment data (varies by provider/negotiation), often
  with a minimum. Budget scales with linked accounts, not users.
- Engineering: this is a multi-week feature (see Section 6), not a quick win.

## 4. Approval / compliance gauntlet (the real gate)

Production access is **not instant**. Expect: a company/business entity, a
production application, use-case review, a **security questionnaire**, and for
investment data sometimes extra review. Timeline **days to weeks**. Some
providers want evidence of data-handling controls. This is why it can't be
"built and shipped" like Phase 1 — the sandbox build is fast; going live is
gated on the provider + your compliance readiness.

## 5. Conflict with scale-to-zero (must resolve)

Live sync relies on **webhooks**, which cannot reach a backend that is scaled to
zero. Same class of problem as the alert scheduler. Resolution options:
- A tiny always-on **serverless webhook receiver** (Lambda + SQS/EventBridge)
  that queues sync jobs the backend drains when up; or
- Keep the backend always-on (drop scale-to-zero) — reverses the cost posture; or
- **Polling-only** sync (scheduled refresh when up, no webhooks) — simplest,
  slightly stale, but works with scale-to-zero. **Recommended for pilot.**

## 6. Phased rollout + effort

- **2a. Sandbox link + one-time holdings pull** (reuses Phase 1 mapping).
  ~3-5 focused days. No approval needed; proves the flow end-to-end.
- **2b. Persistence + polling refresh + reconnect handling + token encryption.**
  ~3-5 days. Still sandbox.
- **2c. Production access** (the gate): approval + security questionnaire +
  privacy policy. Days-to-weeks of mostly *your* work, not code.
- **2d. Webhooks + serverless receiver** (only if near-real-time is needed).
  ~2-3 days + infra.

## 7. Open decisions (needed before building)

1. **Vendor**: SnapTrade (recommended for brokerage/investment fit) vs Plaid vs
   a custodial aggregator.
2. **Region**: which markets are your users in? Coverage differs sharply.
3. **Scale-to-zero**: keep it (polling sync) or go always-on (webhooks)?
4. **Compliance readiness**: are you set up to store financial-account tokens
   (privacy policy, encryption, entity)? This gates production regardless of code.
5. **Cost appetite**: ~$0.30-0.50/account/month at scale — acceptable?

## Bottom line

The **code** for a sandbox link + holdings pull is a few days and reuses Phase
1's mapping. The **real cost** is the vendor-approval + compliance gate and the
webhook/scale-to-zero decision. I'd recommend: pick SnapTrade, build 2a in
sandbox to prove it, and run the production-access application in parallel.
