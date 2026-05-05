def get_price_series(entity_id: str, period: str = "2y"):
    from app.vendors import get_vendor

    try:
        vendor = get_vendor()
        rows = vendor.fetch_price_history(entity_id, period=period)
        if not rows:
            return None

        series = [
            {
                "date": row.get("date"),
                "value": float(row.get("price", row.get("value", 0.0)))
            }
            for row in rows
        ]

        return {
            "entity_id": entity_id,
            "metric_type": "price",
            "frequency": "daily",
            "currency": "USD",
            "series": series,
            "source": vendor.name
        }
    except Exception:
        return None
