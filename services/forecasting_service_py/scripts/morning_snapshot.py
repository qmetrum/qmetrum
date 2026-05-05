#!/usr/bin/env python3
"""
morning_snapshot.py — Morning quote refresh (7:00 AM ET).

Fetches latest delayed quotes for all instruments and upserts IntraDayQuote rows.
Also refreshes news for key tickers.

Usage:
  python scripts/morning_snapshot.py
  python scripts/morning_snapshot.py --symbols AAPL,MSFT
  python scripts/morning_snapshot.py --skip-news
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from typing import List

from sqlmodel import Session, select

sys.path.insert(0, ".")

from app.db.database import engine
from app.db.models import Asset, IntraDayQuote
from app.vendors import get_vendor
from scripts.nightly_batch import get_all_symbols

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Tickers that get news refreshed in the morning
NEWS_REFRESH_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "JPM", "SPY", "QQQ", "BTC-USD", "ETH-USD",
]


def refresh_quotes(session: Session, symbols: List[str]) -> int:
    """Fetch latest quotes and upsert IntraDayQuote. Returns count updated."""
    vendor = get_vendor()
    updated = 0
    now = datetime.utcnow()

    for i, symbol in enumerate(symbols, 1):
        try:
            # Use snapshot if vendor supports it, otherwise fetch last price from history
            quote_data = {}
            if hasattr(vendor, "fetch_snapshot_quote"):
                quote_data = vendor.fetch_snapshot_quote(symbol)

            if not quote_data:
                # Fallback: use most recent price from history
                rows = vendor.fetch_price_history(symbol, period="5d")
                if rows:
                    last = rows[-1]
                    quote_data = {
                        "last_price": float(last.get("close", last.get("price", 0))),
                        "change_pct": 0.0,
                        "as_of": now.isoformat(),
                    }

            if not quote_data or quote_data.get("last_price", 0) == 0:
                continue

            # Ensure asset exists
            canon = symbol.upper()
            asset = session.get(Asset, canon)
            if not asset:
                asset = Asset(
                    symbol=canon,
                    name=canon,
                    vendor=vendor.name,
                    created_at=now,
                    updated_at=now,
                )
                session.add(asset)
                session.flush()

            existing = session.get(IntraDayQuote, canon)
            if existing:
                existing.last_price = quote_data["last_price"]
                existing.change_pct = quote_data.get("change_pct", 0.0)
                existing.as_of = now
                existing.source = vendor.name
                existing.updated_at = now
            else:
                session.add(IntraDayQuote(
                    symbol=canon,
                    last_price=quote_data["last_price"],
                    change_pct=quote_data.get("change_pct", 0.0),
                    as_of=now,
                    source=vendor.name,
                    updated_at=now,
                ))

            updated += 1

            if i % 25 == 0:
                session.commit()
                logger.info(f"  [{i}/{len(symbols)}] committed batch")

        except Exception as e:
            logger.error(f"  Error refreshing quote for {symbol}: {e}")

    session.commit()
    return updated


def refresh_news(session: Session, tickers: List[str]) -> None:
    """Refresh news for key tickers."""
    from app.services.market_store import get_fundamentals_cached

    vendor = get_vendor()
    for ticker in tickers:
        try:
            news = vendor.fetch_news(ticker, limit=10)
            if news:
                logger.info(f"  News refreshed for {ticker}: {len(news)} items")
        except Exception as e:
            logger.error(f"  News refresh failed for {ticker}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Morning quote snapshot")
    parser.add_argument("--symbols", default="", help="CSV of specific symbols")
    parser.add_argument("--skip-news", action="store_true")
    args = parser.parse_args()

    started = time.time()

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = get_all_symbols()

    logger.info(f"Morning snapshot: {len(symbols)} symbols")

    with Session(engine) as session:
        updated = refresh_quotes(session, symbols)
        logger.info(f"Quotes refreshed: {updated}/{len(symbols)}")

        if not args.skip_news:
            news_tickers = [t for t in NEWS_REFRESH_TICKERS if t in set(symbols)]
            refresh_news(session, news_tickers)

    elapsed = time.time() - started
    logger.info(f"Morning snapshot complete in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
