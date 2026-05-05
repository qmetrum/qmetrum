import logging
from app.vendors import get_vendor

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_VENDOR = get_vendor()

def fetch_stock_data(ticker: str, period: str = "2y"):
    """
    Fetches historical stock price data from Yahoo Finance.
    Returns a list of dictionaries: [{'date': '2023-01-01', 'price': 150.0}, ...]
    """
    try:
        return _VENDOR.fetch_price_history(ticker, period=period)
    except Exception as e:
        logger.error(f"Error fetching stock data for {ticker}: {e}")
        return []

def fetch_fundamentals(ticker: str):
    """
    Fetches key fundamental data (P/E, Market Cap, etc.)
    Returns a dictionary.
    """
    try:
        return _VENDOR.fetch_fundamentals(ticker)
    except Exception as e:
        logger.error(f"Error fetching metrics for {ticker}: {e}")
        return {"type": "UNKNOWN", "profile": {"name": ticker}}

# --- NEWS FETCHER ---
def fetch_news(ticker: str, limit: int = 5):
    """
    Fetches latest news from Yahoo Finance.
    Returns: [{'title':..., 'link':..., 'publisher':..., 'time':...}]
    """
    try:
        return _VENDOR.fetch_news(ticker, limit=limit)
    except Exception as e:
        logger.error(f"Error fetching news for {ticker}: {e}")
        return []
