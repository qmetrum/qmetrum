"""Parse a custodian/brokerage holdings export into normalized positions.

Custodian CSVs vary wildly in column names and formatting ($, commas, %, mixed
date formats, total/cash junk rows), so this is deliberately forgiving: it maps
a wide set of header synonyms, coerces messy numbers, and reports what it
skipped rather than failing the whole file. Pure and network-free so it is
unit-testable; weight derivation (needs live prices) happens in the endpoint.

Output per holding: {ticker, quantity, cost_basis (TOTAL), purchase_date (ISO
or None), asset_type}. cost_basis is the position's TOTAL cost (matches how
Position.cost_basis is used for $ P&L); a per-share "unit cost" column is
multiplied by quantity.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any, Optional

# Header synonym sets (matched case-insensitively, punctuation-stripped).
_HEADERS = {
    "ticker": {"ticker", "symbol", "sym", "security symbol", "securitysymbol", "security"},
    "quantity": {"quantity", "qty", "shares", "share", "units", "unit", "position", "shares held"},
    "cost_basis": {"cost basis", "costbasis", "total cost", "totalcost", "book value",
                   "bookvalue", "cost", "adjusted cost basis", "cost basis total"},
    "unit_cost": {"unit cost", "unitcost", "average cost", "avg cost", "avgcost", "price paid",
                  "purchase price", "purchaseprice", "cost per share", "average price"},
    "purchase_date": {"purchase date", "purchasedate", "date acquired", "dateacquired",
                      "acquired", "acquisition date", "buy date", "trade date", "date"},
    "asset_type": {"asset type", "assettype", "type", "security type", "securitytype", "class"},
    "market_value": {"market value", "marketvalue", "value", "current value", "mv",
                     "market val", "position value"},
    "weight": {"weight", "allocation", "% of portfolio", "percent", "% assets", "target %"},
}

# Rows whose ticker cell is one of these are custodian summary/cash lines, not
# holdings; skip rather than treat "TOTAL" as a ticker.
_JUNK_TICKERS = {"total", "totals", "cash", "cash & equivalents", "grand total",
                 "subtotal", "account total", "n/a", "", "-"}


def _canon(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (h or "").strip().lower()).strip()


def _num(v: Any) -> Optional[float]:
    """Coerce '$1,234.56', '(500)', '10%', '' into a float or None."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")  # accounting negatives
    s = s.replace("(", "").replace(")", "").replace("$", "").replace(",", "").replace("%", "").strip()
    if s in {"", "-", "n/a", "na"}:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return -f if neg else f


_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d-%b-%Y",
                 "%b %d, %Y", "%m-%d-%Y", "%Y/%m/%d"]


def _parse_date(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {"n/a", "na", "-", "various"}:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _map_columns(fieldnames: list[str]) -> dict[str, str]:
    """Map our canonical field -> the actual header present in the file."""
    mapping: dict[str, str] = {}
    for raw in fieldnames or []:
        c = _canon(raw)
        for field, synonyms in _HEADERS.items():
            if field in mapping:
                continue
            if c in synonyms:
                mapping[field] = raw
                break
    return mapping


def parse_holdings_csv(text: str) -> dict[str, Any]:
    """Parse holdings CSV text. Returns
    {holdings: [...], warnings: [...], skipped: [{row, reason}], columns: {...}}."""
    if not text or not text.strip():
        return {"holdings": [], "warnings": ["The file was empty."], "skipped": [], "columns": {}}

    # Sniff the delimiter (comma/semicolon/tab), fall back to comma.
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)

    cols = _map_columns(reader.fieldnames or [])
    warnings: list[str] = []
    if "ticker" not in cols:
        return {"holdings": [], "skipped": [],
                "warnings": [f"Could not find a ticker/symbol column. Headers seen: "
                             f"{', '.join(reader.fieldnames or []) or 'none'}."],
                "columns": cols}
    if "quantity" not in cols and "market_value" not in cols and "weight" not in cols:
        warnings.append("No quantity, market value, or weight column found; positions "
                        "will be equal-weighted until you edit them.")

    holdings: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        ticker_raw = (row.get(cols["ticker"]) or "").strip()
        ticker = ticker_raw.upper()
        if _canon(ticker_raw) in _JUNK_TICKERS or not re.match(r"^[A-Z0-9.\-]{1,15}$", ticker):
            if ticker_raw:
                skipped.append({"row": i, "reason": f"'{ticker_raw}' is not a valid ticker"})
            continue

        qty = _num(row.get(cols["quantity"])) if "quantity" in cols else None

        cost_basis = _num(row.get(cols["cost_basis"])) if "cost_basis" in cols else None
        if cost_basis is None and "unit_cost" in cols and qty:
            unit = _num(row.get(cols["unit_cost"]))
            if unit is not None:
                cost_basis = unit * qty

        holdings.append({
            "ticker": ticker,
            "quantity": qty if qty is not None else 0.0,
            "cost_basis": cost_basis if cost_basis is not None else 0.0,
            "purchase_date": _parse_date(row.get(cols["purchase_date"])) if "purchase_date" in cols else None,
            "asset_type": (str(row.get(cols["asset_type"])).strip().upper()
                           if "asset_type" in cols and row.get(cols["asset_type"]) else "EQUITY"),
            # Retained only to derive weights in the endpoint; not stored.
            "_market_value": _num(row.get(cols["market_value"])) if "market_value" in cols else None,
            "_weight": _num(row.get(cols["weight"])) if "weight" in cols else None,
        })

    if not holdings:
        warnings.append("No valid holdings rows were found.")
    return {"holdings": holdings, "warnings": warnings, "skipped": skipped, "columns": cols}
