"""Pure-compute tests for the cross-asset correlation monitor.

No DB, no network — asserts the realized-correlation math is correct and honest:
perfectly co-moving return series -> +1, mirrored -> -1, too-little history -> None,
and the rolling series stays within [-1, 1]."""
from __future__ import annotations

import pandas as pd

from app.logic import correlation_monitor as cm


def _returns_pattern(n: int) -> list[float]:
    # Deterministic, non-constant daily returns (variance > 0 so corr is defined).
    return [0.01 * ((-1) ** i) * (1 + (i % 5) * 0.1) for i in range(n)]


def _rows_from_returns(returns: list[float], start_price: float) -> list[dict]:
    dates = pd.bdate_range("2020-01-01", periods=len(returns) + 1)
    price = start_price
    prices = [price]
    for r in returns:
        price = price * (1 + r)
        prices.append(price)
    return [{"date": d.strftime("%Y-%m-%d"), "price": float(p)} for d, p in zip(dates, prices)]


def test_perfectly_comoving_pair_is_plus_one():
    r = _returns_pattern(120)
    a = _rows_from_returns(r, 100.0)
    b = _rows_from_returns(r, 50.0)  # same returns, different price level
    res = cm.compute_pair_window(a, b, 60)
    assert res is not None
    assert res["pearson"] > 0.99
    assert res["n_obs"] == 60


def test_mirrored_pair_is_minus_one():
    r = _returns_pattern(120)
    a = _rows_from_returns(r, 100.0)
    b = _rows_from_returns([-x for x in r], 100.0)  # exact opposite returns
    res = cm.compute_pair_window(a, b, 60)
    assert res is not None
    assert res["pearson"] < -0.99


def test_insufficient_history_returns_none():
    r = _returns_pattern(15)
    a = _rows_from_returns(r, 100.0)
    b = _rows_from_returns(r, 100.0)
    assert cm.compute_pair_window(a, b, 60) is None


def test_rolling_series_is_bounded_and_dated():
    r = _returns_pattern(200)
    a = _rows_from_returns(r, 100.0)
    b = _rows_from_returns([x * 0.9 for x in r], 100.0)
    res = cm.compute_pair_window(a, b, 30)
    assert res is not None
    assert len(res["series"]) > 0
    assert len(res["series"]) <= cm.ROLLING_HISTORY
    for pt in res["series"]:
        assert -1.0001 <= pt["corr"] <= 1.0001
        # date parses as YYYY-MM-DD
        pd.to_datetime(pt["date"])


def test_symbols_needed_is_deduped():
    syms = cm.symbols_needed()
    assert syms == list(dict.fromkeys(syms))  # order-preserving, no dupes
    assert "SPY" in syms and "AGG" in syms
