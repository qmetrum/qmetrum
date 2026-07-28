"""Drift-baseline addendum to the forecast eval.

The engine's directional metric scores whether the forecast PATH's daily
direction agrees with the actual path over each fold. A smooth model on a
trending asset is monotonic, so it "agrees" on most days of a trending window,
inflating the score. The FAIR comparator is therefore NOT always-up, but a
DRIFT line pointed in the trailing-trend direction, scored on the identical
metric and folds. If the engine only marginally beats drift, the apparent edge
is mostly trend-following, not day-ahead skill.

Reuses the engine numbers already in forecast_eval.json (no re-run); only the
cheap price-based drift baseline is computed here.
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///./eval_local.db")


def _wf_splits(n_obs, max_splits=3, test_window=15, min_train=120):
    splits, end = [], int(n_obs)
    while len(splits) < max_splits:
        train_end = end - test_window
        if train_end < min_train:
            break
        splits.append((train_end, end))
        end = train_end
    splits.reverse()
    return splits


def drift_matches(prices, trend_lookback=21, test_window=15):
    """Per-step matches for a drift baseline: predict every step in the
    direction of the trailing `trend_lookback` move at each fold's train end.
    Also returns a strict NEXT-DAY test: did the trailing trend sign call the
    first out-of-sample day's direction?"""
    prices = np.asarray(prices, dtype=float)
    matches, nextday = [], []
    for (a, b) in _wf_splits(len(prices)):
        if a - trend_lookback < 0:
            continue
        trend = np.sign(prices[a - 1] - prices[a - 1 - trend_lookback]) or 1.0
        seg = prices[a:b]
        d = np.sign(np.diff(seg))
        if len(d) < 1:
            continue
        matches.extend((d == trend).astype(int).tolist())
        nextday.append(int(d[0] == trend))
    return matches, nextday


def _wilson(k, n, z=1.96):
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / den
    return p, max(0.0, c - h), min(1.0, c + h)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/forecast_eval.json"
    d = json.load(open(path))
    from app.services.market_store import get_price_series_cached
    import pandas as pd

    drift_k = drift_n = nd_k = nd_n = 0
    per = []
    for r in d["tickers"]:
        if "engine" not in r:
            continue
        t = r["ticker"]
        raw = get_price_series_cached(t, period="2y")
        if not raw:
            continue
        df = pd.DataFrame(raw); df["date"] = pd.to_datetime(df["date"]); df = df.sort_values("date")
        m, nd = drift_matches(df["price"].astype(float).tolist())
        dk, dn = int(sum(m)), len(m)
        drift_k += dk; drift_n += dn
        nd_k += int(sum(nd)); nd_n += len(nd)
        per.append((t, r["engine"]["directional_accuracy"], (dk / dn if dn else float("nan"))))

    eng = d["summary"]["engine_directional"]
    drift = _wilson(drift_k, drift_n)
    nd = _wilson(nd_k, nd_n)
    print("===== DRIFT-BASELINE ADDENDUM =====")
    print(f"engine directional : {eng['acc']*100:.1f}%  (from eval)")
    print(f"DRIFT baseline     : {drift[0]*100:.1f}%  CI[{drift[1]*100:.1f},{drift[2]*100:.1f}]  n={drift_n}")
    edge = (eng['acc'] - drift[0]) * 100 if eng['acc'] else float('nan')
    print(f"ENGINE edge over DRIFT (the honest number): {edge:+.1f} pp")
    print(f"strict next-day: trailing-trend called the first OOS day {nd[0]*100:.1f}% "
          f"CI[{nd[1]*100:.1f},{nd[2]*100:.1f}] n={nd_n}  (50% = no skill)")
    print("\nper-ticker engine vs drift:")
    for t, e, dr in per:
        print(f"  {t:5} engine {e*100:5.1f}%  drift {dr*100:5.1f}%  edge {(e-dr)*100:+5.1f}pp")


if __name__ == "__main__":
    main()
