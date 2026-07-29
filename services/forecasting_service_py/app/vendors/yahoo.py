import logging
from datetime import datetime
from typing import List, Dict

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class YahooFinanceVendor:
    name = "yahoo"

    def fetch_price_history(self, ticker: str, period: str = "2y") -> List[Dict]:
        try:
            logger.info(f"[Yahoo] Fetching price history for {ticker}...")
            stock = yf.Ticker(ticker)
            hist = stock.history(period=period)
            if hist is None or hist.empty:
                return []

            hist = hist.reset_index()
            data = hist[["Date", "Close"]].copy()
            data.columns = ["date", "price"]
            data["date"] = data["date"].dt.strftime("%Y-%m-%d")
            return data.to_dict(orient="records")
        except Exception as e:
            logger.error(f"[Yahoo] Error fetching price data for {ticker}: {e}")
            return []

    def fetch_fundamentals(self, ticker: str) -> Dict:
        try:
            logger.info(f"[Yahoo] Fetching fundamentals for {ticker}...")
            stock = yf.Ticker(ticker)
            info = stock.info

            quote_type = info.get("quoteType", "EQUITY").upper()

            base_data = {
                "type": quote_type,
                "profile": {
                    "name": info.get("longName", ticker),
                    "sector": info.get("sector", "Unknown"),
                    "industry": info.get("industry", "Unknown"),
                    "description": (info.get("longBusinessSummary", "") or "")[:300] + "...",
                    "currency": info.get("currency", "USD"),
                    "exchange": info.get("exchange", info.get("fullExchangeName"))
                }
            }

            if quote_type in ["ETF", "MUTUALFUND"]:
                base_data["fund_metrics"] = {
                    "expense_ratio": info.get("annualReportExpenseRatio", 0.0),
                    "yield": info.get("yield", 0.0),
                    "net_assets": info.get("totalAssets", 0),
                    "nav_price": info.get("navPrice", 0.0),
                    "category": info.get("fundFamily", "Unknown"),
                    "holdings_top": self._fetch_top_holdings(stock, ticker)
                }
                base_data["technicals"] = {
                    "beta": info.get("beta3Year", 1.0),
                    "52_week_high": info.get("fiftyTwoWeekHigh", 0.0),
                    "52_week_low": info.get("fiftyTwoWeekLow", 0.0)
                }

            elif quote_type == "FUTURE" or "Treasury" in base_data["profile"]["name"]:
                base_data["bond_metrics"] = {
                    "yield": info.get("yield", 0.0),
                    "maturity_date": info.get("expireDate", "N/A"),
                    "coupon": info.get("regularMarketPrice", 0.0)
                }

            else:
                base_data["valuation"] = {
                    "market_cap": info.get("marketCap", 0),
                    "pe_ratio": info.get("trailingPE", 0.0),
                    "forward_pe": info.get("forwardPE", 0.0),
                    "peg_ratio": info.get("pegRatio", 0.0),
                    "price_to_sales": info.get("priceToSalesTrailing12Months", 0.0),
                    "ev_to_ebitda": info.get("enterpriseToEbitda", 0.0),
                    "book_value": info.get("bookValue", 0.0)
                }
                base_data["technicals"] = {
                    "beta": info.get("beta", 1.0),
                    "52_week_high": info.get("fiftyTwoWeekHigh", 0.0),
                    "52_week_low": info.get("fiftyTwoWeekLow", 0.0)
                }
                base_data["analysts"] = {
                    "target_mean": info.get("targetMeanPrice", 0.0),
                    "recommendation": info.get("recommendationKey", "none").replace("_", " ").title(),
                    "num_analysts": info.get("numberOfAnalystOpinions", 0)
                }
                base_data["profitability"] = {
                    "profit_margin": info.get("profitMargins", 0.0),
                    "roe": info.get("returnOnEquity", 0.0),
                    "roa": info.get("returnOnAssets", 0.0)
                }

            return base_data
        except Exception as e:
            logger.error(f"[Yahoo] Error fetching fundamentals for {ticker}: {e}")
            return {"type": "UNKNOWN", "profile": {"name": ticker}}

    def fetch_news(self, ticker: str, limit: int = 5) -> List[Dict]:
        try:
            stock = yf.Ticker(ticker)
            raw_news = stock.news
            cleaned = []
            for n in raw_news[:limit]:
                content = n.get("content", n)
                title = content.get("title", n.get("title", "No Title"))
                # Publisher: new nested format or legacy flat format
                provider = content.get("provider", {})
                publisher = provider.get("displayName") if isinstance(provider, dict) else n.get("publisher", "Unknown")
                # Link: new nested format or legacy flat format
                canon = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
                link = canon.get("url") if isinstance(canon, dict) else n.get("link", "#")
                # Timestamp: ISO string or legacy unix epoch
                pub_date = content.get("pubDate", "")
                if pub_date:
                    date_str = pub_date[:16].replace("T", " ")
                else:
                    ts = n.get("providerPublishTime", 0)
                    # utcfromtimestamp, not fromtimestamp: every naive timestamp this
                    # API emits is UTC, and the frontend parses them as such. Using
                    # server-local time here would shift these items by the host offset.
                    date_str = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
                content_type = content.get("contentType", n.get("type", "STORY"))
                cleaned.append({
                    "title": title,
                    "publisher": publisher or "Unknown",
                    "link": link or "#",
                    "timestamp": date_str,
                    "type": content_type,
                })
            return cleaned
        except Exception as e:
            logger.error(f"[Yahoo] Error fetching news for {ticker}: {e}")
            return []

    def fetch_snapshot_quote(self, ticker: str) -> Dict:
        """Fetch latest quote for morning snapshot."""
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            last_price = info.get("regularMarketPrice", 0) or info.get("currentPrice", 0)
            prev_close = info.get("regularMarketPreviousClose", 0)
            change_pct = 0.0
            if prev_close and last_price:
                change_pct = ((last_price - prev_close) / prev_close) * 100
            return {
                "last_price": float(last_price or 0),
                "change_pct": float(change_pct),
                "as_of": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"[Yahoo] Error fetching snapshot for {ticker}: {e}")
            return {}

    def _fetch_top_holdings(self, stock_obj, ticker: str) -> List[Dict]:
        holdings: List[Dict] = []
        try:
            if hasattr(stock_obj, "funds_data") and stock_obj.funds_data:
                top = stock_obj.funds_data.top_holdings
                if top is not None:
                    if isinstance(top, pd.DataFrame):
                        top = top.reset_index().to_dict(orient="records")
                    for item in top:
                        holdings.append({
                            "name": item.get("Name", "Unknown"),
                            "symbol": item.get("Symbol", ""),
                            "percent": float(item.get("Holding Percent", 0.0)) * 100
                        })
                    return holdings[:10]
        except Exception:
            pass

        if not holdings:
            if ticker in ["SPY", "VOO", "IVV"]:
                return [
                    {"name": "Microsoft Corp", "symbol": "MSFT", "percent": 7.1},
                    {"name": "Apple Inc", "symbol": "AAPL", "percent": 6.5},
                    {"name": "NVIDIA Corp", "symbol": "NVDA", "percent": 6.1},
                    {"name": "Amazon.com Inc", "symbol": "AMZN", "percent": 3.4},
                    {"name": "Meta Platforms", "symbol": "META", "percent": 2.2}
                ]
            if ticker == "QQQ":
                return [
                    {"name": "Apple Inc", "symbol": "AAPL", "percent": 8.5},
                    {"name": "Microsoft Corp", "symbol": "MSFT", "percent": 8.2},
                    {"name": "NVIDIA Corp", "symbol": "NVDA", "percent": 7.8},
                    {"name": "Broadcom Inc", "symbol": "AVGO", "percent": 4.5},
                    {"name": "Meta Platforms", "symbol": "META", "percent": 4.2}
                ]
            if ticker in ["IBIT", "FBTC"]:
                return [
                    {"name": "Bitcoin", "symbol": "BTC", "percent": 99.9},
                    {"name": "Cash", "symbol": "USD", "percent": 0.1}
                ]

        return []
