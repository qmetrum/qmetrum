def get_classification(info: dict, ticker: str):
    """
    Accepts either raw vendor info or the normalized fundamentals dict.
    """
    if isinstance(info, dict) and "profile" in info:
        profile = info.get("profile", {}) or {}
        asset_type = info.get("type", "EQUITY")
        return {
            "entity_id": ticker,
            "metric_type": "classification",
            "values": {
                "type": str(asset_type).upper(),
                "sector": profile.get("sector", "Unknown"),
                "industry": profile.get("industry", "Unknown"),
                "country": profile.get("country", "Unknown")
            },
            "source": info.get("vendor", "vendor")
        }

    return {
        "entity_id": ticker,
        "metric_type": "classification",
        "values": {
            "type": info.get("quoteType", "EQUITY").upper(),
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown"),
            "country": info.get("country", "Unknown")
        },
        "source": "yahoo"
    }
