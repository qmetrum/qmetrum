from app.utils.data_layer.classification import get_classification
from app.utils.data_layer.profile import get_profile
from app.utils.data_layer.fundamentals import normalize_fundamentals
from app.utils.data_layer.market_data import get_price_series
from app.utils.data_layer.ownership import get_holdings
from app.utils.data_layer.news import get_news
from app.vendors import get_vendor

def assemble_entity_snapshot(ticker: str):
    vendor = get_vendor()
    fundamentals_raw = vendor.fetch_fundamentals(ticker)

    classification = get_classification(fundamentals_raw, ticker)
    profile = get_profile(fundamentals_raw, ticker)
    fundamentals = normalize_fundamentals(fundamentals_raw)
    price = get_price_series(ticker)
    holdings = get_holdings(ticker, fundamentals_raw)
    news = get_news(ticker)

    return {
        "entity": {
            "id": ticker,
            "type": classification["values"]["type"]
        },
        "metrics": {
            "profile": profile,
            "classification": classification,
            fundamentals["metric_type"]: fundamentals,
            "price": price
        },
        "attachments": {
            "holdings": holdings,
            "news": news
        }
    }
