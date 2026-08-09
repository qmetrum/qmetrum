from __future__ import annotations

from typing import List, Optional

from .schemas import Fact


def gather_facts(ticker: str, extra_context: Optional[str] = None) -> List[Fact]:
    """Assemble a small, sourced fact set for a ticker from free yfinance data,
    plus any freeform context the caller pastes in. Degrades honestly to
    context-only if live data is unavailable."""
    facts: List[Fact] = []
    i = 0
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        hist = t.history(period="6mo")
        if not hist.empty:
            close = hist["Close"].dropna()
            last = float(close.iloc[-1])
            facts.append(Fact(i, "yfinance/price", f"Last close {last:.2f}.")); i += 1
            for label, n in (("1-month", 21), ("3-month", 63)):
                if len(close) > n:
                    chg = (last / float(close.iloc[-n - 1]) - 1) * 100
                    facts.append(Fact(i, "yfinance/price", f"{label} price change {chg:+.1f}%.")); i += 1
            hi, lo = float(close.max()), float(close.min())
            pct = ((last - lo) / (hi - lo) * 100) if hi > lo else 0.0
            facts.append(Fact(i, "yfinance/price",
                              f"6-month range {lo:.2f}-{hi:.2f}; last sits at {pct:.0f}% of that range.")); i += 1
        info = getattr(t, "info", {}) or {}
        for key, label in (("trailingPE", "trailing P/E"), ("forwardPE", "forward P/E"),
                           ("profitMargins", "profit margin"), ("revenueGrowth", "revenue growth"),
                           ("sector", "sector"), ("beta", "beta")):
            v = info.get(key)
            if v is not None:
                facts.append(Fact(i, "yfinance/fundamentals", f"{label}: {v}.")); i += 1
    except Exception as e:  # noqa: BLE001
        facts.append(Fact(i, "system",
                          f"Live data unavailable ({type(e).__name__}); reasoning from provided context only.")); i += 1

    if extra_context:
        for line in [ln.strip() for ln in extra_context.splitlines() if ln.strip()]:
            facts.append(Fact(i, "user-context", line)); i += 1

    return facts
