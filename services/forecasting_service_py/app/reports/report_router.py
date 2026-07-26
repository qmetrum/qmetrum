"""
report_router.py: FastAPI router for PDF report generation.

Drop this file into your app/ directory and register it in main.py:

    from app.report_router import report_router
    app.include_router(report_router, prefix="/reports", tags=["Reports"])

Each endpoint:
  1. Reads live data from your existing services (market_store, risk_client, etc.)
  2. Runs your forecasting/risk engine on that data
  3. Feeds the results into a report template
  4. Returns a downloadable PDF

Dependencies: reportlab, matplotlib (add to requirements.txt)
"""

import os
import uuid
import logging
import numpy as np
import pandas as pd
from bisect import bisect_left
from io import BytesIO
from xml.sax.saxutils import escape
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

# ── YOUR EXISTING IMPORTS ──
from app.logic.forecasting_logic import HybridForecaster
from app.logic.quantum_vqmc_trained import simulate_trained_vqmc
from app.logic.portfolio_logic import PortfolioManager
from app.services.market_store import get_price_series_cached, get_fundamentals_cached
from app.services.risk_client import calculate_risk
from app.db.database import engine
from app.db.models import (
    User, Portfolio, Position, PortfolioReportDataCache, AssetVolatilitySnapshot,
)
from app.agents import report_narrator, scenario_explainer
from app.reports.report_data_helpers import (
    compute_portfolio_beta,
    get_benchmark_series,
    get_benchmark_series_labeled,
    build_portfolio_daily_prices,
    DEFAULT_BENCHMARK,
)

# ── REPORT TEMPLATES ──
# These would live in app/reports/ in production
from app.reports.report_styles import *
from app.reports.template_quarterly import generate_quarterly_report
from app.reports.template_onboarding import generate_onboarding_report
from app.reports.template_market_event import generate_market_event_report
from app.reports.template_rebalancing import generate_rebalancing_report
from app.reports.template_yearend import generate_yearend_report

logger = logging.getLogger(__name__)
report_router = APIRouter()

# ── CONFIG ──
REPORT_TMP_DIR = os.getenv("REPORT_TMP_DIR", "/tmp/reports")
os.makedirs(REPORT_TMP_DIR, exist_ok=True)

DEFAULT_USER_ID = int(os.getenv("DEFAULT_USER_ID", "1"))


# ────────────────────────────────────────────────────────────
# REQUEST MODELS
# ────────────────────────────────────────────────────────────

class ReportAsset(BaseModel):
    ticker: str
    weight: float

class ReportScenarioItem(BaseModel):
    """A scenario the client already simulated (same shape the AI scenario
    endpoints use): knobs + the fan percentiles + adversarial discovery."""
    name: str
    shock_pct: Optional[float] = None
    vol_scale: Optional[float] = None
    drift_shift: Optional[float] = None
    fan: dict
    discovery: Optional[dict] = None


class QuarterlyReportRequest(BaseModel):
    """Full risk intelligence report (the flagship report)."""
    client_name: str
    advisor_name: str
    firm_name: str
    assets: List[ReportAsset]
    horizon_days: int = 90
    portfolio_value: Optional[float] = None  # REQUIRED at the endpoint: never invented
    # Real simulated scenarios from the Scenario Builder run; when absent the
    # report simply omits the scenario section (it never fabricates one).
    scenarios: Optional[List[ReportScenarioItem]] = None

class OnboardingReportRequest(BaseModel):
    """New client risk assessment.

    risk_tolerance and target_vol are the client's STATED inputs and must be
    supplied by the caller: the report's risk-alignment verdict is built on
    them, so defaulting them would fabricate a client statement."""
    client_name: str
    advisor_name: str
    firm_name: str
    assets: List[ReportAsset]
    risk_tolerance: str                # Conservative, Moderate, Growth, Aggressive
    target_vol: float                  # client's target annualized volatility, e.g. 0.10
    portfolio_value: Optional[float] = None

class MarketEventReportRequest(BaseModel):
    """Triggered during market turbulence."""
    client_name: str
    advisor_name: str
    firm_name: str
    assets: List[ReportAsset]
    event_name: str
    event_date: str                     # ISO date string
    event_summary: str
    portfolio_value: Optional[float] = None

class RebalancingReportRequest(BaseModel):
    """Rebalance proposal with before/after comparison."""
    client_name: str
    advisor_name: str
    firm_name: str
    current_assets: List[ReportAsset]
    proposed_assets: List[ReportAsset]
    rationale: str
    tax_considerations: Optional[str] = None
    portfolio_value: Optional[float] = None
    # Real simulated scenario runs for EACH allocation (same item shape the
    # quarterly report accepts). The stress section renders only when BOTH
    # sets are supplied and scenario names match; it is never fabricated.
    current_scenarios: Optional[List[ReportScenarioItem]] = None
    proposed_scenarios: Optional[List[ReportScenarioItem]] = None

class YearEndReportRequest(BaseModel):
    """Annual performance review.

    portfolio_value_start/_end are optional REAL dollar values from the
    advisor's records; dollar figures are omitted from the PDF when absent
    (never invented, never derived by assuming zero flows). proposed_changes
    are advisor-authored adjustments passed through verbatim."""
    client_name: str
    advisor_name: str
    firm_name: str
    assets: List[ReportAsset]
    review_year: int = 2025
    portfolio_value_start: Optional[float] = None
    portfolio_value_end: Optional[float] = None
    proposed_changes: Optional[List[str]] = None


# ────────────────────────────────────────────────────────────
# HELPER: EXTRACT LIVE DATA FROM YOUR ENGINE
# ────────────────────────────────────────────────────────────

def _resolve_user(user_id: Optional[int], x_user_id: Optional[int]) -> int:
    # Production (Cognito configured): only trust the X-User-Id header set by
    # CognitoAuthMiddleware from a verified JWT claim. Refuse query-param and
    # DEFAULT_USER_ID fallbacks: they're impersonation vectors.
    from app.auth.cognito import is_cognito_configured
    from fastapi import HTTPException
    if is_cognito_configured():
        if x_user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        return int(x_user_id)
    if user_id is not None:
        return int(user_id)
    if x_user_id is not None:
        return int(x_user_id)
    return DEFAULT_USER_ID



def _require_portfolio_value(value, label: str = "portfolio_value") -> float:
    """Dollar figures must come from the caller: never invent an AUM."""
    if value is None or float(value) <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"{label} is required: reports never invent portfolio values.",
        )
    return float(value)


def _last_cached_price(ticker: str, *datasets: dict) -> Optional[float]:
    """Most recent real close for a ticker: prefer the price frames already
    fetched for this report, then the market cache. Returns None when no real
    price exists, so share counts get omitted rather than invented."""
    for data in datasets:
        df = (data.get("price_data") or {}).get(ticker)
        if df is not None and len(df) and "price" in df:
            try:
                px = float(df["price"].iloc[-1])
            except (TypeError, ValueError):
                continue
            if px > 0:
                return px
    try:
        raw = get_price_series_cached(ticker)
        if raw:
            px = float(raw[-1].get("price") or 0.0)
            if px > 0:
                return px
    except Exception as e:
        logger.warning(f"Last price lookup failed for {ticker}: {e}")
    return None


