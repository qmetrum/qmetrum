"""Portfolio Regime Watch compute: sleeve classification + equity-vs-bond realized
correlation on a real book, honest N/A when the book can't support it. Pure, no DB."""
from __future__ import annotations

import pandas as pd

from app.logic import correlation_monitor as cm


def _rows(returns, start=100.0):
    dates = pd.bdate_range("2020-01-01", periods=len(returns) + 1)
    px = [start]
    for r in returns:
        px.append(px[-1] * (1 + r))
    return [{"date": d.strftime("%Y-%m-%d"), "price": float(p)} for d, p in zip(dates, px)]


def _ret(n):
    return [0.01 * ((-1) ** i) * (1 + (i % 5) * 0.1) for i in range(n)]


def test_classify_sleeve():
    assert cm.classify_sleeve("SPY") == "equity"
    assert cm.classify_sleeve("AGG") == "bond"
    assert cm.classify_sleeve("GLD") == "commodity"
    assert cm.classify_sleeve("BTC-USD") == "crypto"
    assert cm.classify_sleeve("AAPL", asset_class="US_EQUITY") == "equity"
    assert cm.classify_sleeve("TLT", asset_class="US_EQUITY") == "bond"  # curated ticker wins
    assert cm.classify_sleeve("ZZZZ") == "other"


def test_portfolio_regime_ok():
    r = _ret(300)
    data = {"SPY": _rows(r), "AGG": _rows([x * 0.5 for x in r])}
    holdings = [
        {"ticker": "SPY", "weight": 0.6, "sleeve": "equity"},
        {"ticker": "AGG", "weight": 0.4, "sleeve": "bond"},
    ]
    out = cm.compute_portfolio_regime(holdings, data, short_window=60, baseline_window=252)
    assert out["status"] == "ok"
    assert out["pair"] == "equity_vs_bond"
    assert -1.0 <= out["short_corr"] <= 1.0
    assert out["baseline_corr"] is not None
    assert out["delta"] is not None
    assert out["sleeve_weights"]["equity"] == 0.6
    assert out["n_obs"] == 60


def test_portfolio_regime_na_single_sleeve():
    data = {"SPY": _rows(_ret(120))}
    holdings = [{"ticker": "SPY", "weight": 1.0, "sleeve": "equity"}]
    out = cm.compute_portfolio_regime(holdings, data)
    assert out["status"] == "na"
    assert "sleeve" in out["reason"].lower()


def test_portfolio_regime_na_insufficient_history():
    r = _ret(20)
    data = {"SPY": _rows(r), "AGG": _rows([x * 0.5 for x in r])}
    holdings = [
        {"ticker": "SPY", "weight": 0.6, "sleeve": "equity"},
        {"ticker": "AGG", "weight": 0.4, "sleeve": "bond"},
    ]
    out = cm.compute_portfolio_regime(holdings, data, short_window=60)
    assert out["status"] == "na"
