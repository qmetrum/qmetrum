#!/usr/bin/env python3
"""
nightly_batch.py — Production nightly data refresh (12:30 AM ET).

Fetches EOD OHLCV for all instruments in the asset table, computes
daily/monthly returns for benchmarks and assets, and pre-warms
portfolio forecast caches.

Usage:
  python scripts/nightly_batch.py
  python scripts/nightly_batch.py --symbols AAPL,MSFT
  python scripts/nightly_batch.py --benchmarks-only
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd
from sqlmodel import Session, select

# Ensure app package is importable
sys.path.insert(0, ".")

from app.db.database import engine
from app.db.models import (
    Asset,
    AssetReturn,
    BenchmarkReturn,
    MarketData,
)
from app.vendors import get_vendor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Default benchmarks to pre-compute returns for
DEFAULT_BENCHMARKS = ["^GSPC", "^DJI", "SPY", "QQQ", "AGG", "BND"]

# Target universe for nightly refresh
TARGET_UNIVERSE = {
    # US Equities (DOW 30 + mega-cap)
    "US_EQUITY": [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
        "JPM", "BAC", "WFC", "GS", "MS", "BLK", "AXP",
        "UNH", "JNJ", "PFE", "MRK", "ABBV", "BMY",
        "XOM", "CVX", "COP",
        "WMT", "COST", "PG", "KO", "PEP", "MCD", "NKE",
        "V", "MA", "DIS", "UBER",
        "CAT", "DE", "LMT", "RTX", "GE", "HON",
    ],
    # Global indices
    "INDEX": ["^GSPC", "^DJI", "^IXIC", "^RUT"],
    # ETFs
    "ETF": [
        "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "SCHD",
        "XLK", "XLF", "XLV", "XLE", "XLI", "XLP", "XLY", "XLU",
        "VNQ", "ARKK",
        "GLD", "SLV", "DBC",
    ],
    # Bond ETFs
    "BOND_ETF": ["AGG", "BND", "TLT", "IEF", "SHY", "LQD", "HYG", "BIL"],
    # Commodities (futures)
    "COMMODITY": ["GC=F", "SI=F", "CL=F", "NG=F", "HG=F"],
    # Crypto
    "CRYPTO": [
        "BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "AVAX-USD",
        "DOT-USD", "LINK-USD", "MATIC-USD", "XRP-USD", "DOGE-USD",
    ],
}


def get_all_symbols() -> List[str]:
    """Get flat list of all symbols in the target universe."""
    symbols = []
    for asset_class_symbols in TARGET_UNIVERSE.values():
        symbols.extend(asset_class_symbols)
    return sorted(set(symbols))


def get_asset_class(symbol: str) -> str:
    """Determine asset class for a symbol."""
    for asset_class, symbols in TARGET_UNIVERSE.items():
        if symbol in symbols:
            return asset_class
    return "US_EQUITY"


def refresh_eod_prices(session: Session, symbols: List[str]) -> int:
    """Fetch and upsert EOD OHLCV for all symbols. Returns count of symbols updated."""
    vendor = get_vendor()
    updated = 0
    now = datetime.utcnow()

    for i, symbol in enumerate(symbols, 1):
        logger.info(f"[{i}/{len(symbols)}] Fetching EOD for {symbol}")
        try:
            rows = vendor.fetch_price_history(symbol, period="5d")
            if not rows:
                logger.warning(f"  No data returned for {symbol}")
                continue

            # Ensure asset exists
            asset = session.get(Asset, symbol.upper())
            if not asset:
                asset = Asset(
                    symbol=symbol.upper(),
                    name=symbol,
                    asset_type="UNKNOWN",
                    asset_class=get_asset_class(symbol),
                    vendor=vendor.name,
                    vendor_symbol=symbol,
                    created_at=now,
                    updated_at=now,
                )
                session.add(asset)
                session.flush()

            for row in rows:
                date_value = datetime.strptime(str(row["date"]), "%Y-%m-%d")
                close_price = float(row.get("close", row.get("price", 0.0)))
                existing = session.exec(
                    select(MarketData)
                    .where(MarketData.symbol == symbol.upper())
                    .where(MarketData.date == date_value)
                ).first()

                if existing:
                    existing.open = float(row.get("open", close_price))
                    existing.high = float(row.get("high", close_price))
                    existing.low = float(row.get("low", close_price))
                    existing.close = close_price
                    existing.volume = float(row.get("volume", 0))
                    existing.updated_at = now
                else:
                    session.add(MarketData(
                        symbol=symbol.upper(),
                        date=date_value,
                        open=float(row.get("open", close_price)),
                        high=float(row.get("high", close_price)),
                        low=float(row.get("low", close_price)),
                        close=close_price,
                        volume=float(row.get("volume", 0)),
                        source=vendor.name,
                        created_at=now,
                        updated_at=now,
                    ))

            session.commit()
            updated += 1

        except Exception as e:
            logger.error(f"  Error refreshing {symbol}: {e}")
            session.rollback()

    return updated


def compute_and_store_returns(
    session: Session,
    symbols: List[str],
    benchmarks: List[str],
    lookback_days: int = 400,
) -> None:
    """Compute daily and monthly returns for assets and benchmarks."""
    now = datetime.utcnow()
    cutoff = now - timedelta(days=lookback_days)

    # --- Asset daily returns ---
    logger.info("Computing asset daily returns...")
    for symbol in symbols:
        rows = session.exec(
            select(MarketData)
            .where(MarketData.symbol == symbol.upper())
            .where(MarketData.date >= cutoff)
            .order_by(MarketData.date.asc())
        ).all()
        if len(rows) < 2:
            continue

        for i in range(1, len(rows)):
            prev_close = rows[i - 1].close
            curr_close = rows[i].close
            if prev_close == 0:
                continue
            daily_ret = (curr_close / prev_close) - 1

            existing = session.exec(
                select(AssetReturn)
                .where(AssetReturn.symbol == symbol.upper())
                .where(AssetReturn.date == rows[i].date)
                .where(AssetReturn.period == "daily")
            ).first()

            if existing:
                existing.return_pct = daily_ret
                existing.updated_at = now
            else:
                session.add(AssetReturn(
                    symbol=symbol.upper(),
                    date=rows[i].date,
                    period="daily",
                    return_pct=daily_ret,
                    created_at=now,
                    updated_at=now,
                ))

        session.commit()

    # --- Benchmark returns ---
    logger.info("Computing benchmark returns...")
    for bench_symbol in benchmarks:
        canon = bench_symbol.upper()
        rows = session.exec(
            select(MarketData)
            .where(MarketData.symbol == canon)
            .where(MarketData.date >= cutoff)
            .order_by(MarketData.date.asc())
        ).all()
        if len(rows) < 2:
            logger.warning(f"  Not enough data for benchmark {canon}")
            continue

        prices = [r.close for r in rows]
        dates = [r.date for r in rows]
        cum_return = 0.0

        for i in range(1, len(rows)):
            if prices[i - 1] == 0:
                continue
            daily_ret = (prices[i] / prices[i - 1]) - 1
            cum_return = (1 + cum_return) * (1 + daily_ret) - 1

            existing = session.exec(
                select(BenchmarkReturn)
                .where(BenchmarkReturn.benchmark_symbol == canon)
                .where(BenchmarkReturn.date == dates[i])
                .where(BenchmarkReturn.period == "daily")
            ).first()

            if existing:
                existing.return_pct = daily_ret
                existing.cumulative_return = cum_return
                existing.updated_at = now
            else:
                session.add(BenchmarkReturn(
                    benchmark_symbol=canon,
                    date=dates[i],
                    period="daily",
                    return_pct=daily_ret,
                    cumulative_return=cum_return,
                    created_at=now,
                    updated_at=now,
                ))

        session.commit()

    logger.info("Return computation complete.")


def precompute_asset_forecasts(
    session: Session,
    symbols: List[str],
    horizon_days: int = 90,
) -> int:
    """Run HybridForecaster on each symbol and cache the result in ForecastCache."""
    from app.logic.forecasting_logic import HybridForecaster
    from app.services.market_store import get_price_series_cached
    from app.db.models import ForecastCache

    computed = 0
    now = datetime.utcnow()

    for i, symbol in enumerate(symbols, 1):
        canon = symbol.upper()
        logger.info(f"  [{i}/{len(symbols)}] Forecasting {canon}")
        try:
            raw_data = get_price_series_cached(canon, period="2y", session=session)
            if not raw_data or len(raw_data) < 60:
                logger.warning(f"    Skipping {canon}: insufficient price data ({len(raw_data or [])} points)")
                continue

            df = pd.DataFrame(raw_data)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            data_last_date = df["date"].iloc[-1].to_pydatetime()

            # Check if we already have a fresh cache for this data
            existing = session.exec(
                select(ForecastCache)
                .where(ForecastCache.ticker == canon)
                .where(ForecastCache.horizon_days == horizon_days)
                .where(ForecastCache.data_last_date == data_last_date)
                .order_by(ForecastCache.run_date.desc())
            ).first()
            if existing and existing.forecast_blob:
                logger.info(f"    {canon} already cached for {data_last_date.date()}, skipping")
                continue

            forecaster = HybridForecaster()
            forecaster.train(df)
            result = forecaster.predict(forecast_horizon_days=horizon_days)

            final_pred = result.get("forecast_prices", [0.0])[-1] if result.get("forecast_prices") else 0.0
            fragility = result.get("risk_metrics", {}).get("fragility_score", 0.0)
            var_95 = result.get("risk_metrics", {}).get("var_95", 0.0)

            cache = ForecastCache(
                ticker=canon,
                run_date=now,
                horizon_days=horizon_days,
                winner_model=result.get("model_used", "unknown"),
                model_version="v1",
                training_window_start=df["date"].iloc[0].to_pydatetime(),
                training_window_end=data_last_date,
                data_last_date=data_last_date,
                forecast_blob=result,
                final_predicted_price=float(final_pred or 0.0),
                fragility_score=float(fragility or 0.0),
                var_95=float(var_95 or 0.0),
            )
            session.add(cache)
            session.commit()
            computed += 1
            logger.info(f"    {canon} forecast cached (model={result.get('model_used', '?')})")

        except Exception as e:
            logger.error(f"    Forecast failed for {canon}: {e}")
            session.rollback()

    return computed


def precompute_asset_risk(
    session: Session,
    symbols: List[str],
    horizon_days: int = 90,
    n_paths: int = 1000,
) -> int:
    """Run R GARCH risk on each symbol and cache results."""
    from app.services.risk_client import calculate_risk
    from app.services.market_store import get_price_series_cached
    from app.db.models import AssetRiskCache, AssetVolatilitySnapshot

    computed = 0
    now = datetime.utcnow()

    for i, symbol in enumerate(symbols, 1):
        canon = symbol.upper()
        logger.info(f"  [{i}/{len(symbols)}] Risk for {canon}")
        try:
            raw_data = get_price_series_cached(canon, period="2y", session=session)
            if not raw_data or len(raw_data) < 60:
                continue

            prices = [float(r["price"]) for r in raw_data]
            data_last_date = datetime.strptime(raw_data[-1]["date"], "%Y-%m-%d")

            # Check existing cache freshness
            existing = session.exec(
                select(AssetRiskCache)
                .where(AssetRiskCache.symbol == canon)
                .where(AssetRiskCache.horizon_days == horizon_days)
                .where(AssetRiskCache.n_paths == n_paths)
                .where(AssetRiskCache.data_last_date == data_last_date)
            ).first()
            if existing:
                logger.info(f"    {canon} risk already cached, skipping")
                continue

            risk_data = calculate_risk(
                prices=prices,
                horizon=horizon_days,
                n_paths=n_paths,
                require_success=False,
            )
            if not risk_data:
                logger.warning(f"    {canon} risk service returned empty")
                continue

            cache_row = AssetRiskCache(
                symbol=canon,
                method="classical_r",
                horizon_days=horizon_days,
                n_paths=n_paths,
                data_last_date=data_last_date,
                result_blob=risk_data,
                created_at=now,
                updated_at=now,
            )
            session.add(cache_row)

            # Also write a volatility snapshot
            def _float(v):
                if isinstance(v, list):
                    return float(v[0]) if v else None
                return float(v) if v is not None else None

            snapshot = AssetVolatilitySnapshot(
                symbol=canon,
                as_of=now,
                method="classical_r",
                horizon_days=horizon_days,
                n_paths=n_paths,
                data_last_date=data_last_date,
                sigma_latest=_float(risk_data.get("sigma_latest")),
                sigma_next=_float(risk_data.get("sigma_next")),
                var_95_latest=_float(risk_data.get("var_95")),
                fragility_score_latest=_float(risk_data.get("fragility_score_latest")),
                regime_latest=str(risk_data.get("regime_latest", "Normal")),
                snapshot_blob=risk_data,
                created_at=now,
            )
            session.add(snapshot)
            session.commit()
            computed += 1

        except Exception as e:
            logger.error(f"    Risk failed for {canon}: {e}")
            session.rollback()

    return computed


def precompute_portfolio_forecasts(
    session: Session,
    horizon_days: int = 90,
    force_refresh: bool = False,
) -> int:
    """Pre-compute portfolio-level forecasts and report data for all stored portfolios.

    When force_refresh is False (default), portfolios whose cache row already
    matches the latest available market data are skipped — so a killed-and-restarted
    run resumes where it left off instead of re-doing portfolio 1.
    """
    from app.logic.forecasting_logic import HybridForecaster
    from app.logic.quantum_vqmc_trained import simulate_trained_vqmc
    from app.services.market_store import get_price_series_cached, get_fundamentals_cached
    from app.services.risk_client import calculate_risk
    from app.db.models import (
        Portfolio, Position, PortfolioForecastCache, PortfolioReportDataCache,
        RiskSimulationCache, MarketData, ForecastCache,
    )
    from sqlalchemy import func as sa_func
    import hashlib, json

    computed = 0
    now = datetime.utcnow()

    portfolios = session.exec(select(Portfolio)).all()
    logger.info(f"Pre-computing forecasts for {len(portfolios)} portfolios")

    for portfolio in portfolios:
        pid = portfolio.id
        logger.info(f"  Portfolio {pid}: {portfolio.name}")

        positions = session.exec(
            select(Position).where(Position.portfolio_id == pid)
        ).all()
        if not positions:
            logger.warning(f"    No positions, skipping")
            continue

        tickers = [p.ticker.upper() for p in positions]
        weights = {p.ticker.upper(): p.weight for p in positions}
        total_w = sum(weights.values())
        if total_w > 0:
            weights = {k: v / total_w for k, v in weights.items()}

        # Resumability: skip if a cache row already exists for the latest market data.
        if not force_refresh:
            latest_market_date = session.exec(
                select(sa_func.max(MarketData.date))
                .where(MarketData.symbol.in_(tickers))
            ).first()
            if latest_market_date is not None:
                existing_fresh = session.exec(
                    select(PortfolioReportDataCache)
                    .where(PortfolioReportDataCache.portfolio_id == pid)
                    .where(PortfolioReportDataCache.data_last_date >= latest_market_date)
                    .order_by(PortfolioReportDataCache.updated_at.desc())
                ).first()
                if existing_fresh is not None:
                    logger.info(
                        f"    Already cached for data_last_date={latest_market_date.date()}, skipping"
                    )
                    continue

        step = "init"
        try:
            # Fetch price data for all assets
            step = "fetch_prices"
            price_data = {}
            fundamentals = {}
            for ticker in tickers:
                raw = get_price_series_cached(ticker, period="2y", session=session)
                if raw:
                    df = pd.DataFrame(raw)
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date")
                    price_data[ticker] = df
                fund = get_fundamentals_cached(ticker, session=session)
                if fund:
                    fundamentals[ticker] = fund

            if not price_data:
                logger.warning(f"    No price data for any ticker, skipping")
                continue

            # Build portfolio series
            step = "build_portfolio_series"
            all_dates = sorted(set().union(*[set(df["date"]) for df in price_data.values()]))
            aligned = {}
            for ticker, df in price_data.items():
                s = df.set_index("date")["price"].reindex(all_dates, method="ffill")
                aligned[ticker] = s

            port_returns = pd.Series(0.0, index=all_dates)
            for ticker, series in aligned.items():
                ret = series.pct_change().fillna(0)
                port_returns += ret * weights.get(ticker, 0)

            port_prices = (1 + port_returns).cumprod() * 100
            port_prices_list = port_prices.values.tolist()
            dates_list = [d.strftime("%Y-%m-%d") for d in all_dates]

            # Run ensemble forecast on portfolio series
            step = "portfolio_forecast"
            hist_df = pd.DataFrame({"date": all_dates, "price": port_prices.values})
            forecaster = HybridForecaster()
            forecaster.train(hist_df)
            forecast_result = forecaster.predict(forecast_horizon_days=horizon_days)

            # Sanity gate lives inside HybridForecaster.predict() now, so the
            # explosion-detection + geometric fallback already ran above. The
            # response carries `forecast_quality = "fallback_post_explosion"`
            # when it fires.

            # Run risk
            step = "risk_service"
            risk_data = {}
            try:
                risk_data = calculate_risk(
                    prices=port_prices_list,
                    horizon=horizon_days,
                    n_paths=1000,
                    require_success=False,
                ) or {}
            except Exception as e:
                logger.warning(f"    Risk service failed: {e}")

            # Quantum Monte Carlo via trained Qiskit ansatz
            step = "quantum_mc"
            qmc_result = {}
            try:
                qmc_result = simulate_trained_vqmc(
                    historical_prices=port_prices_list[-252:],
                    ticker=f"PORTFOLIO_{pid}",
                    horizon_days=min(horizon_days, 90),
                    n_simulations=5000,
                )
            except Exception as e:
                logger.warning(f"    QMC failed: {e}")

            # Per-asset forecasts (include history prices for UI). Reuse the
            # forecasts phase 4 already computed and stored in ForecastCache so we
            # don't retrain HybridForecaster per ticker (the dominant cost here).
            step = "asset_forecasts"
            asset_forecasts = {}
            latest_prices = {}
            for ticker, df in price_data.items():
                try:
                    ticker_data_last_date = df["date"].iloc[-1].to_pydatetime()
                    cached_fc = session.exec(
                        select(ForecastCache)
                        .where(ForecastCache.ticker == ticker)
                        .where(ForecastCache.horizon_days == horizon_days)
                        .where(ForecastCache.data_last_date == ticker_data_last_date)
                        .order_by(ForecastCache.run_date.desc())
                    ).first()
                    if cached_fc is not None and cached_fc.forecast_blob:
                        af_result = dict(cached_fc.forecast_blob)
                    else:
                        logger.info(
                            f"    No phase-4 ForecastCache hit for {ticker}; training inline"
                        )
                        fc = HybridForecaster()
                        fc.train(df)
                        af_result = fc.predict(forecast_horizon_days=horizon_days)
                    af_result["history_prices"] = df["price"].tolist()
                    af_result["history_dates"] = df["date"].dt.strftime("%Y-%m-%d").tolist()
                    asset_forecasts[ticker] = af_result
                    latest_prices[ticker] = float(df["price"].iloc[-1])
                except Exception as e:
                    logger.warning(f"    Asset forecast for {ticker} failed: {e}")
                    # Still store the last price even if forecast fails
                    if len(df) > 0:
                        latest_prices[ticker] = float(df["price"].iloc[-1])

            # Run the full portfolio analyser (MPS-copula scenarios, monthly returns, drawdown fan)
            # so the cached blob carries everything the UI needs without a live recompute.
            step = "analyze_portfolio"
            portfolio_analysis = {}
            try:
                from app.logic.portfolio_logic import PortfolioManager as _PM
                _pm = _PM([{"ticker": t, "weight": float(weights.get(t, 0.0))} for t in tickers])
                portfolio_analysis = _pm.analyze_portfolio(horizon_days=int(horizon_days)) or {}
            except Exception as e:
                logger.warning(f"    analyze_portfolio for cache blob failed: {e}")

            # Assemble the full data blob (same structure as _fetch_portfolio_data)
            perf = forecast_result.get("performance_metrics", {})
            risk_metrics = forecast_result.get("risk_metrics", {})

            def unbox(val, default=0.0):
                if isinstance(val, list):
                    return float(val[0]) if val else default
                return float(val) if val is not None else default

            # Compute beta
            step = "beta"
            from app.reports.report_data_helpers import (
                compute_portfolio_beta, get_benchmark_series, DEFAULT_BENCHMARK,
            )
            beta = 1.0
            try:
                bench_df = get_benchmark_series(
                    DEFAULT_BENCHMARK,
                    all_dates[0], all_dates[-1],
                    session,
                )
                if not bench_df.empty:
                    bench_prices = bench_df.set_index("date")["close"].reindex(all_dates, method="ffill")
                    bench_rets = bench_prices.pct_change().fillna(0)
                    beta = compute_portfolio_beta(port_returns, bench_rets)
            except Exception:
                pass

            step = "build_result_blob"
            result_blob = {
                "tickers": tickers,
                "weights": {k: float(v) for k, v in weights.items()},
                "latest_prices": latest_prices,
                "fundamentals": fundamentals,
                "dates": dates_list,
                "portfolio_prices": port_prices_list,
                "forecast_result": _make_json_safe(forecast_result),
                "risk_data": _make_json_safe(risk_data),
                "qmc_result": _make_json_safe(qmc_result),
                "asset_forecasts": {k: _make_json_safe(v) for k, v in asset_forecasts.items()},
                "performance": _make_json_safe(perf),
                "risk_metrics": {
                    "sharpe_ratio": perf.get("sharpe_ratio", 0.0),
                    "sortino_ratio": perf.get("sortino_ratio", 0.0),
                    "max_drawdown": perf.get("max_drawdown", 0.0),
                    "annualized_vol": perf.get("annualized_volatility", 0.0),
                    "var_95_daily": risk_metrics.get("var_95", -0.02),
                    "cvar_95_daily": risk_metrics.get("cvar_95", -0.03),
                    "beta": beta,
                    "fragility_score": unbox(risk_data.get("fragility_score_latest", 1.0)),
                    "regime": str(risk_data.get("regime_latest", "Normal")),
                },
                "model_used": forecast_result.get("model_used", "unknown"),
                "model_validation": _make_json_safe(forecast_result.get("model_validation", {})),
                # Portfolio-analysis payloads needed by the UI cache path
                "portfolio_summary_extras": _make_json_safe({
                    "scenarios": (portfolio_analysis.get("portfolio_summary") or {}).get("scenarios"),
                    "scenarios_legacy": (portfolio_analysis.get("portfolio_summary") or {}).get("scenarios_legacy"),
                    "drawdown_series": (portfolio_analysis.get("portfolio_summary") or {}).get("drawdown_series"),
                    "monthly_returns": (portfolio_analysis.get("portfolio_summary") or {}).get("monthly_returns"),
                    "upper_ci": (portfolio_analysis.get("portfolio_summary") or {}).get("upper_ci"),
                    "lower_ci": (portfolio_analysis.get("portfolio_summary") or {}).get("lower_ci"),
                }),
            }

            # Compute input hash for cache key
            step = "hash_and_write"
            hash_input = json.dumps(
                {"portfolio_id": pid, "tickers": sorted(tickers),
                 "weights": {k: round(v, 6) for k, v in sorted(weights.items())},
                 "last_date": dates_list[-1] if dates_list else ""},
                sort_keys=True,
            )
            input_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
            data_last_date = datetime.strptime(dates_list[-1], "%Y-%m-%d") if dates_list else now

            # Write to PortfolioReportDataCache (for report endpoints)
            existing = session.exec(
                select(PortfolioReportDataCache)
                .where(PortfolioReportDataCache.portfolio_id == pid)
                .where(PortfolioReportDataCache.input_hash == input_hash)
            ).first()
            if existing:
                existing.result_blob = result_blob
                existing.updated_at = now
            else:
                session.add(PortfolioReportDataCache(
                    portfolio_id=pid,
                    input_hash=input_hash,
                    horizon_days=horizon_days,
                    data_last_date=data_last_date,
                    result_blob=result_blob,
                    created_at=now,
                    updated_at=now,
                ))

            # Write to PortfolioForecastCache (for UI /portfolios/{id}/forecast endpoint)
            # Must use the same input_hash format as main.py's forecast_portfolio_v2
            assets_for_hash = [{"ticker": t, "weight": weights[t]} for t in sorted(tickers)]
            latest_market_dates = {}
            for ticker in tickers:
                row = session.exec(
                    select(sa_func.max(MarketData.date))
                    .where(MarketData.symbol == ticker)
                ).first()
                latest_market_dates[ticker] = row.isoformat() if row else None

            ui_hash_payload = {
                "entity_type": "portfolio",
                "entity_id": str(pid),
                "assets": assets_for_hash,
                "horizon_days": int(horizon_days),
                "scenarios": [],
                "target_weights": {},
                "latest_market_dates": latest_market_dates,
            }
            ui_input_hash = hashlib.sha256(
                json.dumps(ui_hash_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
            ).hexdigest()

            # Build a PortfolioManager-style result blob for the UI
            ui_result_blob = _make_json_safe(result_blob)

            existing_pfc = session.exec(
                select(PortfolioForecastCache)
                .where(PortfolioForecastCache.owner_user_id == portfolio.user_id)
                .where(PortfolioForecastCache.entity_type == "portfolio")
                .where(PortfolioForecastCache.entity_id == str(pid))
                .where(PortfolioForecastCache.input_hash == ui_input_hash)
            ).first()
            if existing_pfc:
                existing_pfc.result_blob = ui_result_blob
                existing_pfc.updated_at = now
            else:
                session.add(PortfolioForecastCache(
                    owner_user_id=portfolio.user_id,
                    entity_type="portfolio",
                    entity_id=str(pid),
                    input_hash=ui_input_hash,
                    horizon_days=horizon_days,
                    data_last_date=data_last_date,
                    request_payload={"source": "nightly_batch"},
                    result_blob=ui_result_blob,
                    created_at=now,
                    updated_at=now,
                ))

            session.commit()
            computed += 1
            logger.info(f"    Portfolio {pid} pre-computed and cached")

        except Exception as e:
            logger.error(
                f"    Portfolio {pid} failed at step={step}: {type(e).__name__}: {e}\n"
                f"{traceback.format_exc()}"
            )
            session.rollback()

    return computed


def _make_json_safe(obj):
    """Convert numpy/pandas types to JSON-serializable Python types."""
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def sync_portfolio_cache(session: Session) -> int:
    """
    Copy pre-computed results from PortfolioReportDataCache → PortfolioForecastCache
    so the UI endpoint can find them. No recomputation.
    """
    from app.db.models import (
        Portfolio, Position, PortfolioForecastCache, PortfolioReportDataCache, MarketData,
    )
    from sqlalchemy import func as sa_func
    import hashlib, json

    synced = 0
    now = datetime.utcnow()

    portfolios = session.exec(select(Portfolio)).all()
    for portfolio in portfolios:
        pid = portfolio.id
        # Get latest cached report data
        cached = session.exec(
            select(PortfolioReportDataCache)
            .where(PortfolioReportDataCache.portfolio_id == pid)
            .order_by(PortfolioReportDataCache.updated_at.desc())
        ).first()
        if not cached or not cached.result_blob:
            logger.info(f"  Portfolio {pid}: no cached data to sync")
            continue

        # Build the same input_hash that main.py's forecast_portfolio_v2 uses
        tickers = cached.result_blob.get("tickers", [])
        weights = cached.result_blob.get("weights", {})
        assets_for_hash = [{"ticker": t, "weight": weights.get(t, 0)} for t in sorted(tickers)]

        latest_market_dates = {}
        for ticker in tickers:
            row = session.exec(
                select(sa_func.max(MarketData.date)).where(MarketData.symbol == ticker)
            ).first()
            latest_market_dates[ticker] = row.isoformat() if row else None

        ui_hash_payload = {
            "entity_type": "portfolio",
            "entity_id": str(pid),
            "assets": assets_for_hash,
            "horizon_days": cached.horizon_days,
            "scenarios": [],
            "target_weights": {},
            "latest_market_dates": latest_market_dates,
        }
        ui_input_hash = hashlib.sha256(
            json.dumps(ui_hash_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()

        existing_pfc = session.exec(
            select(PortfolioForecastCache)
            .where(PortfolioForecastCache.owner_user_id == portfolio.user_id)
            .where(PortfolioForecastCache.entity_type == "portfolio")
            .where(PortfolioForecastCache.entity_id == str(pid))
            .where(PortfolioForecastCache.input_hash == ui_input_hash)
        ).first()
        if existing_pfc:
            existing_pfc.result_blob = cached.result_blob
            existing_pfc.updated_at = now
        else:
            session.add(PortfolioForecastCache(
                owner_user_id=portfolio.user_id,
                entity_type="portfolio",
                entity_id=str(pid),
                input_hash=ui_input_hash,
                horizon_days=cached.horizon_days,
                data_last_date=cached.data_last_date,
                request_payload={"source": "sync_from_report_cache"},
                result_blob=cached.result_blob,
                created_at=now,
                updated_at=now,
            ))
        session.commit()
        synced += 1
        logger.info(f"  Portfolio {pid}: synced to UI cache")

    return synced


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly EOD data refresh + forecast pre-computation")
    parser.add_argument("--symbols", default="", help="CSV of specific symbols (default: full universe)")
    parser.add_argument("--benchmarks-only", action="store_true", help="Only recompute benchmark returns")
    parser.add_argument("--skip-returns", action="store_true", help="Skip return computation")
    parser.add_argument("--skip-forecasts", action="store_true", help="Skip per-asset forecast pre-computation")
    parser.add_argument("--skip-risk", action="store_true", help="Skip per-asset risk pre-computation")
    parser.add_argument("--skip-portfolios", action="store_true", help="Skip portfolio-level pre-computation")
    parser.add_argument("--force-refresh-portfolios", action="store_true", help="Recompute portfolios even if cache row matches latest market data")
    parser.add_argument("--forecast-symbols", default="", help="CSV of symbols to forecast (default: key assets)")
    parser.add_argument("--sync-cache", action="store_true", help="Just sync existing results to UI cache (no recomputation)")
    args = parser.parse_args()

    started = time.time()

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = get_all_symbols()

    # Key assets to pre-compute forecasts for (most important ones)
    if args.forecast_symbols:
        forecast_symbols = [s.strip().upper() for s in args.forecast_symbols.split(",") if s.strip()]
    else:
        # Default: tickers held by demo portfolios + key ETFs/benchmarks. Keep this
        # in sync with PORTFOLIO_TEMPLATES in scripts/seed_demo_cache.py — anything
        # missing here forces phase 5 to retrain HybridForecaster inline (slow).
        forecast_symbols = [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
            "SPY", "QQQ", "IWM", "AGG", "TLT", "BND", "GLD",
            "JNJ", "PG", "KO", "XLU", "LQD", "SHY",
        ]

    # Quick sync mode: just copy existing results to UI cache, no computation
    if args.sync_cache:
        logger.info("Sync mode: copying pre-computed results to UI cache...")
        with Session(engine) as session:
            count = sync_portfolio_cache(session)
        logger.info(f"Synced {count} portfolios")
        return 0

    logger.info(f"Nightly batch: {len(symbols)} symbols, {len(forecast_symbols)} forecast targets")

    with Session(engine) as session:
        # Phase 1: EOD prices
        if not args.benchmarks_only:
            updated = refresh_eod_prices(session, symbols)
            logger.info(f"Phase 1 complete: EOD refresh {updated}/{len(symbols)} symbols")

        # Phase 2: Returns
        if not args.skip_returns:
            compute_and_store_returns(session, symbols=symbols, benchmarks=DEFAULT_BENCHMARKS)
            logger.info("Phase 2 complete: returns computed")

        # Phase 3: Per-asset risk (R GARCH)
        if not args.skip_risk:
            logger.info("Phase 3: Per-asset risk computation...")
            risk_count = precompute_asset_risk(session, forecast_symbols)
            logger.info(f"Phase 3 complete: {risk_count} assets risk-computed")

        # Phase 4: Per-asset forecasts
        if not args.skip_forecasts:
            logger.info("Phase 4: Per-asset forecast computation...")
            fc_count = precompute_asset_forecasts(session, forecast_symbols)
            logger.info(f"Phase 4 complete: {fc_count} assets forecasted")

        # Phase 5: Portfolio-level forecasts + report data
        if not args.skip_portfolios:
            logger.info("Phase 5: Portfolio forecast pre-computation...")
            port_count = precompute_portfolio_forecasts(
                session,
                force_refresh=args.force_refresh_portfolios,
            )
            logger.info(f"Phase 5 complete: {port_count} portfolios pre-computed")

    elapsed = time.time() - started
    logger.info(f"Nightly batch complete in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