def _cached_blob_matches(blob: dict, assets: List[ReportAsset]) -> bool:
    """A cached blob is only valid for the SAME portfolio: same ticker set AND
    same normalized weights (2% tolerance). A tickers-only match can silently
    report another portfolio's numbers under this client's name."""
    cached_w = blob.get("weights") or {}
    requested = {a.ticker.upper(): float(a.weight or 0.0) for a in assets}
    total = sum(requested.values())
    if total <= 0 or set(requested) != set(cached_w):
        return False
    return all(
        abs(w / total - float(cached_w.get(t, 0.0))) <= 0.02
        for t, w in requested.items()
    )


def _try_cached_portfolio_data(
    assets: List[ReportAsset],
    portfolio_id: Optional[int] = None,
) -> Optional[dict]:
    """Check PortfolioReportDataCache for pre-computed data. Returns None on miss."""
    try:
        with Session(engine) as session:
            if portfolio_id is not None:
                # Direct lookup by portfolio_id
                cached = session.exec(
                    select(PortfolioReportDataCache)
                    .where(PortfolioReportDataCache.portfolio_id == portfolio_id)
                    .order_by(PortfolioReportDataCache.updated_at.desc())
                ).first()
                if cached and cached.result_blob and _cached_blob_matches(cached.result_blob, assets):
                    logger.info(f"Portfolio {portfolio_id} report served from cache")
                    return _prepare_cached_result(cached.result_blob)
            else:
                # No portfolio_id: scan all cached portfolios for a full match
                all_cached = session.exec(
                    select(PortfolioReportDataCache)
                    .order_by(PortfolioReportDataCache.updated_at.desc())
                ).all()
                for cached in all_cached:
                    if cached.result_blob and _cached_blob_matches(cached.result_blob, assets):
                        logger.info(f"Ad-hoc report matched cached portfolio {cached.portfolio_id}")
                        return _prepare_cached_result(cached.result_blob)
    except Exception as e:
        logger.warning(f"Cache read failed: {e}")
    return None


def _prepare_cached_result(blob: dict) -> dict:
    """Prepare a cached blob for use by report templates."""
    result = dict(blob)
    result["price_data"] = _reconstruct_price_data(result)
    result["aligned"] = {}
    result["all_dates"] = []
    result["port_returns"] = pd.Series(dtype=float)
    return result


def _reconstruct_price_data(cached_result: dict) -> dict:
    """Reconstruct price_data DataFrames from cached dates/prices for contribution helpers."""
    price_data = {}
    dates = cached_result.get("dates", [])
    portfolio_prices = cached_result.get("portfolio_prices", [])
    tickers = cached_result.get("tickers", [])
    # We don't have per-asset prices in the cache blob, but asset_forecasts have history
    for ticker in tickers:
        af = cached_result.get("asset_forecasts", {}).get(ticker, {})
        hist_dates = af.get("history_dates", [])
        hist_prices = af.get("history_prices", [])
        if hist_dates and hist_prices and len(hist_dates) == len(hist_prices):
            df = pd.DataFrame({"date": hist_dates, "price": hist_prices})
            df["date"] = pd.to_datetime(df["date"])
            price_data[ticker] = df
    return price_data


def _fetch_portfolio_data(assets: List[ReportAsset], horizon_days: int = 90, portfolio_id: Optional[int] = None):
    """
    Serve pre-computed data from cache if available, otherwise run the full
    forecasting + risk pipeline on a portfolio.
    Returns a rich dict with everything the report templates need.
    """
    # Try cache first (instant)
    cached = _try_cached_portfolio_data(assets, portfolio_id=portfolio_id)
    if cached is not None:
        return cached

    asset_configs = [{"ticker": a.ticker.upper(), "weight": a.weight} for a in assets]
    tickers = [a["ticker"] for a in asset_configs]
    weights = {a["ticker"]: a["weight"] for a in asset_configs}

    # Normalize weights
    total_w = sum(weights.values())
    if total_w > 0:
        weights = {k: v / total_w for k, v in weights.items()}

    # ── Fetch price history for each asset ──
    price_data = {}
    fundamentals = {}
    for ticker in tickers:
        raw = get_price_series_cached(ticker, period="2y")
        if raw:
            df = pd.DataFrame(raw)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            price_data[ticker] = df
        fund = get_fundamentals_cached(ticker)
        if fund:
            fundamentals[ticker] = fund

    if not price_data:
        raise HTTPException(status_code=400, detail="Could not fetch price data for any ticker.")

    # ── Build synthetic portfolio price series ──
    # Align all tickers to common dates, fill forward
    all_dates = sorted(set().union(*[set(df["date"]) for df in price_data.values()]))
    aligned = {}
    for ticker, df in price_data.items():
        s = df.set_index("date")["price"].reindex(all_dates, method="ffill")
        aligned[ticker] = s

    # Weighted portfolio returns
    port_returns = pd.Series(0.0, index=all_dates)
    for ticker, series in aligned.items():
        ret = series.pct_change().fillna(0)
        port_returns += ret * weights.get(ticker, 0)

    port_prices = (1 + port_returns).cumprod() * 100  # indexed to 100
    port_prices_list = port_prices.values.tolist()
    dates_list = [d.strftime("%Y-%m-%d") for d in all_dates]

    # ── Run ensemble forecast on the portfolio series ──
    hist_df = pd.DataFrame({
        "date": all_dates,
        "price": port_prices.values,
    })

    forecaster = HybridForecaster()
    forecaster.train(hist_df)
    forecast_result = forecaster.predict(forecast_horizon_days=horizon_days)

    # ── Run risk service on portfolio series ──
    risk_data = {}
    try:
        risk_data = calculate_risk(
            prices=port_prices_list,
            horizon=horizon_days,
            n_paths=1000,
            require_success=False,
        ) or {}
    except Exception as e:
        logger.warning(f"Risk service call failed: {e}")

    # ── Quantum Monte Carlo via trained Qiskit ansatz ──
    qmc_result = {}
    try:
        qmc_result = simulate_trained_vqmc(
            historical_prices=port_prices_list[-252:],
            ticker=f"PORTFOLIO_REPORT",
            horizon_days=min(horizon_days, 90),
            n_simulations=5000,
        )
    except Exception as e:
        logger.warning(f"QMC simulation failed: {e}")

    # ── Per-asset forecasts (for contribution analysis) ──
    asset_forecasts = {}
    for ticker, df in price_data.items():
        try:
            fc = HybridForecaster()
            fc.train(df)
            asset_forecasts[ticker] = fc.predict(forecast_horizon_days=horizon_days)
        except Exception as e:
            logger.warning(f"Forecast for {ticker} failed: {e}")

    # ── Assemble performance metrics ──
    perf = forecast_result.get("performance_metrics", {})
    risk_metrics = forecast_result.get("risk_metrics", {})

    # Safe unbox (R sometimes returns [value] instead of value)
    def unbox(val, default=0.0):
        if isinstance(val, list):
            return float(val[0]) if val else default
        return float(val) if val is not None else default

    # ── Compute real portfolio beta from benchmark ──
    beta = 1.0
    try:
        with Session(engine) as session:
            bench_start = all_dates[0] if all_dates else datetime.utcnow() - timedelta(days=252)
            bench_end = all_dates[-1] if all_dates else datetime.utcnow()
            bench_df = get_benchmark_series(DEFAULT_BENCHMARK, bench_start, bench_end, session)
            if not bench_df.empty:
                bench_prices = bench_df.set_index("date")["close"].reindex(all_dates, method="ffill")
                bench_rets = bench_prices.pct_change().fillna(0)
                beta = compute_portfolio_beta(port_returns, bench_rets)
    except Exception as e:
        logger.warning(f"Beta computation failed, using default: {e}")

    return {
        "tickers": tickers,
        "weights": weights,
        "asset_configs": asset_configs,
        "fundamentals": fundamentals,
        "dates": dates_list,
        "portfolio_prices": port_prices_list,
        "price_data": price_data,
        "aligned": aligned,
        "all_dates": all_dates,
        "port_returns": port_returns,
        "forecast_result": forecast_result,
        "risk_data": risk_data,
        "qmc_result": qmc_result,
        "asset_forecasts": asset_forecasts,
        "performance": perf,
        "risk_metrics": {
            "sharpe_ratio": perf.get("sharpe_ratio", 0.0),
            "sortino_ratio": perf.get("sortino_ratio", 0.0),
            "max_drawdown": perf.get("max_drawdown", 0.0),
            "annualized_vol": perf.get("annualized_volatility", 0.0),
            # None when the risk engine returned nothing: templates render
            # n/a rather than an invented default.
            "var_95_daily": risk_metrics.get("var_95"),
            "cvar_95_daily": risk_metrics.get("cvar_95"),
            "beta": beta,
            "fragility_score": unbox(risk_data.get("fragility_score_latest", 1.0)),
            "regime": str(risk_data.get("regime_latest", "Normal")),
        },
        "model_used": forecast_result.get("model_used", "unknown"),
        "model_validation": forecast_result.get("model_validation", {}),
    }


