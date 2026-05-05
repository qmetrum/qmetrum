def get_fundamentals(info: dict, asset_type: str):
    if asset_type in ["ETF", "MUTUALFUND"]:
        return {
            "metric_type": "fund_metrics",
            "values": {
                "expense_ratio": info.get("annualReportExpenseRatio"),
                "yield": info.get("yield"),
                "net_assets": info.get("totalAssets"),
                "nav_price": info.get("navPrice"),
                "category": info.get("fundFamily")
            }
        }

    if asset_type == "BOND":
        return {
            "metric_type": "bond_metrics",
            "values": {
                "yield": info.get("yield"),
                "maturity": info.get("expireDate"),
                "coupon": info.get("couponRate")
            }
        }

    return {
        "metric_type": "valuation",
        "values": {
            "market_cap": info.get("marketCap"),
            "pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "ev_ebitda": info.get("enterpriseToEbitda")
        }
    }


def normalize_fundamentals(fundamentals: dict):
    """
    Normalize vendor fundamentals into a metric payload.
    """
    if not isinstance(fundamentals, dict):
        return {"metric_type": "valuation", "values": {}}

    if "fund_metrics" in fundamentals:
        return {"metric_type": "fund_metrics", "values": fundamentals.get("fund_metrics", {})}
    if "bond_metrics" in fundamentals:
        return {"metric_type": "bond_metrics", "values": fundamentals.get("bond_metrics", {})}
    if "valuation" in fundamentals:
        return {"metric_type": "valuation", "values": fundamentals.get("valuation", {})}

    return {"metric_type": "valuation", "values": {}}
