import os
from typing import Optional

from app.vendors.base import MarketDataVendor
from app.vendors.yahoo import YahooFinanceVendor

_VENDOR: Optional[MarketDataVendor] = None


def get_vendor() -> MarketDataVendor:
    global _VENDOR
    if _VENDOR is not None:
        return _VENDOR

    name = os.getenv("DATA_VENDOR", "yahoo").lower().strip()
    if name == "yahoo":
        _VENDOR = YahooFinanceVendor()
    elif name == "polygon":
        from app.vendors.polygon import PolygonVendor
        _VENDOR = PolygonVendor()
    elif name in ("hybrid", "alpaca"):
        # `alpaca` accepted as an alias — under the hood it's the hybrid
        # router (Alpaca for US prices/news/snapshot, Yahoo for fundamentals
        # and foreign listings).
        from app.vendors.hybrid import HybridVendor
        _VENDOR = HybridVendor()
    else:
        raise ValueError(f"Unsupported DATA_VENDOR: {name}")

    return _VENDOR
