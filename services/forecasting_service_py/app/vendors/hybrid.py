"""Hybrid vendor that picks the right backend per (ticker, capability).

Default routing:
- Fundamentals → always Yahoo (Alpaca doesn't provide fundamentals).
- Foreign listings (`.L`, `.T`, `.HK`, …) → always Yahoo (not on Alpaca).
- Everything else → try Alpaca for prices/news/snapshot, fall back to Yahoo
  if Alpaca returns empty or errors.

Enable via env: `DATA_VENDOR=hybrid` (plus `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.vendors.yahoo import YahooFinanceVendor


logger = logging.getLogger(__name__)


# Ticker suffixes for foreign listings that Alpaca does not cover.
_FOREIGN_SUFFIXES = (
    ".L",   # London
    ".T",   # Tokyo
    ".HK",  # Hong Kong
    ".PA",  # Paris (Euronext)
    ".DE",  # XETRA (Frankfurt)
    ".AS",  # Amsterdam
    ".MI",  # Milan
    ".SW",  # Switzerland
    ".CO",  # Copenhagen
    ".OL",  # Oslo
    ".ST",  # Stockholm
    ".VI",  # Vienna
    ".LS",  # Lisbon
    ".BR",  # Brussels
    ".HE",  # Helsinki
    ".AT",  # Athens
    ".IS",  # Istanbul
    ".TA",  # Tel Aviv
    ".SA",  # São Paulo
    ".JK",  # Jakarta
    ".KS",  # Korea
    ".KQ",  # Kosdaq
    ".SS",  # Shanghai
    ".SZ",  # Shenzhen
    ".AX",  # Sydney
    ".NZ",  # New Zealand
    ".TO",  # Toronto
    ".V",   # TSX Venture
    ".MX",  # Mexico
)


def _alpaca_supported(ticker: str) -> bool:
    t = (ticker or "").upper()
    if not t:
        return False
    return not any(t.endswith(suffix) for suffix in _FOREIGN_SUFFIXES)


class HybridVendor:
    name = "hybrid"

    def __init__(self) -> None:
        self.yahoo = YahooFinanceVendor()
        self._alpaca = None
        self._alpaca_unavailable = False

    def _try_alpaca(self):
        if self._alpaca is not None:
            return self._alpaca
        if self._alpaca_unavailable:
            return None
        try:
            from app.vendors.alpaca import AlpacaVendor
            self._alpaca = AlpacaVendor()
            return self._alpaca
        except Exception as exc:
            logger.warning("[hybrid] Alpaca unavailable, falling back to Yahoo: %s", exc)
            self._alpaca_unavailable = True
            return None

    def fetch_price_history(self, ticker: str, period: str = "2y") -> List[Dict]:
        if _alpaca_supported(ticker):
            alpaca = self._try_alpaca()
            if alpaca is not None:
                bars = alpaca.fetch_price_history(ticker, period=period)
                if bars:
                    return bars
        return self.yahoo.fetch_price_history(ticker, period=period)

    def fetch_fundamentals(self, ticker: str) -> Dict:
        # Alpaca does not provide fundamentals — always Yahoo.
        return self.yahoo.fetch_fundamentals(ticker)

    def fetch_news(self, ticker: str, limit: int = 5) -> List[Dict]:
        if _alpaca_supported(ticker):
            alpaca = self._try_alpaca()
            if alpaca is not None:
                items = alpaca.fetch_news(ticker, limit=limit)
                if items:
                    return items
        return self.yahoo.fetch_news(ticker, limit=limit)

    def fetch_snapshot_quote(self, ticker: str) -> Dict:
        if _alpaca_supported(ticker):
            alpaca = self._try_alpaca()
            if alpaca is not None:
                snap = alpaca.fetch_snapshot_quote(ticker)
                if snap:
                    return snap
        return self.yahoo.fetch_snapshot_quote(ticker)
