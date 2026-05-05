# Qmetrum

> A risk-intelligence and AI-advisor workstation for independent financial advisors and small wealth-management firms.

Qmetrum lets a financial advisor manage client portfolios, run quantitative
forecasts and stress scenarios, monitor alerts, and generate advisor-facing
narratives — all backed by a hybrid classical / quantum / AI engine.

**Status: Pre-launch MVP.** The classical forecasting and AI-agent layers are
working end-to-end; the quantum modules are partially user-visible (VQMC
scenario fans, MPS-copula joint sampling) and partially research code that
sits behind dedicated endpoints. Auth (Cognito) and Postgres support are in
place; cloud deployment to AWS is the current focus.

---

## What it does

- **Portfolios & holdings.** Create client portfolios; edit weights/quantities; track per-portfolio risk metrics.
- **Forecasting.** Per-asset price forecasts (ARIMA + GARCH + BSTS + Quantum Reservoir) with confidence cones, plus per-portfolio aggregate forecasts.
- **Risk metrics.** Sharpe, Sortino, annualized vol, VaR(95%), max drawdown, fragility score, regime label (Normal / Drawdown / High_Vol / Low_Vol — calibrated per asset class).
- **Scenarios.** Custom stress scenarios via NL ("describe a scenario") or sliders; comparison chart, scenario fans (MPS-copula based), dollar-impact summary.
- **Alerts.** Per-ticker price thresholds with AI explanations grounded in the user's exposure to that ticker.
- **AI agents (Gemini 2.5 Flash).** Six advisor-facing agents: portfolio commentary, scenario translator, scenario summary, news synthesizer, alert explainer, single-turn client Q&A. Every output ships with a "View source data" panel so advisors can verify claims against the underlying numbers.
- **Reports.** PDF generation for quarterly client reviews.
- **Watchlists / Saved screens.** Per-user saved tickers and screener filters.

