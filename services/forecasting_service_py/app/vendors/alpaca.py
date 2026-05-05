"""Alpaca market data vendor (REST/batch only — no WebSocket streaming).

Implements `MarketDataVendor` for the data Alpaca actually provides:
- price_history (stocks + crypto, daily bars)
- snapshot_quote (latest trade + previous daily close → change pct)
- news

`fetch_fundamentals` returns an empty dict on purpose — Alpaca is a
brokerage / market-data API and does not provide fundamentals. Callers
should route fundamentals to a different vendor (e.g. Yahoo or Polygon).

Coverage: US-listed equities/ETFs and crypto pairs (BTC/USD style).
Non-US listings (`.L`, `.T`, `.HK`, …) are NOT on Alpaca — the hybrid
router skips this vendor for those tickers.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


_PERIOD_DAYS = {
    "1mo": 30, "3mo": 90, "6mo": 180,
    "1y": 365, "2y": 730, "5y": 1825, "10y": 3650,
    "max": 3650 * 5,
}


def _period_to_start(period: str) -> datetime:
    p = (period or "").lower()
    if p == "ytd":
        return datetime(datetime.utcnow().year, 1, 1)
    days = _PERIOD_DAYS.get(p, 730)
    return datetime.utcnow() - timedelta(days=days)


def _is_crypto(ticker: str) -> bool:
    t = (ticker or "").upper()
    return t.endswith("-USD") or t.endswith("USDT") or t.endswith("USDC")


def _to_crypto_symbol(ticker: str) -> str:
    """Normalize Yahoo-style 'BTC-USD' to Alpaca's 'BTC/USD'."""
    t = ticker.upper()
    if t.endswith("-USD"):
        return t[:-4] + "/USD"
    if t.endswith("USDT"):
        return t[:-4] + "/USDT"
    if t.endswith("USDC"):
        return t[:-4] + "/USDC"
    return t


class AlpacaVendor:
    name = "alpaca"

    def __init__(self) -> None:
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        if not api_key or not secret_key:
            raise RuntimeError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set to use the Alpaca vendor"
            )
        self.api_key = api_key
        self.secret_key = secret_key
        self._stock_client = None
        self._crypto_client = None
        self._news_client = None

    # --- lazy clients (avoid importing alpaca-py unless actually used) ---
    def _stock(self):
        if self._stock_client is None:
            from alpaca.data.historical import StockHistoricalDataClient
            self._stock_client = StockHistoricalDataClient(self.api_key, self.secret_key)
        return self._stock_client

    def _crypto(self):
        if self._crypto_client is None:
            from alpaca.data.historical import CryptoHistoricalDataClient
            self._crypto_client = CryptoHistoricalDataClient(self.api_key, self.secret_key)
        return self._crypto_client

    def _news(self):
        if self._news_client is None:
            from alpaca.data.historical.news import NewsClient
            self._news_client = NewsClient(self.api_key, self.secret_key)
        return self._news_client

    # --- vendor interface ---
    def fetch_price_history(self, ticker: str, period: str = "2y") -> List[Dict]:
        try:
            from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
            from alpaca.data.timeframe import TimeFrame

            start = _period_to_start(period)

            if _is_crypto(ticker):
                symbol = _to_crypto_symbol(ticker)
                req = CryptoBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=TimeFrame.Day,
                    start=start,
                )
                bars = self._crypto().get_crypto_bars(req)
            else:
                req = StockBarsRequest(
                    symbol_or_symbols=ticker.upper(),
                    timeframe=TimeFrame.Day,
                    start=start,
                )
                bars = self._stock().get_stock_bars(req)

            df = getattr(bars, "df", None)
            if df is None or df.empty:
                return []
            df = df.reset_index()
            out: List[Dict] = []
            for _, row in df.iterrows():
                ts = row.get("timestamp")
                if ts is None:
                    continue
                out.append({
                    "date": ts.strftime("%Y-%m-%d"),
                    "price": float(row.get("close", 0.0) or 0.0),
                })
            return out
        except Exception as exc:
            logger.warning("[Alpaca] price history failed for %s: %s", ticker, exc)
            return []

    def fetch_fundamentals(self, ticker: str) -> Dict:
        # Alpaca does not expose fundamentals — return empty so the caller can
        # fall through to a different vendor.
        return {}

    def fetch_news(self, ticker: str, limit: int = 5) -> List[Dict]:
        try:
            from alpaca.data.requests import NewsRequest

            req = NewsRequest(
                symbols=[ticker.upper()],
                limit=int(limit),
                start=datetime.utcnow() - timedelta(days=30),
            )
            resp = self._news().get_news(req)
            # alpaca-py returns a NewsSet with .news attribute (list of NewsArticle)
            items = getattr(resp, "news", None) or getattr(resp, "data", []) or []
            cleaned: List[Dict] = []
            for n in items[:limit]:
                created = getattr(n, "created_at", None) or getattr(n, "updated_at", None)
                ts_str = ""
                if created is not None:
                    try:
                        ts_str = created.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        ts_str = str(created)[:16]
                cleaned.append({
                    "title": getattr(n, "headline", "No Title") or "No Title",
                    "publisher": getattr(n, "source", "Alpaca") or "Alpaca",
                    "link": getattr(n, "url", "#") or "#",
                    "timestamp": ts_str,
                    "type": "STORY",
                })
            return cleaned
        except Exception as exc:
            logger.warning("[Alpaca] news failed for %s: %s", ticker, exc)
            return []

    def fetch_snapshot_quote(self, ticker: str) -> Dict:
        try:
            from alpaca.data.requests import StockSnapshotRequest, CryptoSnapshotRequest

            if _is_crypto(ticker):
                symbol = _to_crypto_symbol(ticker)
                req = CryptoSnapshotRequest(symbol_or_symbols=symbol)
                snap = self._crypto().get_crypto_snapshot(req)
                key = symbol
            else:
                req = StockSnapshotRequest(symbol_or_symbols=ticker.upper())
                snap = self._stock().get_stock_snapshot(req)
                key = ticker.upper()

            entry = snap.get(key) if isinstance(snap, dict) else None
            if entry is None:
                return {}

            latest_trade = getattr(entry, "latest_trade", None)
            prev_bar = getattr(entry, "previous_daily_bar", None)
            last_price = float(getattr(latest_trade, "price", 0) or 0)
            prev_close = float(getattr(prev_bar, "close", 0) or 0)
            change_pct = 0.0
            if prev_close and last_price:
                change_pct = ((last_price - prev_close) / prev_close) * 100

            return {
                "last_price": last_price,
                "change_pct": change_pct,
                "as_of": datetime.utcnow().isoformat(),
            }
        except Exception as exc:
            logger.warning("[Alpaca] snapshot failed for %s: %s", ticker, exc)
            return {}
