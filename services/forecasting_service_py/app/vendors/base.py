from typing import List, Dict, Protocol


class MarketDataVendor(Protocol):
    name: str

    def fetch_price_history(self, ticker: str, period: str = "2y") -> List[Dict]:
        ...

    def fetch_fundamentals(self, ticker: str) -> Dict:
        ...

    def fetch_news(self, ticker: str, limit: int = 5) -> List[Dict]:
        ...

    def fetch_snapshot_quote(self, ticker: str) -> Dict:
        ...