For deeper detail on how the pieces fit together, see [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11, FastAPI, SQLModel, Alembic, Uvicorn |
| Frontend | Next.js 16, React 19, TanStack Query, Recharts, lightweight-charts, Tailwind |
| Database | SQLite (dev) / Postgres (prod, RDS-bound) |
| Auth | AWS Cognito (User Pool, Hosted UI), JWT validation in backend middleware |
| LLM | Google Gemini 2.5 Flash via `google-genai` |
| Market data | Yahoo Finance (default), Polygon, Alpaca (REST) — all behind a vendor `Protocol` |
| Quantum | Qiskit, qiskit-finance, qiskit-machine-learning, qiskit-ibm-runtime |
| ML extras | scikit-learn, statsmodels, prophet, tensorflow, sentence-transformers, SHAP |
| Deploy target | AWS App Runner (backend) + Amplify Hosting (frontend) + RDS Postgres + Cognito + SSM Parameter Store |

---

## Repository layout

```
qmetrum_project/
├── services/
│   ├── forecasting_service_py/      # FastAPI backend (the brain)
│   │   ├── app/
│   │   │   ├── agents/              # AI agents (Gemini-powered)
│   │   │   ├── auth/                # Cognito JWT validation middleware
│   │   │   ├── db/                  # SQLModel models + engine
│   │   │   ├── logic/               # Forecasting, risk, regime, quantum modules
│   │   │   ├── reports/             # PDF report generation
│   │   │   ├── services/            # Market store, risk client
│   │   │   ├── vendors/             # Yahoo / Polygon / Alpaca / Hybrid
│   │   │   └── main.py              # FastAPI app + ~70 endpoints
│   │   ├── alembic/versions/        # DB migrations
│   │   ├── scripts/                 # Calibration + seed scripts
│   │   └── requirements.txt
│   └── frontend_nextjs/             # Next.js frontend
│       ├── src/
│       │   ├── app/                 # Pages (dashboard, assets, portfolios, scenarios, …)
│       │   ├── components/          # Charts, agents UI, auth, layout
│       │   └── lib/                 # API client, auth config, csv/png export
│       └── package.json
├── docs/                            # Specs and design notes
├── archive/                         # Decommissioned modules (R risk service, etc.)
├── ARCHITECTURE.md                  # Deep-dive on system design
└── README.md
```

---

## Local development

### Prerequisites

- Python 3.11
- Node.js 20+
- (Optional, for prod parity) Docker + a local Postgres if you want to test against Postgres rather than SQLite

### 1. Clone and install

```bash
git clone <this-repo>
cd qmetrum_project

# Backend
cd services/forecasting_service_py
pip install -r requirements.txt

# Frontend
cd ../frontend_nextjs
npm install
```

### 2. Configure env files

Backend — copy `services/forecasting_service_py/.env.example` to `.env` and fill in:

```
DATABASE_URL=sqlite:///./qmetrum.db          # default; can be Postgres URL
GOOGLE_API_KEY=AIza...                       # https://aistudio.google.com/app/apikey
COGNITO_REGION=eu-north-1                    # only required when running with auth
COGNITO_USER_POOL_ID=eu-north-1_xxx
COGNITO_APP_CLIENT_ID=xxx
DATA_VENDOR=yahoo                            # yahoo | polygon | hybrid (= alpaca + yahoo)
# ALPACA_API_KEY=...   (only when DATA_VENDOR=hybrid)
# ALPACA_SECRET_KEY=...
```

Frontend — copy `services/frontend_nextjs/.env.local.example` to `.env.local` and fill in:

```
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_COGNITO_AUTHORITY=https://cognito-idp.eu-north-1.amazonaws.com/eu-north-1_xxx
NEXT_PUBLIC_COGNITO_CLIENT_ID=xxx
NEXT_PUBLIC_COGNITO_DOMAIN=https://xxx.auth.eu-north-1.amazoncognito.com
NEXT_PUBLIC_COGNITO_REDIRECT_URI=http://localhost:3000/auth/callback
NEXT_PUBLIC_COGNITO_LOGOUT_URI=http://localhost:3000/
```

> ⚠️ Never commit `.env` or `.env.local`. Both are in `.gitignore`.

### 3. Run migrations

```bash
cd services/forecasting_service_py
alembic upgrade head
```

### 4. (Optional) Seed demo data

```bash
python scripts/seed_demo_cache.py
```

### 5. Start the services

```bash
# Terminal 1 — backend
cd services/forecasting_service_py
uvicorn app.main:app --reload

# Terminal 2 — frontend
cd services/frontend_nextjs
npm run dev
```

Open http://localhost:3000.

---

## Common commands

| Task | Command |
|---|---|
| Run a new alembic migration | `alembic revision --autogenerate -m "msg"` then `alembic upgrade head` |
| Type-check the frontend | `cd services/frontend_nextjs && npx tsc --noEmit` |
| Refresh regime thresholds from market data | `python scripts/calibrate_regime_thresholds.py --years 5` |
| Take over the demo data with your Cognito account | `python scripts/claim_demo_data.py --email you@example.com` |
| OpenAPI docs (auto-generated) | http://127.0.0.1:8000/docs |

---

## Deployment

Production deploy is to **AWS**: App Runner (backend) + Amplify Hosting (frontend) + RDS Postgres + Cognito + SSM Parameter Store. A full deploy guide will live in `DEPLOY.md` once the cloud setup is finalized.

---

## Security notes

- API keys belong in environment variables, never in the repo. Use AWS Secrets Manager / SSM Parameter Store in prod, `.env` files locally.
- The `qmetrum.db` SQLite file contains user data and is gitignored.
- The Cognito JWT auth middleware (`app/auth/middleware.py`) validates Bearer tokens on every request; the legacy `X-User-Id` header is honored only when `COGNITO_USER_POOL_ID` is unset (local dev / pre-Cognito mode) and will be removed once production cutover is complete.
- The frontend redirects unauthenticated visitors to Cognito's Hosted UI (`AuthGate`) — direct URL navigation to authenticated routes is not possible without a valid token.

---

## Contributing

Single-developer project today; contribution guidelines TBD when that changes.

---

## License

TBD.
