"""
Polygon.io vendor implementation for MarketDataVendor protocol.

Requires:
  - POLYGON_API_KEY env var
  - polygon-io package (pip install polygon-api-client)
"""

import os
import logging
from datetime import datetime, timedelta
from app.utils.timeutil import utcnow
from typing import Dict, List

logger = logging.getLogger(__name__)

_API_KEY = os.getenv("POLYGON_API_KEY", "")


class PolygonVendor:
    name = "polygon"

    def __init__(self):
        if not _API_KEY:
            logger.warning("[Polygon] POLYGON_API_KEY not set — calls will fail")
        from polygon import RESTClient
        self._client = RESTClient(api_key=_API_KEY)

    def fetch_price_history(self, ticker: str, period: str = "2y") -> List[Dict]:
        """Fetch daily OHLCV bars from Polygon."""
        try:
            days = _period_to_days(period)
            end_date = utcnow().date()
            start_date = end_date - timedelta(days=days)

            # Polygon uses different ticker formats:
            # Crypto: X:BTCUSD (we convert BTC-USD -> X:BTCUSD)
            # Indices: I:SPX (we convert ^GSPC -> I:SPX for known indices)
            poly_ticker = _to_polygon_ticker(ticker)

            logger.info(f"[Polygon] Fetching bars for {poly_ticker} ({start_date} to {end_date})")
            aggs = self._client.get_aggs(
                ticker=poly_ticker,
                multiplier=1,
                timespan="day",
                from_=str(start_date),
                to=str(end_date),
                limit=50000,
            )

            if not aggs:
                return []

            results = []
            for bar in aggs:
                # bar.timestamp is the start of the aggregate window in Unix ms:
                # midnight ET for US equities, midnight UTC for crypto. Bucketing
                # that into a date with fromtimestamp() would resolve it against the
                # HOST's timezone, silently shifting every bar to the previous day on
                # any host west of UTC — the whole price history off by one session,
                # which is invisible until it corrupts a forecast. utcfromtimestamp
                # keeps the date host-independent.
                date_str = datetime.utcfromtimestamp(bar.timestamp / 1000).strftime("%Y-%m-%d")
                results.append({
                    "date": date_str,
                    "price": float(bar.close),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume or 0),
                })
            return results

        except Exception as e:
            logger.error(f"[Polygon] Error fetching price history for {ticker}: {e}")
            return []

    def fetch_fundamentals(self, ticker: str) -> Dict:
        """Fetch company/ticker reference data from Polygon."""
        try:
            logger.info(f"[Polygon] Fetching fundamentals for {ticker}")
            details = self._client.get_ticker_details(ticker)

            if not details:
                return {"type": "UNKNOWN", "profile": {"name": ticker}}

            quote_type = _classify_ticker_type(ticker, details)

            return {
                "type": quote_type,
                "profile": {
                    "name": getattr(details, "name", ticker),
                    "sector": getattr(details, "sic_description", "Unknown"),
                    "industry": getattr(details, "sic_description", "Unknown"),
                    "description": (getattr(details, "description", "") or "")[:300],
                    "currency": getattr(details, "currency_name", "USD"),
                    "exchange": getattr(details, "primary_exchange", None),
                },
                "valuation": {
                    "market_cap": getattr(details, "market_cap", 0),
                },
            }
        except Exception as e:
            logger.error(f"[Polygon] Error fetching fundamentals for {ticker}: {e}")
            return {"type": "UNKNOWN", "profile": {"name": ticker}}

    def fetch_news(self, ticker: str, limit: int = 5) -> List[Dict]:
        """Fetch recent news from Polygon."""
        try:
            logger.info(f"[Polygon] Fetching news for {ticker}")
            news_items = self._client.list_ticker_news(ticker=ticker, limit=limit)

            results = []
            for item in news_items:
                results.append({
                    "title": getattr(item, "title", "No Title"),
                    "publisher": getattr(item, "publisher", {}).get("name", "Unknown") if isinstance(getattr(item, "publisher", None), dict) else "Unknown",
                    "link": getattr(item, "article_url", "#"),
                    "timestamp": getattr(item, "published_utc", ""),
                    "type": "STORY",
                })
                if len(results) >= limit:
                    break
            return results
        except Exception as e:
            logger.error(f"[Polygon] Error fetching news for {ticker}: {e}")
            return []

    def fetch_snapshot_quote(self, ticker: str) -> Dict:
        """Fetch latest quote snapshot (for morning refresh)."""
        try:
            poly_ticker = _to_polygon_ticker(ticker)
            snapshot = self._client.get_snapshot_ticker("stocks", poly_ticker)
            if snapshot and snapshot.day:
                return {
                    "last_price": float(snapshot.day.close or 0),
                    "change_pct": float(snapshot.todays_change_percent or 0),
                    "as_of": utcnow().isoformat(),
                }
        except Exception as e:
            logger.error(f"[Polygon] Error fetching snapshot for {ticker}: {e}")
        return {}


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

_PERIOD_DAYS = {
    "1d": 1, "5d": 5, "1mo": 31, "3mo": 93, "6mo": 186,
    "1y": 366, "2y": 732, "5y": 1830, "10y": 3660, "max": 36500,
}

# Known index ticker mappings (Yahoo -> Polygon)
_INDEX_MAP = {
    "^GSPC": "I:SPX",
    "^DJI": "I:DJI",
    "^IXIC": "I:COMP",
    "^VIX": "I:VIX",
    "^RUT": "I:RUT",
}


def _period_to_days(period: str) -> int:
    return _PERIOD_DAYS.get(period.lower(), 732)


def _to_polygon_ticker(ticker: str) -> str:
    """Convert Yahoo-style ticker to Polygon format."""
    # Index tickers
    if ticker in _INDEX_MAP:
        return _INDEX_MAP[ticker]

    # Crypto: BTC-USD -> X:BTCUSD
    if ticker.endswith("-USD"):
        base = ticker.replace("-USD", "")
        return f"X:{base}USD"

    # Futures: GC=F -> not directly supported, keep as-is
    # Most US equities and ETFs use the same symbol
    return ticker


def _classify_ticker_type(ticker: str, details) -> str:
    """Classify a ticker based on Polygon details."""
    ticker_type = getattr(details, "type", "")
    if ticker_type == "ETF":
        return "ETF"
    if ticker_type == "CS":
        return "EQUITY"
    if ticker.endswith("-USD"):
        return "CRYPTO"
    if ticker.startswith("^") or ticker.startswith("I:"):
        return "INDEX"
    return "EQUITY"
