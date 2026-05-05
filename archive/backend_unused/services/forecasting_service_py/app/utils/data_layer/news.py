from datetime import datetime

def get_news(entity_id: str, limit=5):
    from app.vendors import get_vendor

    try:
        vendor = get_vendor()
        raw_news = vendor.fetch_news(entity_id, limit=limit)
        news = []

        for n in raw_news[:limit]:
            ts = n.get("timestamp")
            if ts and len(ts) >= 10:
                timestamp = ts
            else:
                timestamp = datetime.utcnow().isoformat()

            news.append({
                "title": n.get("title"),
                "publisher": n.get("publisher"),
                "url": n.get("link"),
                "timestamp": timestamp
            })

        return {
            "entity_id": entity_id,
            "metric_type": "news",
            "items": news,
            "source": vendor.name
        }
    except Exception:
        return {
            "entity_id": entity_id,
            "metric_type": "news",
            "items": [],
            "source": "vendor"
        }