def _pdf_response(filepath: str, filename: str) -> StreamingResponse:
    """Stream a PDF file as a download response."""
    def _stream():
        with open(filepath, "rb") as f:
            yield from iter(lambda: f.read(8192), b"")
        # Cleanup temp file
        try:
            os.unlink(filepath)
        except OSError:
            pass

    return StreamingResponse(
        _stream(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_review_year_prices(data: dict, year: int) -> pd.Series:
    """Daily portfolio prices covering the review year: prefer the MarketData
    table, fall back to the price frames already fetched for this report.
    Returns an empty series when neither source has real data."""
    start, end = datetime(year, 1, 1), datetime(year, 12, 31)
    try:
        with Session(engine) as session:
            port_daily, _ = build_portfolio_daily_prices(
                data["tickers"], data["weights"], start, end, session,
            )
        if len(port_daily) >= 2:
            return port_daily
    except Exception as e:
        logger.warning(f"MarketData portfolio series failed for {year}: {e}")

    frames = {}
    for ticker, df in (data.get("price_data") or {}).items():
        if df is None or not len(df):
            continue
        s = df.copy()
        s["date"] = pd.to_datetime(s["date"])
        mask = (s["date"] >= pd.Timestamp(start)) & (s["date"] <= pd.Timestamp(end))
        s = s[mask].sort_values("date")
        if len(s) >= 2:
            frames[ticker] = s.set_index("date")["price"]
    if not frames:
        return pd.Series(dtype=float)
    all_dates = pd.DatetimeIndex(
        sorted(set().union(*[set(s.index) for s in frames.values()]))
    )
    port_returns = pd.Series(0.0, index=all_dates)
    for ticker, s in frames.items():
        aligned = s.reindex(all_dates, method="ffill")
        port_returns += aligned.pct_change().fillna(0) * data["weights"].get(ticker, 0.0)
    return (1 + port_returns).cumprod() * 100


def _monthly_returns_or_none(daily_prices, year: int) -> List[Optional[float]]:
    """12 monthly returns; months with fewer than 2 observations are None,
    never a silent 0.0 rendered as a real month."""
    out: List[Optional[float]] = []
    for month in range(1, 13):
        if daily_prices is None or len(daily_prices) < 2:
            out.append(None)
            continue
        mask = (daily_prices.index.year == year) & (daily_prices.index.month == month)
        month_prices = daily_prices[mask]
        if len(month_prices) >= 2 and float(month_prices.iloc[0]) > 0:
            out.append(float(month_prices.iloc[-1] / month_prices.iloc[0] - 1))
        else:
            out.append(None)
    return out


def _coverage_run(monthly: List[Optional[float]]) -> List[int]:
    """Indices of the first contiguous run of real monthly returns. A gap
    after data begins ends the run: chaining a period return across unknown
    months would be an invented number."""
    first = next((i for i, r in enumerate(monthly) if r is not None), None)
    if first is None:
        return []
    stop = first
    while stop < len(monthly) and monthly[stop] is not None:
        stop += 1
    return list(range(first, stop))


def _cumulative_pct(monthly: List[Optional[float]], cov: List[int]) -> List[Optional[float]]:
    """Cumulative % return per month over the covered run; None elsewhere."""
    out: List[Optional[float]] = [None] * len(monthly)
    running = 1.0
    for i in cov:
        running *= 1.0 + float(monthly[i])
        out[i] = (running - 1.0) * 100.0
    return out


def _compute_yearend_vol(port_daily, year: int) -> List[Optional[float]]:
    """Monthly realized vol (annualized %) from the review-year daily prices.
    Months with fewer than 5 return observations are None, never a 0.0
    rendered as a calm month."""
    if port_daily is None or len(port_daily) < 2:
        return [None] * 12
    returns = port_daily.pct_change().dropna()
    out: List[Optional[float]] = []
    for month in range(1, 13):
        mask = (returns.index.year == year) & (returns.index.month == month)
        month_returns = returns[mask]
        if len(month_returns) >= 5:
            out.append(float(month_returns.std() * np.sqrt(252) * 100))
        else:
            out.append(None)
    return out


def _compute_yearend_fragility(data: dict, year: int) -> List[Optional[float]]:
    """Monthly portfolio-weighted fragility from AssetVolatilitySnapshot.
    Months with no snapshot coverage are None (omitted from the chart), never
    a neutral 1.0 rendered as a real observation."""
    out: List[Optional[float]] = []
    try:
        with Session(engine) as session:
            for month in range(1, 13):
                month_start = datetime(year, month, 1)
                month_end = (datetime(year + 1, 1, 1) if month == 12
                             else datetime(year, month + 1, 1))
                weighted, total_weight = 0.0, 0.0
                for ticker in data["tickers"]:
                    weight = data["weights"].get(ticker, 0.0)
                    if weight <= 0:
                        continue
                    snapshot = session.exec(
                        select(AssetVolatilitySnapshot)
                        .where(AssetVolatilitySnapshot.symbol == ticker)
                        .where(AssetVolatilitySnapshot.as_of >= month_start)
                        .where(AssetVolatilitySnapshot.as_of < month_end)
                        .order_by(AssetVolatilitySnapshot.as_of.desc())
                    ).first()
                    if snapshot and snapshot.fragility_score_latest is not None:
                        weighted += snapshot.fragility_score_latest * weight
                        total_weight += weight
                out.append(weighted / total_weight if total_weight > 0 else None)
    except Exception as e:
        logger.warning(f"Fragility computation failed: {e}")
        return [None] * 12
    return out


def _real_model_accuracy(data: dict) -> Optional[dict]:
    """REAL walk-forward validation figures for the winning model, or None.
    Sources: forecast_result.forecast_quality (the engine's own summary for
    the winner), then model_validation.quality_per_model. Never a hardcoded
    number: when neither source has finite figures the report omits the model
    performance section entirely."""
    def _finite(x):
        try:
            return x is not None and np.isfinite(float(x))
        except (TypeError, ValueError):
            return False

    candidates = []
    fq = (data.get("forecast_result") or {}).get("forecast_quality")
    if isinstance(fq, dict):
        candidates.append(fq)
    model = str(data.get("model_used") or "")
    quality = (data.get("model_validation") or {}).get("quality_per_model") or {}
    if isinstance(quality.get(model), dict):
        candidates.append(dict(quality[model], model=model))
    for c in candidates:
        da, mape = c.get("directional_accuracy"), c.get("mape")
        n = c.get("n_validation_steps")
        if _finite(da) and _finite(mape) and n and int(n) > 0:
            return {
                "hit_rate": float(da),
                "avg_error": float(mape),
                "n_steps": int(n),
                "best_model": str(c.get("model") or model or "unknown"),
            }
    return None


def _compute_top_contributors(data: dict, year: int, top: bool = True) -> List[Dict]:
    """Top/bottom contributors by weighted contribution over the review year.
    Holdings with no price data inside the year are dropped, never shown as
    0.0% observations."""
    start = pd.Timestamp(datetime(year, 1, 1))
    end = pd.Timestamp(datetime(year, 12, 31))
    weights = data.get("weights", {})

    rows = []
    for ticker, df in (data.get("price_data") or {}).items():
        if df is None or not len(df):
            continue
        s = df.copy()
        s["date"] = pd.to_datetime(s["date"])
        period = s[(s["date"] >= start) & (s["date"] <= end)].sort_values("date")
        if len(period) < 2 or float(period["price"].iloc[0]) <= 0:
            continue
        ret = float(period["price"].iloc[-1] / period["price"].iloc[0] - 1)
        rows.append({
            "ticker": ticker,
            "name": data["fundamentals"].get(ticker, {}).get("profile", {}).get("name", ticker),
            "return": ret,
            "contribution": ret * weights.get(ticker, 0.0),
        })
    rows.sort(key=lambda r: r["contribution"], reverse=True)
    # Top 3; bottom 2 drawn only from holdings not already shown as top.
    return rows[:3] if top else rows[3:][-2:]


def _compute_holdings_impact(data: dict, assets: List, window_start: datetime,
                             window_end: datetime) -> List[Dict]:
    """Real per-asset returns and weighted contributions over the event window.
    Assets with no price data inside the window get None (rendered as n/a),
    never a silent 0.0."""
    price_data = data.get("price_data", {})
    weights = data.get("weights", {})

    results = []
    for a in assets:
        ticker = a.ticker.upper()
        ret = None
        df = price_data.get(ticker)
        if df is not None and len(df):
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            mask = (df["date"] >= pd.Timestamp(window_start)) & (df["date"] <= pd.Timestamp(window_end))
            period = df[mask].sort_values("date")
            if len(period) >= 2 and float(period["price"].iloc[0]) > 0:
                ret = float(period["price"].iloc[-1] / period["price"].iloc[0] - 1)
        results.append({
            "ticker": ticker,
            "name": data["fundamentals"].get(ticker, {}).get("profile", {}).get("name", ticker),
            "return": ret,
            "contribution": (ret * weights.get(ticker, 0.0)) if ret is not None else None,
        })
    results.sort(key=lambda r: (r["contribution"] is None, -(r["contribution"] or 0.0)))
    return results


# Honest labels for whichever benchmark symbol actually supplied data.
BENCHMARK_LABELS = {
    "^GSPC": "S&P 500",
    "SPY": "S&P 500 (SPY proxy)",
    "VOO": "S&P 500 (VOO proxy)",
}


def _slice_event_window(dates_iso: List[str], prices: List[float], event_date: datetime,
                        pre_days: int = 15, post_days: int = 15) -> dict:
    """Slice the REAL portfolio series around event_date (trading days).

    Event impact is measured from the last close BEFORE the event through the
    window end. Raises 400 when the event date falls outside the available
    history: the report never fabricates an event window."""
    n = min(len(dates_iso), len(prices))
    if n < 2:
        raise HTTPException(
            status_code=400,
            detail="Not enough portfolio price history to build an event window.",
        )
    try:
        ts = [datetime.fromisoformat(str(x)[:10]) for x in dates_iso[:n]]
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Portfolio price dates are malformed.")
    if event_date < ts[0] or event_date > ts[-1]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"event_date {event_date.date().isoformat()} is outside the available "
                f"price history ({ts[0].date().isoformat()} to {ts[-1].date().isoformat()}). "
                "The report will not fabricate an event window."
            ),
        )
    pos = bisect_left(ts, event_date)  # first trading day on/after the event
    start = max(0, pos - pre_days)
    end = min(n, pos + post_days + 1)
    window_dates = ts[start:end]
    window_prices = np.array(prices[start:end], dtype=float)
    if len(window_prices) < 2 or window_prices[0] <= 0:
        raise HTTPException(
            status_code=400,
            detail="Not enough portfolio price history around the event date.",
        )
    anchor = max(0, pos - 1 - start)  # last trading day BEFORE the event, in-window
    port_idx = window_prices / window_prices[0] * 100.0
    port_dd = (port_idx / np.maximum.accumulate(port_idx) - 1) * 100
    return {
        "dates": window_dates,
        "port_idx": port_idx,
        "port_dd": port_dd,
        "anchor": anchor,
        "event_pos": pos - start,
        "event_return": float(port_idx[-1] / port_idx[anchor] - 1),
        "drawdown_peak": float(port_dd.min() / 100.0),
    }


