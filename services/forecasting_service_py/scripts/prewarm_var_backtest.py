#!/usr/bin/env python3
"""Pre-warm VaR-95 backtest data + caches for demo / showcase portfolios.

Runs IN-PROCESS against the target DB (DATABASE_URL), the same model as
nightly_batch.py — because deepening price history needs
get_price_series_cached(force_refresh=True), which is not exposed over HTTP.

For each target portfolio it does two things:

  1. BACKFILL prices to `--period` (default 5y) for every held ticker, with
     force_refresh=True. This is the load-bearing step: nightly only tops up 5d
     and every app caller asks for 2y, so a 5y request otherwise returns the
     cached ~2y subset. Without real 5y depth the MPS d=4-fails / d=8-passes
     story silently runs on 2y.

  2. WARM the three backtests the VarBacktestCard requests, writing them into
     RiskSimulationCache so the card serves instantly instead of a 30-50s cold
     compute. The cache key is built to MATCH the live endpoints exactly
     (app.main.var_backtest_portfolio / var_backtest_compare_portfolio) — the
     request models supply the same defaults, and the card's overrides
     (mps_fan: n_backtest=120, n_simulations=400) are mirrored here.
     See VarBacktestCard.tsx SINGLE_PAYLOAD / the Compare query.

Usage (from services/forecasting_service_py):
  python scripts/prewarm_var_backtest.py --portfolios 1,2,3
  python scripts/prewarm_var_backtest.py --portfolios all
  python scripts/prewarm_var_backtest.py --portfolios all --skip-compare
  python scripts/prewarm_var_backtest.py --portfolios 1 --skip-backfill   # prices already deep

In AWS, run it the same way the nightly batch runs — as a one-off Fargate task
with the prod DATABASE_URL + market-data vendor env. Warm AFTER the day's EOD
load: the cache key includes latest_market_dates, so new prices invalidate it.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import List

from sqlmodel import Session, select

# Ensure app package is importable (matches nightly_batch.py)
sys.path.insert(0, ".")

from app.db.database import engine
from app.db.models import Portfolio, Position
from app.services.market_store import get_price_series_cached
from app.logic.var_backtest_runner import (
    run_portfolio_var_backtest,
    run_portfolio_var_backtest_comparison,
)
# Reuse the endpoints' own helpers so the cache key + blob match a real request.
from app.main import (
    VarBacktestRequest,
    VarBacktestCompareRequest,
    _normalize_assets,
    _portfolio_latest_market_dates,
    _portfolio_storage_enabled_for_user,
    _save_simulation_cache_result,
    _stable_json_hash,
    _json_compatible,
)


def _resolve_pids(session: Session, spec: str) -> List[int]:
    if spec.strip().lower() == "all":
        rows = session.exec(select(Portfolio.id)).all()
        return [int(r) for r in rows]
    return [int(x) for x in spec.split(",") if x.strip()]


def _single_input_hash(pid, assets, latest_market_dates, req: VarBacktestRequest) -> tuple[str, str]:
    """Mirror app.main.var_backtest_portfolio's input_hash exactly."""
    cache_method = f"var_backtest_{req.method}"
    input_hash = _stable_json_hash({
        "portfolio_id": pid,
        "method": cache_method,
        "assets": assets,
        "confidence": float(req.confidence),
        "horizon_days": int(req.horizon_days),
        "est_window": int(req.est_window),
        "n_backtest": int(req.n_backtest),
        "n_simulations": int(req.n_simulations),
        "random_seed": req.random_seed,
        "latest_market_dates": latest_market_dates,
    })
    return cache_method, input_hash


def _compare_input_hash(pid, assets, latest_market_dates, req: VarBacktestCompareRequest) -> tuple[str, str]:
    """Mirror app.main.var_backtest_compare_portfolio's input_hash exactly."""
    cache_method = "var_backtest_compare"
    input_hash = _stable_json_hash({
        "portfolio_id": pid,
        "method": cache_method,
        "assets": assets,
        "confidence": float(req.confidence),
        "horizon_days": int(req.horizon_days),
        "est_window": int(req.est_window),
        "n_backtest": int(req.n_backtest),
        "n_simulations": int(req.n_simulations),
        "random_seed": req.random_seed,
        "latest_market_dates": latest_market_dates,
    })
    return cache_method, input_hash


def _store(session, pid, cache_method, input_hash, req, runner_result) -> None:
    """Persist a result blob shaped like the endpoint's, so a card hit is identical."""
    result = _json_compatible(runner_result)
    result["portfolio_id"] = pid
    result["cache"] = {
        "hit": False, "cache_type": "risk_simulation",
        "input_hash": input_hash, "method": cache_method, "persisted": True,
    }
    _save_simulation_cache_result(
        session, entity_type="portfolio", entity_id=str(pid), method=cache_method,
        horizon_days=int(req.horizon_days), n_simulations=int(req.n_simulations),
        random_seed=req.random_seed, input_hash=input_hash, data_last_date=None,
        result_blob=result,
    )


