"""Historical replay compute: rolling correlation + 60/40 drawdown over long
history, with realized per-crisis-window stats. Pure, no DB/network."""
from __future__ import annotations

import pandas as pd

from app.logic import correlation_monitor as cm


def _rows(returns, start_price=100.0, start="2006-01-02"):
    dates = pd.bdate_range(start, periods=len(returns) + 1)
    px = [start_price]
    for r in returns:
        px.append(px[-1] * (1 + r))
    return [{"date": d.strftime("%Y-%m-%d"), "price": float(p)} for d, p in zip(dates, px)]


def _pattern(n, scale=1.0):
    return [0.008 * ((-1) ** i) * (1 + (i % 7) * 0.1) * scale for i in range(n)]


def test_replay_structure_and_episodes():
    # ~20 years of business days so the 2008/2020/2022 windows fall inside.
    n = 20 * 252
    a = _rows(_pattern(n))
    b = _rows([x * 0.6 for x in _pattern(n)])  # correlated bond leg
    out = cm.compute_historical_replay(a, b, window=60, sample_every=5)
    assert out is not None
    assert out["pair"] == "SPY_AGG"
    assert out["window"] == 60
    assert len(out["points"]) > 100
    for p in out["points"]:
        assert -1.0001 <= p["corr"] <= 1.0001
        assert "dd" in p and p["dd"] <= 0.0001   # drawdown is <= 0
    # all three named crisis windows resolved with realized stats
    names = [e["name"] for e in out["episodes"]]
    assert any("2008" in nm for nm in names)
    assert any("2020" in nm for nm in names)
    assert any("2022" in nm for nm in names)
    for e in out["episodes"]:
        assert -1.0001 <= (e["corr"] or 0) <= 1.0001
        assert e["blend_drawdown_pct"] <= 0.0001
        assert e["n_obs"] >= 20


def test_replay_insufficient_history_returns_none():
    a = _rows(_pattern(100))
    b = _rows(_pattern(100))
    assert cm.compute_historical_replay(a, b, window=60) is None
