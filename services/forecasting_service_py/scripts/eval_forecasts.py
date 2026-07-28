"""Forecast evaluation harness.

Answers "do the forecasts have real predictive power?" with numbers, not
opinion. For a basket of tickers it:

  1. Runs the real HybridForecaster and harvests its OWN walk-forward metrics
     (directional accuracy, MAPE, excess-vs-buy-hold, per model family).
  2. Computes NAIVE baselines on the EXACT same walk-forward folds:
        - always-up:    predict every step is an up move
        - persistence:  predict this step's direction = the previous step's
     so "61% vs a 54% always-up baseline" is a fair, matched comparison.
  3. Pools per-step outcomes across the basket and reports binomial 95% CIs,
     plus the engine-vs-best-baseline edge.

Honesty notes baked into the output:
  - Pooled steps are NOT independent (market-wide moves correlate across
    tickers and adjacent days), so the naive-pooled CI UNDERSTATES uncertainty.
    Treated as a lower bound on the error bars, flagged in the summary.
  - Per-model win counts show whether the exotic families (QRC) actually earn
    their place over plain Prophet/ARIMA.

Run (background, ~1-3 min per ticker due to LSTM training):
    python scripts/eval_forecasts.py --tickers AAPL,MSFT,... --horizon 15 --out /tmp/eval.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

# Make the service root importable when run as `python scripts/eval_forecasts.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///./eval_local.db")


DEFAULT_TICKERS =["AAPL", "MSFT", "NVDA", "JPM", "XOM", "JNJ", "PG", "WMT",
                   "SPY", "QQQ", "TLT", "GLD"]


def _wf_splits(n_obs, max_splits=3, test_window=15, min_train=120):
    """Replica of HybridForecaster._build_walk_forward_splits so baselines use
    the identical fold boundaries the engine scored itself on."""
    splits, end = [], int(n_obs)
    test_window = int(max(3, test_window))
    while len(splits) < int(max_splits):
        train_end = end - test_window
        if train_end < int(min_train):
            break
        splits.append((train_end, end))
        end = train_end
    splits.reverse()
    return splits


def _baseline_dir_matches(prices, test_window=15, trend_lookback=21):
    """Per-step direction matches for the naive baselines, over the same folds.
    Returns (always_up, persistence, drift) as lists of 0/1.
      always-up   : predict every step is up
      persistence : predict this step's direction = the previous step's
      drift       : predict every step in the trailing-trend direction (the
                    FAIR comparator for a smooth forecast line)."""
    prices = np.asarray(prices, dtype=float)
    up, pers, drift = [], [], []
    for (a, b) in _wf_splits(len(prices), test_window=test_window):
        seg = prices[a:b]
        d = np.sign(np.diff(seg))          # actual per-step direction in-fold
        if len(d) < 2:
            continue
        up.extend((d > 0).astype(int).tolist())            # always predict up
        pers.extend((d[1:] == d[:-1]).astype(int).tolist())  # predict = previous
        if a - trend_lookback >= 0:
            trend = np.sign(prices[a - 1] - prices[a - 1 - trend_lookback]) or 1.0
            drift.extend((d == trend).astype(int).tolist())
    return up, pers, drift


def _wilson(k, n, z=1.96):
    """Wilson 95% interval for a binomial proportion (better than normal for
    the tails); returns (p_hat, lo, hi)."""
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def evaluate_ticker(ticker, horizon, period="5y"):
    """Run the engine once and harvest matched engine + baseline outcomes."""
    from app.logic.forecasting_logic import HybridForecaster
    from app.services.market_store import get_price_series_cached
    import pandas as pd

    raw = get_price_series_cached(ticker, period=period)
    if not raw or len(raw) < 200:
        return {"ticker": ticker, "error": f"insufficient data ({len(raw) if raw else 0} pts)"}
    df = pd.DataFrame(raw)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    prices = df["price"].astype(float).tolist()

    fc = HybridForecaster()
    fc.train(df)
    res = fc.predict(forecast_horizon_days=horizon)

    fq = res.get("forecast_quality") or {}
    qpm = (res.get("model_validation") or {}).get("quality_per_model") or {}
    winner = res.get("model_used", "unknown")

    up, pers, drift = _baseline_dir_matches(prices)

    # Engine per-step dir count reconstructed from its reported accuracy and n.
    da = fq.get("directional_accuracy")
    n = fq.get("n_validation_steps")
    eng_k = int(round(da * n)) if (da is not None and n) else None

    return {
        "ticker": ticker,
        "winner": winner,
        "engine": {
            "directional_accuracy": da,
            "n_validation_steps": n,
            "dir_matches": eng_k,
            "mape": fq.get("mape"),
            "long_short_sharpe": fq.get("long_short_sharpe"),
        },
        "per_model": {
            m: {"da": q.get("directional_accuracy"), "mape": q.get("mape"),
                "n": q.get("n_validation_steps")}
            for m, q in qpm.items() if isinstance(q, dict)
        },
        "baseline_always_up": {"matches": int(sum(up)), "n": len(up)},
        "baseline_persistence": {"matches": int(sum(pers)), "n": len(pers)},
        "baseline_drift": {"matches": int(sum(drift)), "n": len(drift)},
    }


def summarize(rows):
    ok = [r for r in rows if "error" not in r]
    # Pool engine directional matches.
    eng_k = sum(r["engine"]["dir_matches"] for r in ok if r["engine"]["dir_matches"] is not None)
    eng_n = sum(r["engine"]["n_validation_steps"] for r in ok if r["engine"]["n_validation_steps"])
    up_k = sum(r["baseline_always_up"]["matches"] for r in ok)
    up_n = sum(r["baseline_always_up"]["n"] for r in ok)
    ps_k = sum(r["baseline_persistence"]["matches"] for r in ok)
    ps_n = sum(r["baseline_persistence"]["n"] for r in ok)
    dr_k = sum(r.get("baseline_drift", {}).get("matches", 0) for r in ok)
    dr_n = sum(r.get("baseline_drift", {}).get("n", 0) for r in ok)

    eng = _wilson(eng_k, eng_n)
    up = _wilson(up_k, up_n)
    ps = _wilson(ps_k, ps_n)
    dr = _wilson(dr_k, dr_n)

    # Per-model directional accuracy pooled, and winner counts.
    fam_k, fam_n, wins = {}, {}, {}
    for r in ok:
        wins[r["winner"]] = wins.get(r["winner"], 0) + 1
        for m, q in r["per_model"].items():
            if q["da"] is not None and q["n"]:
                fam_k[m] = fam_k.get(m, 0) + int(round(q["da"] * q["n"]))
                fam_n[m] = fam_n.get(m, 0) + q["n"]
    families = {m: {"da": fam_k[m] / fam_n[m], "n": fam_n[m]} for m in fam_n if fam_n[m]}

    mapes = [r["engine"]["mape"] for r in ok if r["engine"]["mape"] is not None]
    sharpes = [r["engine"]["long_short_sharpe"] for r in ok
               if r["engine"]["long_short_sharpe"] is not None]

    return {
        "n_tickers_ok": len(ok),
        "n_tickers_failed": len(rows) - len(ok),
        "engine_directional": {"acc": eng[0], "ci": [eng[1], eng[2]], "n": eng_n},
        "baseline_always_up": {"acc": up[0], "ci": [up[1], up[2]], "n": up_n},
        "baseline_persistence": {"acc": ps[0], "ci": [ps[1], ps[2]], "n": ps_n},
        "baseline_drift": {"acc": dr[0], "ci": [dr[1], dr[2]], "n": dr_n},
        "edge_over_best_baseline_pp": (
            (eng[0] - max(up[0], ps[0], dr[0] if dr_n else 0)) * 100 if eng[0] else None),
        "mape_median": float(np.median(mapes)) if mapes else None,
        "long_short_sharpe_median": float(np.median(sharpes)) if sharpes else None,
        "per_model_directional": families,
        "winner_counts": wins,
        "caveat": ("Pooled per-step outcomes are correlated across tickers/days, so "
                   "the CIs are a LOWER bound on true uncertainty. Treat a sub-2pp "
                   "edge over baseline as unproven."),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    ap.add_argument("--horizon", type=int, default=15)
    ap.add_argument("--period", default="5y")
    ap.add_argument("--out", default="/tmp/forecast_eval.json")
    args = ap.parse_args()

    # Create the local cache schema so market_store can persist fetched prices.
    import app.db.models  # noqa: F401  (register tables)
    from app.db.database import engine
    from sqlmodel import SQLModel
    SQLModel.metadata.create_all(engine)

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    jsonl = args.out + "l"  # incremental per-ticker log
    rows = []
    open(jsonl, "w").close()
    for i, t in enumerate(tickers, 1):
        t0 = time.time()
        try:
            r = evaluate_ticker(t, args.horizon, period=args.period)
        except Exception as e:
            r = {"ticker": t, "error": repr(e)[:300]}
        r["_secs"] = round(time.time() - t0, 1)
        rows.append(r)
        with open(jsonl, "a") as f:
            f.write(json.dumps(r) + "\n")
        da = r.get("engine", {}).get("directional_accuracy")
        print(f"[{i}/{len(tickers)}] {t}: "
              + (f"engine_da={da:.3f} ({r['_secs']}s)" if da is not None
                 else f"ERROR {r.get('error','')[:80]}"), flush=True)

    summary = summarize(rows)
    out = {"summary": summary, "tickers": rows, "horizon": args.horizon}
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)

    s = summary
    print("\n===== FORECAST EVALUATION SUMMARY =====")
    print(f"tickers ok: {s['n_tickers_ok']}  failed: {s['n_tickers_failed']}")
    e, u, p = s["engine_directional"], s["baseline_always_up"], s["baseline_persistence"]
    print(f"engine directional : {e['acc']*100:.1f}%  CI[{e['ci'][0]*100:.1f}, {e['ci'][1]*100:.1f}]  n={e['n']}")
    print(f"always-up baseline : {u['acc']*100:.1f}%  CI[{u['ci'][0]*100:.1f}, {u['ci'][1]*100:.1f}]  n={u['n']}")
    print(f"persistence base   : {p['acc']*100:.1f}%  CI[{p['ci'][0]*100:.1f}, {p['ci'][1]*100:.1f}]  n={p['n']}")
    dr = s.get("baseline_drift", {})
    if dr.get("n"):
        print(f"DRIFT baseline     : {dr['acc']*100:.1f}%  CI[{dr['ci'][0]*100:.1f}, {dr['ci'][1]*100:.1f}]  n={dr['n']}  (fair comparator)")
    print(f"edge over best baseline: {s['edge_over_best_baseline_pp']:+.1f} pp" if s['edge_over_best_baseline_pp'] is not None else "edge: n/a")
    print(f"median MAPE: {s['mape_median']*100:.2f}%" if s['mape_median'] is not None else "MAPE: n/a")
    print(f"median long/short info ratio: {s['long_short_sharpe_median']:.3f}" if s['long_short_sharpe_median'] is not None else "")
    print("per-model directional:", {m: f"{v['da']*100:.1f}%" for m, v in s["per_model_directional"].items()})
    print("winner counts:", s["winner_counts"])
    print("CAVEAT:", s["caveat"])
    print(f"\nfull results: {args.out}  (incremental: {jsonl})")


if __name__ == "__main__":
    sys.exit(main())