def _align_benchmark_to_dates(bench_df: pd.DataFrame,
                              window_dates: List[datetime]) -> Optional[np.ndarray]:
    """Align benchmark closes to the portfolio's REAL trading dates, by DATE.
    Returns the indexed series (base 100), or None when alignment is not
    possible (no data, missing endpoints, or sparse coverage): the report then
    omits the benchmark rather than padding a fake one."""
    if bench_df is None or bench_df.empty or not window_dates:
        return None
    closes = (
        bench_df.assign(date=pd.to_datetime(bench_df["date"]).dt.normalize())
        .drop_duplicates("date", keep="last")
        .set_index("date")["close"]
    )
    idx = pd.DatetimeIndex([pd.Timestamp(dt).normalize() for dt in window_dates])
    vals = closes.reindex(idx)
    if pd.isna(vals.iloc[0]) or pd.isna(vals.iloc[-1]) or vals.notna().mean() < 0.9:
        return None
    vals = vals.ffill()
    base = float(vals.iloc[0])
    if base <= 0:
        return None
    return (vals.to_numpy(dtype=float) / base) * 100.0


# ────────────────────────────────────────────────────────────
# ENDPOINTS
# ────────────────────────────────────────────────────────────

@report_router.post("/quarterly")
def generate_quarterly(
    payload: QuarterlyReportRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """
    Generate the flagship Portfolio Risk Intelligence Report.
    Returns a downloadable PDF.
    """
    report_id = uuid.uuid4().hex[:12]
    output_path = os.path.join(REPORT_TMP_DIR, f"quarterly_{report_id}.pdf")
    report_date = datetime.utcnow()

    # Validate cheap inputs BEFORE the expensive engine fetch.
    portfolio_value = _require_portfolio_value(payload.portfolio_value)

    # Fetch live data from your engine
    data = _fetch_portfolio_data(payload.assets, horizon_days=payload.horizon_days)

    # Real scenario section: derived from the client's simulated fans; the AI
    # narrative reuses the scenario explainer (content-hash cached, so a page
    # that already ran the analysis costs nothing here). Failures degrade to a
    # numbers-only section: never to invented numbers.
    scenario_rows: list = []
    scenario_analysis = None
    scenario_items = [
        i.model_dump() for i in (payload.scenarios or [])
        if not i.name.startswith("_")
        and isinstance(i.fan.get("central"), list) and len(i.fan["central"]) >= 2
    ]
    if scenario_items:
        try:
            facts = scenario_explainer.derive_facts(scenario_items, portfolio_value)
            for f in facts:
                ret = f["vs_base_pct"] if f["vs_base_pct"] is not None else f["path_return_pct"]
                scenario_rows.append({
                    "name": f["name"],
                    "is_base": f["is_base"],
                    "return_pct": ret,
                    "dollar_impact": f["dollar_impact"],
                    "downside_pct": f["downside_pct"],
                    "band_pct": f["band_pct"],
                })
        except Exception as e:
            logger.warning(f"Report scenario derivation failed: {e}")
            scenario_rows = []
        if scenario_rows:
            try:
                summary, explanations, _, _ = scenario_explainer.run(
                    portfolio_name=payload.client_name,
                    portfolio_value=portfolio_value,
                    scenarios=scenario_items,
                )
                scenario_analysis = {"summary": summary, "explanations": explanations}
            except Exception as e:
                logger.warning(f"Report scenario AI analysis unavailable: {e}")

    holdings_list = [
        {
            "ticker": a.ticker.upper(),
            "name": data["fundamentals"].get(a.ticker.upper(), {}).get("profile", {}).get("name", a.ticker),
            "sector": data["fundamentals"].get(a.ticker.upper(), {}).get("type", "Equity"),
            "weight": a.weight,
            "value": portfolio_value * a.weight,
        }
        for a in payload.assets
    ]

    # Narrative layer: written analysis grounded in the SAME real facts the
    # report renders. Unavailable -> numbers-only report, never invented text.
    narrative = None
    try:
        fc_res = data.get("forecast_result") or {}
        fp = fc_res.get("forecast_prices") or []
        fc_facts = {}
        if len(fp) >= 2 and fp[0]:
            fc_facts["return_pct"] = (fp[-1] / fp[0] - 1) * 100
            lo, hi = fc_res.get("lower_ci") or [], fc_res.get("upper_ci") or []
            if lo and hi and fp[-1]:
                fc_facts["band_pct"] = (hi[-1] - lo[-1]) / fp[-1] * 100
        narrative, _ = report_narrator.run(facts={
            "portfolio_name": payload.client_name,
            "portfolio_value": portfolio_value,
            "horizon_days": payload.horizon_days,
            "risk_metrics": data["risk_metrics"],
            "forecast": fc_facts,
            "scenarios": scenario_rows,
            "holdings": holdings_list,
        })
    except Exception as e:
        logger.warning(f"Report narrative unavailable: {e}")

    # Build the template data dict
    # (This is where your engine output maps to the template's expected format)
    template_data = {
        "client_name": payload.client_name,
        "advisor_name": payload.advisor_name,
        "firm_name": payload.firm_name,
        "report_date": report_date,
        "portfolio_value": portfolio_value,
        "holdings": holdings_list,
        "risk_metrics": data["risk_metrics"],
        "forecast_result": data["forecast_result"],
        "risk_data": data["risk_data"],
        "portfolio_prices": data["portfolio_prices"],
        "portfolio_dates": data.get("dates", []),
        "scenarios": scenario_rows,
        "scenario_analysis": scenario_analysis,
        "narrative": narrative,
    }

    generate_quarterly_report(output_path, template_data)
    filename = f"risk_report_{payload.client_name.replace(' ', '_')}_{report_date.strftime('%Y%m%d')}.pdf"
    return _pdf_response(output_path, filename)


@report_router.post("/onboarding")
def generate_onboarding(
    payload: OnboardingReportRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """Generate a New Client Risk Assessment report."""
    report_id = uuid.uuid4().hex[:12]
    output_path = os.path.join(REPORT_TMP_DIR, f"onboarding_{report_id}.pdf")
    report_date = datetime.utcnow()

    # Validate cheap inputs BEFORE the expensive engine fetch.
    portfolio_value = _require_portfolio_value(payload.portfolio_value)
    if float(payload.target_vol) <= 0:
        raise HTTPException(
            status_code=400,
            detail="target_vol must be a positive annualized volatility (e.g. 0.10 for 10%).",
        )

    data = _fetch_portfolio_data(payload.assets)
    rm = data["risk_metrics"]
    actual_vol = rm["annualized_vol"]

    # Current allocation grouped by asset TYPE (fundamentals 'type'; labeled
    # honestly as type, not sector). There is no optimizer in this pipeline,
    # so no "recommended" allocation is produced: the old report rendered a
    # copy of the current allocation as a recommendation.
    allocation = {}
    for a in payload.assets:
        t = a.ticker.upper()
        asset_type = data["fundamentals"].get(t, {}).get("type", "Equity")
        allocation[asset_type] = allocation.get(asset_type, 0) + a.weight

    holdings_list = [
        {
            "ticker": a.ticker.upper(),
            "name": data["fundamentals"].get(a.ticker.upper(), {}).get("profile", {}).get("name", a.ticker),
            "asset_type": data["fundamentals"].get(a.ticker.upper(), {}).get("type", "Equity"),
            "weight": a.weight,
            "value": portfolio_value * a.weight,
        }
        for a in payload.assets
    ]

    # Computed findings from the measured risk metrics (no canned advice).
    findings = []
    mismatch = actual_vol - payload.target_vol
    if abs(mismatch) > 0.02:
        direction = "more" if mismatch > 0 else "less"
        findings.append(
            f"Portfolio volatility ({actual_vol*100:.1f}%) is {abs(mismatch)*100:.1f}% "
            f"{direction} than target ({payload.target_vol*100:.0f}%)."
        )
    if rm["max_drawdown"] < -0.15:
        findings.append(
            f"Maximum drawdown of {rm['max_drawdown']*100:.1f}% indicates significant "
            f"tail risk that may exceed comfort level for a "
            f"{escape(payload.risk_tolerance)} investor."
        )
    if rm["sharpe_ratio"] < 0.5:
        findings.append(
            f"Sharpe ratio of {rm['sharpe_ratio']:.2f} suggests the portfolio is not being "
            f"adequately compensated for the risk it takes."
        )
    if not findings:
        findings.append("Portfolio risk metrics are broadly aligned with the stated risk tolerance.")

    # Narrative layer: the measured risk profile in plain terms vs the client's
    # stated tolerance and target, what to watch, and options to evaluate,
    # grounded in the SAME numbers the report renders. Unavailable -> the
    # assessment ships numbers-only, never canned text.
    narrative = None
    try:
        narrative, _ = report_narrator.run_onboarding(facts={
            "portfolio_name": payload.client_name,
            "portfolio_value": portfolio_value,
            "risk_tolerance": payload.risk_tolerance,
            "target_vol": payload.target_vol,
            "risk_metrics": rm,
            "allocation": allocation,
            "holdings": holdings_list,
        })
    except Exception as e:
        logger.warning(f"Onboarding narrative unavailable: {e}")

    template_data = {
        "client_name": payload.client_name,
        "advisor_name": payload.advisor_name,
        "firm_name": payload.firm_name,
        "report_date": report_date,
        "portfolio_value": portfolio_value,
        "risk_tolerance": payload.risk_tolerance,
        "target_vol": payload.target_vol,
        "actual_vol": actual_vol,
        "sharpe": rm["sharpe_ratio"],
        "max_drawdown": rm["max_drawdown"],
        "holdings": holdings_list,
        "current_allocation": allocation,
        "risk_findings": findings,
        "narrative": narrative,
    }

    generate_onboarding_report(output_path, template_data)
    filename = f"onboarding_{payload.client_name.replace(' ', '_')}_{report_date.strftime('%Y%m%d')}.pdf"
    return _pdf_response(output_path, filename)


@report_router.post("/market-event")
def generate_event_report(
    payload: MarketEventReportRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """Generate a Market Event Briefing report."""
    report_id = uuid.uuid4().hex[:12]
    output_path = os.path.join(REPORT_TMP_DIR, f"event_{report_id}.pdf")
    report_date = datetime.utcnow()

    # Validate cheap inputs BEFORE the expensive engine fetch.
    portfolio_value = _require_portfolio_value(payload.portfolio_value)
    try:
        event_date = datetime.fromisoformat(str(payload.event_date)[:10])
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="event_date must be an ISO date (YYYY-MM-DD).")

    data = _fetch_portfolio_data(payload.assets, horizon_days=30)
    rm = data["risk_metrics"]

    # REAL event window: sliced from the portfolio's actual trading dates
    # around event_date (400 if the event falls outside the history).
    window = _slice_event_window(
        data.get("dates", []), data.get("portfolio_prices", []), event_date,
    )
    dates = window["dates"]
    anchor_date = dates[window["anchor"]]

    # Benchmark: fetched for the SAME window and aligned by DATE; omitted when
    # alignment is impossible, never padded.
    bench_idx = None
    bench_label = None
    try:
        with Session(engine) as session:
            bench_df, bench_symbol = get_benchmark_series_labeled(
                DEFAULT_BENCHMARK, dates[0], dates[-1], session,
            )
        bench_idx = _align_benchmark_to_dates(bench_df, dates)
        if bench_idx is not None:
            bench_label = BENCHMARK_LABELS.get(bench_symbol, bench_symbol)
    except Exception as e:
        logger.warning(f"Benchmark unavailable for event window: {e}")
        bench_idx = None

    port_event_return = window["event_return"]
    bench_event_return = None
    bench_dd = None
    if bench_idx is not None:
        bench_event_return = float(bench_idx[-1] / bench_idx[window["anchor"]] - 1)
        bench_dd = ((bench_idx / np.maximum.accumulate(bench_idx)) - 1) * 100

    # Per-holding impact over the SAME span as the headline number: from the
    # last close before the event through the window end.
    holdings_impact = _compute_holdings_impact(data, payload.assets, anchor_date, dates[-1])

    # Forecast facts: the engine's ACTUAL projection, never a canned outlook.
    fc_res = data.get("forecast_result") or {}
    fp = fc_res.get("forecast_prices") or []
    forecast_facts = None
    if len(fp) >= 2 and fp[0]:
        forecast_facts = {
            "model": str(data.get("model_used") or "unknown"),
            "horizon_days": len(fp),
            "return_pct": (fp[-1] / fp[0] - 1) * 100,
            "band_pct": None,
        }
        lo, hi = fc_res.get("lower_ci") or [], fc_res.get("upper_ci") or []
        if lo and hi and fp[-1]:
            forecast_facts["band_pct"] = (hi[-1] - lo[-1]) / fp[-1] * 100

    # Narrative layer: what happened in the window, benchmark comparison, and
    # an outlook grounded in the actual forecast. Unavailable -> the briefing
    # ships numbers-only, never canned text.
    narrative = None
    try:
        narrative, _ = report_narrator.run_market_event(facts={
            "portfolio_name": payload.client_name,
            "portfolio_value": portfolio_value,
            "event_name": payload.event_name,
            "event_date": event_date.date().isoformat(),
            "event_summary": payload.event_summary,
            "window_start": dates[0].date().isoformat(),
            "window_end": dates[-1].date().isoformat(),
            "trading_days": len(dates),
            "portfolio": {
                "event_return": port_event_return,
                "peak_drawdown": window["drawdown_peak"],
            },
            "benchmark": (
                {
                    "label": bench_label,
                    "event_return": bench_event_return,
                    "peak_drawdown": float(np.min(bench_dd)) / 100.0,
                }
                if bench_event_return is not None else None
            ),
            "risk": {"regime": rm["regime"], "fragility_score": rm["fragility_score"]},
            "forecast": forecast_facts,
            "holdings_impact": holdings_impact,
        })
    except Exception as e:
        logger.warning(f"Market event narrative unavailable: {e}")

    template_data = {
        "client_name": payload.client_name,
        "advisor_name": payload.advisor_name,
        "firm_name": payload.firm_name,
        "report_date": report_date,
        "portfolio_value": portfolio_value,
        "event_name": payload.event_name,
        "event_date": event_date,
        "event_summary": payload.event_summary,
        "portfolio_return_event": port_event_return,
        "benchmark_return_event": bench_event_return,
        "benchmark_label": bench_label,
        "portfolio_drawdown_peak": window["drawdown_peak"],
        "regime": rm["regime"],
        "fragility_score": rm["fragility_score"],
        "holdings_impact": holdings_impact,
        "forecast_facts": forecast_facts,
        "narrative": narrative,
        "dates": dates,
        "portfolio_index": window["port_idx"].tolist(),
        "benchmark_index": bench_idx.tolist() if bench_idx is not None else None,
        "portfolio_dd": window["port_dd"].tolist(),
        "benchmark_dd": bench_dd.tolist() if bench_dd is not None else None,
    }

    generate_market_event_report(output_path, template_data)
    filename = f"event_report_{payload.client_name.replace(' ', '_')}_{report_date.strftime('%Y%m%d')}.pdf"
    return _pdf_response(output_path, filename)


@report_router.post("/rebalancing")
def generate_rebalance_report(
    payload: RebalancingReportRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """Generate a Rebalancing Proposal report."""
    report_id = uuid.uuid4().hex[:12]
    output_path = os.path.join(REPORT_TMP_DIR, f"rebalance_{report_id}.pdf")
    report_date = datetime.utcnow()

    # Validate cheap inputs BEFORE the expensive engine fetches.
    portfolio_value = _require_portfolio_value(payload.portfolio_value)

    # Run engine on BOTH current and proposed portfolios
    current_data = _fetch_portfolio_data(payload.current_assets)
    proposed_data = _fetch_portfolio_data(payload.proposed_assets)

    current_rm = current_data["risk_metrics"]
    proposed_rm = proposed_data["risk_metrics"]

    # Build trades list. Share counts come from real last prices; when no
    # price is available the count is omitted, never invented.
    current_weights = {a.ticker.upper(): a.weight for a in payload.current_assets}
    proposed_weights = {a.ticker.upper(): a.weight for a in payload.proposed_assets}
    all_tickers = set(current_weights.keys()) | set(proposed_weights.keys())

    trades = []
    for ticker in sorted(all_tickers):
        cw = current_weights.get(ticker, 0)
        pw = proposed_weights.get(ticker, 0)
        diff = pw - cw
        if abs(diff) < 0.001:
            action = "Hold"
            value = 0.0
            shares = None
        else:
            action = "Buy" if diff > 0 else "Sell"
            value = abs(diff) * portfolio_value
            last_price = _last_cached_price(ticker, current_data, proposed_data)
            shares = int(value / last_price) if last_price else None

        trades.append({
            "ticker": ticker,
            "action": action,
            "shares": shares,
            "value": value,
            "from_weight": cw,
            "to_weight": pw,
        })

    # Scenario stress: ONLY from real simulated runs supplied for BOTH weight
    # sets; scenarios are matched by name and anything unmatched is dropped.
    # Failures degrade to omitting the section, never to invented numbers.
    def _usable_scenarios(items):
        return [
            i.model_dump() for i in (items or [])
            if not i.name.startswith("_")
            and isinstance(i.fan.get("central"), list) and len(i.fan["central"]) >= 2
        ]

    scenario_rows: list = []
    current_items = _usable_scenarios(payload.current_scenarios)
    proposed_items = _usable_scenarios(payload.proposed_scenarios)
    if current_items and proposed_items:
        try:
            current_facts = scenario_explainer.derive_facts(current_items, portfolio_value)
            proposed_by_name = {
                f["name"]: f
                for f in scenario_explainer.derive_facts(proposed_items, portfolio_value)
            }
            for cf in current_facts:
                pf = proposed_by_name.get(cf["name"])
                if pf is None:
                    continue
                c_ret = cf["vs_base_pct"] if cf["vs_base_pct"] is not None else cf["path_return_pct"]
                p_ret = pf["vs_base_pct"] if pf["vs_base_pct"] is not None else pf["path_return_pct"]
                if c_ret is None or p_ret is None:
                    continue
                scenario_rows.append({
                    "name": cf["name"],
                    "is_base": cf["is_base"],
                    "current_return_pct": c_ret,
                    "proposed_return_pct": p_ret,
                })
        except Exception as e:
            logger.warning(f"Rebalancing scenario derivation failed: {e}")
            scenario_rows = []

    current_metrics = {
        "annualized_vol": current_rm["annualized_vol"],
        "max_drawdown": current_rm["max_drawdown"],
        "var_95": current_rm["var_95_daily"],
        "sharpe": current_rm["sharpe_ratio"],
        "sortino": current_rm["sortino_ratio"],
    }
    proposed_metrics = {
        "annualized_vol": proposed_rm["annualized_vol"],
        "max_drawdown": proposed_rm["max_drawdown"],
        "var_95": proposed_rm["var_95_daily"],
        "sharpe": proposed_rm["sharpe_ratio"],
        "sortino": proposed_rm["sortino_ratio"],
    }

    # Narrative layer: what the proposal changes and why it matters, grounded
    # in the SAME computed deltas the report renders. Unavailable -> the PDF
    # ships numbers-only, never canned text.
    narrative = None
    try:
        narrative, _ = report_narrator.run_rebalancing(facts={
            "portfolio_name": payload.client_name,
            "portfolio_value": portfolio_value,
            "current_metrics": current_metrics,
            "proposed_metrics": proposed_metrics,
            "trades": trades,
            "scenarios": scenario_rows,
            "rationale": payload.rationale,
        })
    except Exception as e:
        logger.warning(f"Rebalancing narrative unavailable: {e}")

    template_data = {
        "client_name": payload.client_name,
        "advisor_name": payload.advisor_name,
        "firm_name": payload.firm_name,
        "report_date": report_date,
        "portfolio_value": portfolio_value,
        "current_metrics": current_metrics,
        "proposed_metrics": proposed_metrics,
        "trades": trades,
        "scenarios": scenario_rows,
        "rationale": payload.rationale,
        "tax_considerations": payload.tax_considerations,
        "narrative": narrative,
    }

    generate_rebalancing_report(output_path, template_data)
    filename = f"rebalance_{payload.client_name.replace(' ', '_')}_{report_date.strftime('%Y%m%d')}.pdf"
    return _pdf_response(output_path, filename)


@report_router.post("/year-end")
def generate_year_end(
    payload: YearEndReportRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """Generate a Year-End Portfolio Review report."""
    report_id = uuid.uuid4().hex[:12]
    output_path = os.path.join(REPORT_TMP_DIR, f"yearend_{report_id}.pdf")
    report_date = datetime.utcnow()
    year = payload.review_year

    # Dollar values are optional and rendered only when actually supplied: the
    # report never invents an AUM and never derives an ending value by
    # assuming zero flows over the year.
    def _positive_or_none(v):
        try:
            return float(v) if v is not None and float(v) > 0 else None
        except (TypeError, ValueError):
            return None

    value_start = _positive_or_none(payload.portfolio_value_start)
    value_end = _positive_or_none(payload.portfolio_value_end)

    data = _fetch_portfolio_data(payload.assets, horizon_days=90)
    rm = data["risk_metrics"]

    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    # REAL review-year monthly series; months without data stay None, and the
    # endpoint refuses to fabricate a review when no month has data.
    port_daily = _build_review_year_prices(data, year)
    monthly_returns = _monthly_returns_or_none(port_daily, year)
    cov = _coverage_run(monthly_returns)
    if not cov:
        raise HTTPException(
            status_code=400,
            detail=(f"No portfolio price data is available for {year}: "
                    "the report will not fabricate a year in review."),
        )

    # Benchmark: labeled with whichever symbol actually supplied the data, and
    # omitted entirely unless it covers every month the portfolio covers.
    bench_monthly: Optional[List[Optional[float]]] = None
    bench_label = None
    try:
        with Session(engine) as session:
            bench_df, bench_symbol = get_benchmark_series_labeled(
                DEFAULT_BENCHMARK, datetime(year, 1, 1), datetime(year, 12, 31), session,
            )
        if bench_symbol and not bench_df.empty:
            closes = (bench_df.assign(date=pd.to_datetime(bench_df["date"]))
                      .sort_values("date").set_index("date")["close"])
            bench_monthly = _monthly_returns_or_none(closes, year)
            bench_label = BENCHMARK_LABELS.get(bench_symbol, bench_symbol)
    except Exception as e:
        logger.warning(f"Benchmark unavailable for year-end report: {e}")
    if bench_monthly is None or any(bench_monthly[i] is None for i in cov):
        bench_monthly = None
        bench_label = None

    ytd_return = float(np.prod([1 + monthly_returns[i] for i in cov]) - 1)
    port_cum = _cumulative_pct(monthly_returns, cov)
    bench_ytd = None
    bench_cum = None
    if bench_monthly is not None:
        bench_ytd = float(np.prod([1 + bench_monthly[i] for i in cov]) - 1)
        bench_cum = _cumulative_pct(bench_monthly, cov)

    full_year = cov == list(range(12))
    coverage_label = (
        f"January to December {year}" if full_year else
        f"{datetime(year, cov[0] + 1, 1).strftime('%B')} to "
        f"{datetime(year, cov[-1] + 1, 1).strftime('%B')} {year}"
    )
    metrics_window_label = (
        f"engine's trailing two-year analysis window ending "
        f"{report_date.strftime('%B %d, %Y')}"
    )

    vol_series = _compute_yearend_vol(port_daily, year)
    fragility_series = _compute_yearend_fragility(data, year)
    model_accuracy = _real_model_accuracy(data)
    top_contributors = _compute_top_contributors(data, year, top=True)
    bottom_contributors = _compute_top_contributors(data, year, top=False)

    # Narrative layer: how the year actually went, honest model commentary
    # only when real walk-forward figures exist, and a year-ahead grounded in
    # the current regime. Unavailable -> numbers-only report, never canned
    # macro themes.
    narrative = None
    try:
        narrative, _ = report_narrator.run_yearend(facts={
            "portfolio_name": payload.client_name,
            "review_year": year,
            "portfolio_value_start": value_start,
            "portfolio_value_end": value_end,
            "return_period": ytd_return,
            "coverage_label": coverage_label,
            "benchmark": ({"label": bench_label, "return_period": bench_ytd}
                          if bench_ytd is not None else None),
            "monthly_returns": [
                {"month": months[i], "return": monthly_returns[i]} for i in cov
            ],
            "risk_metrics": {
                "annualized_vol": rm["annualized_vol"],
                "sharpe": rm["sharpe_ratio"],
                "sortino": rm["sortino_ratio"],
                "max_drawdown": rm["max_drawdown"],
                "regime": rm["regime"],
                "fragility_score": rm["fragility_score"],
            },
            "metrics_window": metrics_window_label,
            "vol_series": [{"month": months[i], "vol": v}
                           for i, v in enumerate(vol_series) if v is not None],
            "fragility_series": [{"month": months[i], "fragility": f}
                                 for i, f in enumerate(fragility_series) if f is not None],
            "model_accuracy": model_accuracy,
            "top_contributors": top_contributors,
            "bottom_contributors": bottom_contributors,
        })
    except Exception as e:
        logger.warning(f"Year-end narrative unavailable: {e}")

    template_data = {
        "client_name": payload.client_name,
        "advisor_name": payload.advisor_name,
        "firm_name": payload.firm_name,
        "report_date": report_date,
        "review_year": year,
        "portfolio_value_start": value_start,
        "portfolio_value_end": value_end,
        "portfolio_return_ytd": ytd_return,
        "coverage_label": coverage_label,
        "full_year": full_year,
        "benchmark_return_ytd": bench_ytd,
        "benchmark_label": bench_label,
        "sharpe": rm["sharpe_ratio"],
        "sortino": rm["sortino_ratio"],
        "max_drawdown": rm["max_drawdown"],
        "annualized_vol": rm["annualized_vol"],
        "metrics_window_label": metrics_window_label,
        "regime": rm["regime"],
        "fragility_score": rm["fragility_score"],
        "months": months,
        "portfolio_cumulative": port_cum,
        "benchmark_cumulative": bench_cum,
        "monthly_returns": monthly_returns,
        "vol_series": vol_series,
        "fragility_series": fragility_series,
        "model_accuracy": model_accuracy,
        "top_contributors": top_contributors,
        "bottom_contributors": bottom_contributors,
        "narrative": narrative,
        "proposed_changes": payload.proposed_changes,
    }

    generate_yearend_report(output_path, template_data)
    filename = f"yearend_{year}_{payload.client_name.replace(' ', '_')}.pdf"
    return _pdf_response(output_path, filename)


# ────────────────────────────────────────────────────────────
# PORTFOLIO-LINKED SHORTCUT (uses stored portfolios)
# ────────────────────────────────────────────────────────────

@report_router.post("/portfolio/{portfolio_id}/quarterly")
def generate_portfolio_quarterly(
    portfolio_id: int,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
    advisor_name: str = Query(default="Financial Advisor"),
    firm_name: str = Query(default="Advisory Firm"),
):
    """
    Generate quarterly report for a saved portfolio.
    Pulls holdings directly from the Portfolio/Position tables.
    """
    with Session(engine) as session:
        uid = _resolve_user(user_id, x_user_id)
        portfolio = session.exec(
            select(Portfolio)
            .where(Portfolio.id == portfolio_id)
            .where(Portfolio.user_id == uid)
        ).first()
        if not portfolio:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        positions = session.exec(
            select(Position).where(Position.portfolio_id == portfolio_id)
        ).all()
        if not positions:
            raise HTTPException(status_code=400, detail="Portfolio has no positions")

    assets = [
        ReportAsset(ticker=p.ticker, weight=p.weight)
        for p in positions
    ]

    return generate_quarterly(
        QuarterlyReportRequest(
            client_name=portfolio.name or f"Portfolio #{portfolio_id}",
            advisor_name=advisor_name,
            firm_name=firm_name,
            assets=assets,
        ),
        user_id=user_id,
        x_user_id=x_user_id,
    )