def prewarm_portfolio(session, pid, *, period, skip_backfill, skip_compare) -> None:
    pf = session.get(Portfolio, pid)
    if not pf:
        print(f"[pf {pid}] not found — skipping")
        return
    positions = session.exec(select(Position).where(Position.portfolio_id == pid)).all()
    raw_assets = [{"ticker": p.ticker, "weight": p.weight} for p in positions]
    try:
        assets = _normalize_assets(raw_assets)
    except Exception as e:
        print(f"[pf {pid}] '{pf.name}': bad positions ({e}) — skipping")
        return
    if not assets:
        print(f"[pf {pid}] '{pf.name}': no positions — skipping")
        return
    tickers = [a["ticker"] for a in assets]
    print(f"\n[pf {pid}] '{pf.name}' — {len(tickers)} tickers: {', '.join(tickers)}")

    if not _portfolio_storage_enabled_for_user(session, int(pf.user_id)):
        print(f"  ⚠ owner (user {pf.user_id}) has portfolio storage DISABLED — the card will "
              f"NOT read this cache; enable store_portfolio_runs for that user or the warm is moot.")

    # 1. Backfill prices to full depth (the only way past the cached ~2y).
    if skip_backfill:
        print("  backfill: skipped")
    else:
        for t in tickers:
            try:
                series = get_price_series_cached(t, period=period, force_refresh=True)
                print(f"  backfill {t:<8} {len(series):>5} days")
            except Exception as e:
                print(f"  backfill {t:<8} FAILED: {e}")

    # 2. Warm the three card requests. latest_market_dates is computed AFTER the
    #    backfill so it matches what the card will see at request time.
    lmd = _portfolio_latest_market_dates(session, tickers)

    single_reqs = [
        VarBacktestRequest(method="historical"),
        VarBacktestRequest(method="mps_fan", n_backtest=120, n_simulations=400),
    ]
    for req in single_reqs:
        cache_method, input_hash = _single_input_hash(pid, assets, lmd, req)
        t0 = time.time()
        try:
            res = run_portfolio_var_backtest(
                assets=assets, confidence=req.confidence, horizon_days=req.horizon_days,
                est_window=req.est_window, n_backtest=req.n_backtest, method=req.method,
                n_simulations=req.n_simulations, random_seed=req.random_seed,
            )
            _store(session, pid, cache_method, input_hash, req, res)
            print(f"  warm {req.method:<11} {time.time()-t0:5.1f}s  "
                  f"passes={res.get('model_passes')} breach={res.get('breach_rate'):.3f}")
        except Exception as e:
            print(f"  warm {req.method:<11} FAILED: {e}")

    if skip_compare:
        print("  warm compare    : skipped")
        return
    cmp_req = VarBacktestCompareRequest()
    cache_method, input_hash = _compare_input_hash(pid, assets, lmd, cmp_req)
    t0 = time.time()
    try:
        res = run_portfolio_var_backtest_comparison(
            assets=assets, confidence=cmp_req.confidence, horizon_days=cmp_req.horizon_days,
            est_window=cmp_req.est_window, n_backtest=cmp_req.n_backtest,
            n_simulations=cmp_req.n_simulations, random_seed=cmp_req.random_seed,
        )
        _store(session, pid, cache_method, input_hash, cmp_req, res)
        rec = (res.get("recommended") or {}).get("label", "none")
        passers = [m["label"] for m in res.get("methods", [])
                   if m.get("status") == "ok" and m.get("model_passes")]
        print(f"  warm compare     {time.time()-t0:5.1f}s  recommended={rec}  passers={passers}")
    except Exception as e:
        print(f"  warm compare     FAILED: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-warm VaR-95 backtest data + caches.")
    parser.add_argument("--portfolios", default="all", help='CSV of portfolio ids, or "all"')
    parser.add_argument("--period", default="5y", help="price history depth to backfill (default 5y)")
    parser.add_argument("--skip-backfill", action="store_true", help="skip the 5y price backfill")
    parser.add_argument("--skip-compare", action="store_true", help="skip the heavy compare warm")
    args = parser.parse_args()

    t0 = time.time()
    with Session(engine) as session:
        pids = _resolve_pids(session, args.portfolios)
        print(f"Pre-warming {len(pids)} portfolio(s): {pids}  (period={args.period})")
        for pid in pids:
            try:
                prewarm_portfolio(session, pid, period=args.period,
                                  skip_backfill=args.skip_backfill, skip_compare=args.skip_compare)
            except Exception as e:
                print(f"[pf {pid}] unexpected error: {e}")
    print(f"\nDone in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
