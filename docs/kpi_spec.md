# Qmetrum KPI Specification

Date: 2026-03-04
Owner: Product + Quant + Engineering

## Goal

Define a compact, consistent KPI set across asset and portfolio screens:

1. Explain expected return
2. Explain downside/risk
3. Explain technical state
4. Keep metrics auditable (formula + source)

## KPI Layers

### Layer 1: Core Risk/Performance (must-have)

- `var_95`: 1-day VaR from R GARCH service
- `cvar_95`, `cvar_99`: expected tail loss
- `max_drawdown`: minimum drawdown on cumulative return curve
- `sharpe_ratio`: annualized excess return / annualized volatility
- `sortino_ratio`: annualized excess return / annualized downside deviation
- `calmar_ratio`: annualized return / abs(max_drawdown)
- `hit_rate`: fraction of positive daily returns

### Layer 2: Technical State

- `rsi` (14)
- `macd` (12, 26, 9) and histogram (`macd_line - signal_line`)
- `atr` (14)
- `volatility` (historical + forecast sigma)

### Layer 3: Valuation / Context

- Market cap
- P/E and forward P/E
- EV/EBITDA
- Beta
- 52-week range

## Formula Notes

- Daily return: `r_t = P_t / P_{t-1} - 1`
- Annualization factor: `252`
- Risk-free rate: `3% annual` (`rf_daily = 0.03 / 252`)
- Sharpe: `sqrt(252) * (mean(r) - rf_daily) / std(r)`
- Sortino: `sqrt(252) * (mean(r) - rf_daily) / std(r[r < 0])`
- Max drawdown: `min((cumprod(1+r) / cummax(cumprod(1+r))) - 1)`
- Calmar: `annualized_return / abs(max_drawdown)`
- CVaR p: `mean(r | r <= VaR_p)`

## Data Sources

- Asset risk: `GET /assets/{symbol}/risk` (R GARCH engine)
- Asset forecast/performance/indicators: `POST /assets/{symbol}/forecast`
- Portfolio forecast/risk/indicators/performance: `POST /portfolios/{id}/forecast`
- Quantum tail metrics: `POST /portfolios/{id}/simulate_quantum_risk`

## UI Mapping

- Asset context rail:
  - Core KPIs (valuation)
  - Risk Snapshot (VaR, CVaR, regime, fragility)
  - Performance Snapshot (Sharpe, Sortino, Max DD, Calmar, Hit Rate)
- Asset Risk tab:
  - Monte Carlo cone + volatility panel
  - Technical Snapshot (RSI, MACD histogram, ATR, sigma)
- Portfolio Forecast tab:
  - Forecast Readout (return + risk + performance KPIs)
  - Right rail Risk Snapshot + Technical Snapshot

## Rollout Strategy

1. Expose already-computed metrics in UI first
2. Add QA checks for sign conventions and annualization assumptions
3. Add tooltips with formulas on KPI labels
4. Add endpoint-level metric contracts (JSON schema tests)
