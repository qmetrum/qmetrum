def get_profile(info: dict, ticker: str):
    """
    Accepts either raw vendor info or the normalized fundamentals dict.
    """
    if isinstance(info, dict) and "profile" in info:
        profile = info.get("profile", {}) or {}
        return {
            "entity_id": ticker,
            "metric_type": "profile",
            "values": {
                "name": profile.get("name", ticker),
                "description": (profile.get("description", "") or "")[:300],
                "currency": profile.get("currency", "USD")
            },
            "source": info.get("vendor", "vendor")
        }

    return {
        "entity_id": ticker,
        "metric_type": "profile",
        "values": {
            "name": info.get("longName", ticker),
            "description": (info.get("longBusinessSummary", "") or "")[:300],
            "currency": info.get("currency", "USD")
        },
        "source": "yahoo"
    }
