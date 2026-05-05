#!/usr/bin/env python3
"""Bootstrap one-shot demo data for Qmetrum UI.

This script is designed for local/demo environments where you want enough
asset coverage to test the UI without ingesting the whole market.

What it does:
- Upserts demo portfolios (ids 1,2,3) used by the frontend routes.
- Upserts demo watchlists, alerts, and screener saved screens.
- Warms per-asset profile/price/news/risk caches.
- Optionally warms selected asset forecasts and portfolio-level forecast/quantum caches.
- Writes one volatility snapshot per symbol refresh via /assets/{symbol}/risk?refresh=true.

Usage examples:
  python scripts/seed_demo_cache.py
  python scripts/seed_demo_cache.py --asset-preset standard
  python scripts/seed_demo_cache.py --asset-preset standard --skip-asset-forecasts
  python scripts/seed_demo_cache.py --asset-preset lite --assets BRK-B,XLE
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

DEFAULT_FORECAST_SCENARIOS = [
    {"name": "bear_10", "initial_shock_pct": -0.10, "return_scale": 1.10, "drift_shift": -0.0002},
    {"name": "high_vol", "initial_shock_pct": 0.0, "return_scale": 1.35, "drift_shift": 0.0},
]

DEFAULT_PORTFOLIO_SCENARIOS = [
    {"name": "bear_15", "initial_shock_pct": -0.15, "return_scale": 1.10, "drift_shift": -0.0002},
    {"name": "high_vol", "initial_shock_pct": 0.0, "return_scale": 1.35, "drift_shift": 0.0},
]

# ---------------------------------------------------------------------------
# Asset universes (curated for demo coverage)
# ---------------------------------------------------------------------------

STOCKS_LITE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
    "JPM", "BAC", "WFC", "XOM", "CVX", "JNJ", "PG", "UNH", "WMT", "COST",
]

STOCKS_STANDARD_EXTRA = [
    "ORCL", "ADBE", "CRM", "INTC", "CSCO", "QCOM", "TXN", "AMAT", "INTU", "PANW",
    "GS", "BLK", "C", "MS", "AXP", "COP", "CAT", "DE", "LMT", "RTX",
    "NKE", "MCD", "KO", "PEP", "DIS", "UBER", "IBM", "V", "MA", "PFE",
    "MRK", "ABBV", "BMY", "GE", "HON", "LIN", "ETN", "NEE", "DUK", "SO",
]

ETFS_LITE = [
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "SCHD", "XLK", "XLF", "XLV",
]

ETFS_STANDARD_EXTRA = [
    "XLE", "XLI", "XLP", "XLY", "XLU", "VNQ", "ARKK", "GLD", "SLV",
]

# "5 most popular" bond ETFs + a couple of credit/risk proxies.
BONDS_CORE = ["AGG", "BND", "TLT", "IEF", "SHY"]
BONDS_EXTRA = ["LQD", "HYG", "BIL"]

# S&P 500 constituents (as of early 2026). Some tickers use dots on
# exchanges but Yahoo Finance uses hyphens (e.g. BRK-B, BF-B).
SP500_TICKERS = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "ADI", "ADM", "ADP", "ADSK", "AEE",
    "AEP", "AES", "AFL", "AIG", "AIZ", "AJG", "AKAM", "ALB", "ALGN", "ALK",
    "ALL", "ALLE", "AMAT", "AMCR", "AMD", "AME", "AMGN", "AMP", "AMT", "AMZN",
    "ANET", "ANSS", "AON", "AOS", "APA", "APD", "APH", "APTV", "ARE", "ATO",
    "ATVI", "AVB", "AVGO", "AVY", "AWK", "AXP", "AZO", "BA", "BAC", "BAX",
    "BBWI", "BBY", "BDX", "BEN", "BF-B", "BIO", "BIIB", "BK", "BKNG", "BKR",
    "BLK", "BMY", "BR", "BRK-B", "BRO", "BSX", "BWA", "BXP", "C", "CAG",
    "CAH", "CARR", "CAT", "CB", "CBOE", "CBRE", "CCI", "CCL", "CDAY", "CDNS",
    "CDW", "CE", "CEG", "CF", "CFG", "CHD", "CHRW", "CHTR", "CI", "CINF",
    "CL", "CLX", "CMA", "CMCSA", "CME", "CMG", "CMI", "CMS", "CNC", "CNP",
    "COF", "COO", "COP", "COST", "CPB", "CPRT", "CPT", "CRL", "CRM", "CSCO",
    "CSGP", "CSX", "CTAS", "CTLT", "CTRA", "CTSH", "CTVA", "CVS", "CVX", "CZR",
    "D", "DAL", "DD", "DE", "DFS", "DG", "DGX", "DHI", "DHR", "DIS",
    "DISH", "DLR", "DLTR", "DOV", "DOW", "DPZ", "DRI", "DTE", "DUK", "DVA",
    "DVN", "DXC", "DXCM", "EA", "EBAY", "ECL", "ED", "EFX", "EIX", "EL",
    "EMN", "EMR", "ENPH", "EOG", "EPAM", "EQIX", "EQR", "EQT", "ES", "ESS",
    "ETN", "ETR", "ETSY", "EVRG", "EW", "EXC", "EXPD", "EXPE", "EXR", "F",
    "FANG", "FAST", "FBHS", "FCX", "FDS", "FDX", "FE", "FFIV", "FIS", "FISV",
    "FITB", "FLT", "FMC", "FOX", "FOXA", "FRC", "FRT", "FTNT", "FTV", "GD",
    "GE", "GILD", "GIS", "GL", "GLW", "GM", "GNRC", "GOOG", "GOOGL", "GPC",
    "GPN", "GRMN", "GS", "GWW", "HAL", "HAS", "HBAN", "HCA", "HD", "PEAK",
    "HES", "HIG", "HII", "HLT", "HOLX", "HON", "HPE", "HPQ", "HRL", "HSIC",
    "HST", "HSY", "HUM", "HWM", "IBM", "ICE", "IDXX", "IEX", "IFF", "ILMN",
    "INCY", "INTC", "INTU", "INVH", "IP", "IPG", "IQV", "IR", "IRM", "ISRG",
    "IT", "ITW", "IVZ", "J", "JBHT", "JCI", "JKHY", "JNJ", "JNPR", "JPM",
    "K", "KDP", "KEY", "KEYS", "KHC", "KIM", "KLAC", "KMB", "KMI", "KMX",
    "KO", "KR", "L", "LDOS", "LEN", "LH", "LHX", "LIN", "LKQ", "LLY",
    "LMT", "LNC", "LNT", "LOW", "LRCX", "LUMN", "LUV", "LVS", "LW", "LYB",
    "LYV", "MA", "MAA", "MAR", "MAS", "MCD", "MCHP", "MCK", "MCO", "MDLZ",
    "MDT", "MET", "META", "MGM", "MHK", "MKC", "MKTX", "MLM", "MMC", "MMM",
    "MNST", "MO", "MOH", "MOS", "MPC", "MPWR", "MRK", "MRNA", "MRO", "MS",
    "MSCI", "MSFT", "MSI", "MTB", "MTCH", "MTD", "MU", "NCLH", "NDAQ", "NDSN",
    "NEE", "NEM", "NFLX", "NI", "NKE", "NOC", "NOW", "NRG", "NSC", "NTAP",
    "NTRS", "NUE", "NVDA", "NVR", "NWL", "NWS", "NWSA", "NXPI", "O", "ODFL",
    "OGN", "OKE", "OMC", "ON", "ORCL", "ORLY", "OTIS", "OXY", "PARA", "PAYC",
    "PAYX", "PCAR", "PCG", "PEAK", "PEG", "PEP", "PFE", "PFG", "PG", "PGR",
    "PH", "PHM", "PKG", "PKI", "PLD", "PM", "PNC", "PNR", "PNW", "POOL",
    "PPG", "PPL", "PRU", "PSA", "PSX", "PTC", "PVH", "PWR", "PXD", "PYPL",
    "QCOM", "QRVO", "RCL", "RE", "REG", "REGN", "RF", "RHI", "RJF", "RL",
    "RMD", "ROK", "ROL", "ROP", "ROST", "RSG", "RTX", "SBAC", "SBNY", "SBUX",
    "SCHW", "SEE", "SHW", "SIVB", "SJM", "SLB", "SNA", "SNPS", "SO", "SPG",
    "SPGI", "SRE", "STE", "STT", "STX", "STZ", "SWK", "SWKS", "SYF", "SYK",
    "SYY", "T", "TAP", "TDG", "TDY", "TECH", "TEL", "TER", "TFC", "TFX",
    "TGT", "TMO", "TMUS", "TPR", "TRGP", "TRMB", "TROW", "TRV", "TSCO", "TSLA",
    "TSN", "TT", "TTWO", "TXN", "TXT", "TYL", "UAL", "UDR", "UHS", "ULTA",
    "UNH", "UNP", "UPS", "URI", "USB", "V", "VFC", "VICI", "VLO", "VMC",
    "VNO", "VRSK", "VRSN", "VRTX", "VTR", "VTRS", "VZ", "WAB", "WAT", "WBA",
    "WBD", "WDC", "WEC", "WELL", "WFC", "WHR", "WM", "WMB", "WMT", "WRB",
    "WRK", "WST", "WTW", "WY", "WYNN", "XEL", "XOM", "XRAY", "XYL", "YUM",
    "ZBH", "ZBRA", "ZION", "ZTS",
]

# Top 50 most traded S&P 500 names — precompute forecasts for these.
SP500_FORECAST_TOP50 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V",
    "UNH", "MA", "HD", "PG", "JNJ", "XOM", "COST", "ABBV", "MRK", "BAC",
    "NFLX", "AMD", "CRM", "LLY", "CVX", "KO", "PEP", "WMT", "ADBE", "TMO",
    "ORCL", "CSCO", "ACN", "DHR", "MCD", "ABT", "INTC", "NKE", "DIS", "QCOM",
    "TXN", "NEE", "PM", "BMY", "UNP", "UPS", "GS", "MS", "CAT", "DE",
]

ASSET_PRESETS: Dict[str, List[str]] = {
    "lite": sorted(set(STOCKS_LITE + ETFS_LITE + BONDS_CORE)),
    "standard": sorted(
        set(STOCKS_LITE + STOCKS_STANDARD_EXTRA + ETFS_LITE + ETFS_STANDARD_EXTRA + BONDS_CORE + BONDS_EXTRA)
    ),
    "wide": sorted(
        set(
            STOCKS_LITE
            + STOCKS_STANDARD_EXTRA
            + [
                "PLTR", "SNOW", "SHOP", "ARM", "TMUS", "PYPL", "TGT", "LOW", "ADI", "MU",
                "VRTX", "ISRG", "MDT", "AMGN", "SPGI", "MCO", "CB", "USB", "BK", "SCHW",
            ]
            + ETFS_LITE
            + ETFS_STANDARD_EXTRA
            + ["VYM", "USMV", "XBI", "SMH", "EEM", "VEA"]
            + BONDS_CORE
            + BONDS_EXTRA
        )
    ),
    "sp500": sorted(set(SP500_TICKERS + ETFS_LITE + BONDS_CORE)),
}

# Fast subset to precompute expensive asset forecast models.
DEFAULT_FORECAST_ASSETS = ["AAPL", "MSFT", "NVDA", "AMZN", "SPY", "QQQ", "IWM", "AGG", "TLT", "BND"]

# When using sp500 preset, forecast these top names + core ETFs/bonds.
SP500_FORECAST_DEFAULTS = sorted(set(SP500_FORECAST_TOP50 + ETFS_LITE + BONDS_CORE))

# ---------------------------------------------------------------------------
# Demo UI artifacts
# ---------------------------------------------------------------------------

PORTFOLIO_TEMPLATES = [
    {
        "id": 1,
        "name": "Big Tech Growth",
        "assets": [
            {"ticker": "AAPL", "weight": 0.24, "asset_type": "EQUITY"},
            {"ticker": "MSFT", "weight": 0.24, "asset_type": "EQUITY"},
            {"ticker": "NVDA", "weight": 0.20, "asset_type": "EQUITY"},
            {"ticker": "AMZN", "weight": 0.16, "asset_type": "EQUITY"},
            {"ticker": "GOOGL", "weight": 0.16, "asset_type": "EQUITY"},
        ],
    },
    {
        "id": 2,
        "name": "ETF Core",
        "assets": [
            {"ticker": "SPY", "weight": 0.35, "asset_type": "ETF"},
            {"ticker": "QQQ", "weight": 0.25, "asset_type": "ETF"},
            {"ticker": "IWM", "weight": 0.10, "asset_type": "ETF"},
            {"ticker": "AGG", "weight": 0.15, "asset_type": "ETF"},
            {"ticker": "TLT", "weight": 0.10, "asset_type": "ETF"},
            {"ticker": "GLD", "weight": 0.05, "asset_type": "ETF"},
        ],
    },
    {
        "id": 3,
        "name": "Income & Defensive",
        "assets": [
            {"ticker": "JNJ", "weight": 0.12, "asset_type": "EQUITY"},
            {"ticker": "PG", "weight": 0.12, "asset_type": "EQUITY"},
            {"ticker": "KO", "weight": 0.10, "asset_type": "EQUITY"},
            {"ticker": "XLU", "weight": 0.12, "asset_type": "ETF"},
            {"ticker": "BND", "weight": 0.24, "asset_type": "ETF"},
            {"ticker": "LQD", "weight": 0.15, "asset_type": "ETF"},
            {"ticker": "SHY", "weight": 0.15, "asset_type": "ETF"},
        ],
    },
]

WATCHLIST_TEMPLATES = [
    {"name": "Mega Cap Leaders", "tickers": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"]},
    {"name": "ETF Rotation", "tickers": ["SPY", "QQQ", "IWM", "XLK", "XLF", "XLV", "XLE"]},
    {"name": "Rates & Credit", "tickers": ["TLT", "IEF", "SHY", "LQD", "HYG", "BND", "AGG"]},
]

ALERT_TEMPLATES = [
    {"name": "AAPL Breakout", "ticker": "AAPL", "watchlist": "Mega Cap Leaders", "direction": "above", "threshold": 250},
    {"name": "SPY Pullback", "ticker": "SPY", "watchlist": "ETF Rotation", "direction": "below", "threshold": 500},
    {"name": "TLT Risk-Off", "ticker": "TLT", "watchlist": "Rates & Credit", "direction": "above", "threshold": 100},
    {"name": "HYG Credit Stress", "ticker": "HYG", "watchlist": "Rates & Credit", "direction": "below", "threshold": 75},
]

SCREEN_TEMPLATES = [
    {
        "name": "Quality Large Caps",
        "description": "Large caps with healthy profitability",
        "filters": {
            "min_market_cap": 100000000000,
            "min_profit_margin": 0.10,
            "min_pe_ratio": 5,
            "max_pe_ratio": 45,
        },
    },
    {
        "name": "Low Beta Defensives",
        "description": "Lower beta names for defensive posture",
        "filters": {
            "max_beta": 1.0,
            "sector_in": ["Utilities", "Consumer Defensive", "Healthcare"],
        },
    },
]


def parse_csv_symbols(value: str) -> List[str]:
    return [v.strip().upper() for v in value.split(",") if v.strip()]


def unique_symbols(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        symbol = str(value).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    json_payload: Optional[dict] = None,
    timeout_seconds: int = 180,
) -> dict:
    response = session.request(
        method,
        url,
        params=params,
        json=json_payload,
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} -> HTTP {response.status_code}: {response.text[:400]}")
    if not response.text:
        return {}
    return response.json()


def safe_call(
    session: requests.Session,
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    json_payload: Optional[dict] = None,
    timeout_seconds: int = 180,
) -> Tuple[bool, Optional[dict], Optional[str]]:
    try:
        data = request_json(
            session,
            method,
            url,
            params=params,
            json_payload=json_payload,
            timeout_seconds=timeout_seconds,
        )
        return True, data, None
    except Exception as exc:
        return False, None, str(exc)


def upsert_portfolios(session: requests.Session, base_url: str) -> List[int]:
    print("\n== Upserting demo portfolios ==")
    created_ids: List[int] = []
    for template in PORTFOLIO_TEMPLATES:
        pid = int(template["id"])
        payload = {"name": template["name"], "assets": template["assets"]}
        ok, _, err = safe_call(
            session,
            "PUT",
            f"{base_url}/portfolios/{pid}",
            json_payload=payload,
            timeout_seconds=180,
        )
        if ok:
            print(f"  portfolio {pid}: {template['name']}")
            created_ids.append(pid)
        else:
            print(f"  portfolio {pid} failed: {err}")
    return created_ids


def upsert_watchlists(session: requests.Session, base_url: str) -> Dict[str, int]:
    print("\n== Upserting watchlists ==")
    ok, data, err = safe_call(session, "GET", f"{base_url}/watchlists", timeout_seconds=60)
    if not ok:
        print(f"  list watchlists failed: {err}")
        return {}

    items = (data or {}).get("items", [])
    by_name = {str(w.get("name", "")).strip(): int(w.get("watchlist_id")) for w in items if w.get("watchlist_id")}

    for template in WATCHLIST_TEMPLATES:
        name = template["name"]
        payload = {"name": name, "tickers": template["tickers"]}

        if name in by_name:
            wid = by_name[name]
            ok, _, err = safe_call(
                session,
                "PUT",
                f"{base_url}/watchlists/{wid}",
                json_payload=payload,
                timeout_seconds=90,
            )
            if ok:
                print(f"  watchlist updated: {name} (id={wid})")
            else:
                print(f"  watchlist update failed ({name}): {err}")
        else:
            ok, created, err = safe_call(
                session,
                "POST",
                f"{base_url}/watchlists",
                json_payload=payload,
                timeout_seconds=90,
            )
            if ok:
                wid = int((created or {}).get("watchlist_id"))
                by_name[name] = wid
                print(f"  watchlist created: {name} (id={wid})")
            else:
                print(f"  watchlist create failed ({name}): {err}")

    # refresh map to ensure ids are accurate
    ok, data, err = safe_call(session, "GET", f"{base_url}/watchlists", timeout_seconds=60)
    if ok:
        items = (data or {}).get("items", [])
        by_name = {str(w.get("name", "")).strip(): int(w.get("watchlist_id")) for w in items if w.get("watchlist_id")}
    return by_name


def upsert_alerts(session: requests.Session, base_url: str, watchlist_ids: Dict[str, int]) -> None:
    print("\n== Upserting alerts ==")

    ok, data, err = safe_call(
        session,
        "GET",
        f"{base_url}/alerts",
        params={"active_only": False},
        timeout_seconds=60,
    )
    if not ok:
        print(f"  list alerts failed: {err}")
        return

    existing = (data or {}).get("items", [])
    existing_by_key = {}
    for row in existing:
        key = (str(row.get("name", "")).strip(), str(row.get("ticker", "")).upper().strip())
        if row.get("id"):
            existing_by_key[key] = int(row["id"])

    for template in ALERT_TEMPLATES:
        name = template["name"]
        ticker = template["ticker"].upper()
        key = (name, ticker)
        watchlist_id = watchlist_ids.get(template["watchlist"])

        create_payload = {
            "name": name,
            "ticker": ticker,
            "alert_type": "price_threshold",
            "direction": template["direction"],
            "threshold_value": float(template["threshold"]),
            "lookback_days": 30,
            "watchlist_id": watchlist_id,
            "extra_config": {},
            "is_active": True,
        }

        if key in existing_by_key:
            alert_id = existing_by_key[key]
            update_payload = {
                "name": name,
                "direction": template["direction"],
                "threshold_value": float(template["threshold"]),
                "lookback_days": 30,
                "is_active": True,
                "extra_config": {},
            }
            ok, _, err = safe_call(
                session,
                "PUT",
                f"{base_url}/alerts/{alert_id}",
                json_payload=update_payload,
                timeout_seconds=60,
            )
            if ok:
                print(f"  alert updated: {name} ({ticker})")
            else:
                print(f"  alert update failed ({name}/{ticker}): {err}")
        else:
            ok, _, err = safe_call(
                session,
                "POST",
                f"{base_url}/alerts",
                json_payload=create_payload,
                timeout_seconds=60,
            )
            if ok:
                print(f"  alert created: {name} ({ticker})")
            else:
                print(f"  alert create failed ({name}/{ticker}): {err}")


def upsert_screener_screens(session: requests.Session, base_url: str) -> None:
    print("\n== Upserting screener screens ==")

    ok, data, err = safe_call(session, "GET", f"{base_url}/screener/screens", timeout_seconds=60)
    if not ok:
        print(f"  list screens failed: {err}")
        return

    items = (data or {}).get("items", [])
    by_name = {str(s.get("name", "")).strip(): int(s.get("id")) for s in items if s.get("id")}

    for template in SCREEN_TEMPLATES:
        payload = {
            "name": template["name"],
            "description": template.get("description"),
            "filters": template["filters"],
        }
        name = template["name"]

        if name in by_name:
            sid = by_name[name]
            ok, _, err = safe_call(
                session,
                "PUT",
                f"{base_url}/screener/screens/{sid}",
                json_payload=payload,
                timeout_seconds=60,
            )
            if ok:
                print(f"  screen updated: {name}")
            else:
                print(f"  screen update failed ({name}): {err}")
        else:
            ok, _, err = safe_call(
                session,
                "POST",
                f"{base_url}/screener/screens",
                json_payload=payload,
                timeout_seconds=60,
            )
            if ok:
                print(f"  screen created: {name}")
            else:
                print(f"  screen create failed ({name}): {err}")


def warm_asset(
    session: requests.Session,
    base_url: str,
    symbol: str,
    *,
    period: str,
    horizon_days: int,
    n_paths: int,
    news_limit: int,
    warm_forecast: bool,
) -> List[str]:
    errors: List[str] = []

    steps = [
        ("profile", "GET", f"{base_url}/assets/{symbol}/profile", None, None, 90),
        ("price", "GET", f"{base_url}/assets/{symbol}/price", {"period": period}, None, 90),
        (
            "risk_refresh",
            "GET",
            f"{base_url}/assets/{symbol}/risk",
            {"horizon_days": horizon_days, "n_paths": n_paths, "refresh": True},
            None,
            180,
        ),
        (
            "news_refresh",
            "GET",
            f"{base_url}/assets/{symbol}/news",
            {"limit": news_limit, "refresh": True},
            None,
            90,
        ),
    ]

    if warm_forecast:
        steps.append(
            (
                "forecast_base",
                "POST",
                f"{base_url}/assets/{symbol}/forecast",
                None,
                {"horizon_days": horizon_days},
                420,
            )
        )
        steps.append(
            (
                "forecast_scenarios",
                "POST",
                f"{base_url}/assets/{symbol}/forecast",
                None,
                {"horizon_days": horizon_days, "scenarios": DEFAULT_FORECAST_SCENARIOS},
                420,
            )
        )

    for step_name, method, url, params, payload, timeout_seconds in steps:
        ok, _, err = safe_call(
            session,
            method,
            url,
            params=params,
            json_payload=payload,
            timeout_seconds=timeout_seconds,
        )
        if not ok:
            errors.append(f"{step_name}: {err}")

    return errors


def warm_portfolio(
    session: requests.Session,
    base_url: str,
    portfolio_id: int,
    *,
    horizon_days: int,
) -> List[str]:
    errors: List[str] = []

    ok, _, err = safe_call(
        session,
        "POST",
        f"{base_url}/portfolios/{portfolio_id}/forecast",
        params={"async_mode": False, "force_refresh": True},
        json_payload={"horizon_days": horizon_days, "scenarios": DEFAULT_PORTFOLIO_SCENARIOS},
        timeout_seconds=900,
    )
    if not ok:
        errors.append(f"forecast: {err}")

    ok, _, err = safe_call(
        session,
        "POST",
        f"{base_url}/portfolios/{portfolio_id}/simulate_quantum_risk",
        json_payload={"horizon_days": 30, "n_simulations": 1500, "random_seed": 42},
        timeout_seconds=420,
    )
    if not ok:
        errors.append(f"quantum: {err}")

    return errors


def evaluate_alerts(session: requests.Session, base_url: str) -> None:
    print("\n== Evaluating alerts once (persist events) ==")
    ok, data, err = safe_call(
        session,
        "POST",
        f"{base_url}/alerts/evaluate",
        params={"active_only": True, "persist": True},
        timeout_seconds=240,
    )
    if not ok:
        print(f"  evaluate failed: {err}")
        return
    evaluated_count = int((data or {}).get("evaluated_count", 0))
    triggered_count = int((data or {}).get("triggered_count", 0))
    print(f"  evaluated={evaluated_count} triggered={triggered_count}")


SP500_CACHE_FILE = Path(__file__).parent / "sp500_validated.json"
SP500_CACHE_MAX_AGE_DAYS = 7

WIKIPEDIA_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_sp500_from_wikipedia() -> List[str]:
    """Scrape current S&P 500 constituents from Wikipedia."""
    import pandas as pd

    print("\n== Fetching S&P 500 list from Wikipedia ==")
    try:
        # Wikipedia blocks requests without a User-Agent header (HTTP 403).
        # Fetch the HTML via requests with a proper UA, then parse with pd.read_html.
        import io
        resp = requests.get(
            WIKIPEDIA_SP500_URL,
            headers={"User-Agent": "QmetrumForecaster/1.0 (research; +https://github.com)"},
            timeout=15,
        )
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        df = tables[0]
        tickers = [str(t).strip().replace(".", "-") for t in df["Symbol"].tolist()]
        print(f"  fetched {len(tickers)} tickers from Wikipedia")
        return sorted(set(tickers))
    except Exception as exc:
        print(f"  Wikipedia fetch failed: {exc}")
        return []


def validate_tickers(
    session: requests.Session,
    base_url: str,
    tickers: List[str],
) -> List[str]:
    """Hit /assets/{symbol}/profile for each ticker; keep only those that return 200."""
    print(f"\n== Validating {len(tickers)} tickers against backend ==")
    valid: List[str] = []
    invalid: List[str] = []
    for idx, symbol in enumerate(tickers, start=1):
        try:
            resp = session.get(f"{base_url}/assets/{symbol}/profile", timeout=30)
            if resp.status_code < 400:
                valid.append(symbol)
            else:
                invalid.append(symbol)
                if idx <= 20 or idx % 50 == 0:
                    print(f"  [{idx:>3}/{len(tickers)}] {symbol} -> {resp.status_code} (dropped)")
        except Exception:
            invalid.append(symbol)
    print(f"  valid={len(valid)}  dropped={len(invalid)}")
    if invalid:
        print(f"  dropped tickers: {', '.join(invalid[:30])}")
        if len(invalid) > 30:
            print(f"    ... and {len(invalid) - 30} more")
    return valid


def load_or_refresh_sp500(
    session: requests.Session,
    base_url: str,
    *,
    force_refresh: bool = False,
) -> List[str]:
    """Return a validated S&P 500 ticker list, refreshing from Wikipedia + backend when stale."""
    if not force_refresh and SP500_CACHE_FILE.exists():
        try:
            cache = json.loads(SP500_CACHE_FILE.read_text())
            age_days = (time.time() - cache.get("timestamp", 0)) / 86400
            if age_days < SP500_CACHE_MAX_AGE_DAYS and cache.get("tickers"):
                print(f"\n== Using cached validated S&P 500 list ({len(cache['tickers'])} tickers, {age_days:.1f} days old) ==")
                return cache["tickers"]
        except Exception:
            pass

    wiki_tickers = fetch_sp500_from_wikipedia()
    if not wiki_tickers:
        print("  falling back to hardcoded SP500_TICKERS list")
        wiki_tickers = list(SP500_TICKERS)

    valid = validate_tickers(session, base_url, wiki_tickers)
    if not valid:
        print("  validation returned 0 tickers — falling back to hardcoded list")
        return list(SP500_TICKERS)

    cache_data = {
        "timestamp": time.time(),
        "fetched_count": len(wiki_tickers),
        "valid_count": len(valid),
        "tickers": valid,
    }
    try:
        SP500_CACHE_FILE.write_text(json.dumps(cache_data, indent=2))
        print(f"  cached {len(valid)} validated tickers to {SP500_CACHE_FILE.name}")
    except Exception as exc:
        print(f"  cache write failed: {exc}")

    return valid


def build_assets_from_args(
    args: argparse.Namespace,
    session: requests.Session,
    base_url: str,
) -> List[str]:
    if args.asset_preset == "sp500":
        sp500_valid = load_or_refresh_sp500(
            session, base_url, force_refresh=args.refresh_sp500,
        )
        base = sorted(set(sp500_valid + ETFS_LITE + BONDS_CORE))
    else:
        base = ASSET_PRESETS.get(args.asset_preset, ASSET_PRESETS["lite"])

    extra = parse_csv_symbols(args.assets) if args.assets else []

    must_have: List[str] = []
    for p in PORTFOLIO_TEMPLATES:
        must_have.extend([a["ticker"] for a in p["assets"]])
    for w in WATCHLIST_TEMPLATES:
        must_have.extend(w["tickers"])
    for a in ALERT_TEMPLATES:
        must_have.append(a["ticker"])

    symbols = unique_symbols(list(base) + extra + must_have)

    if args.max_assets is not None and args.max_assets > 0:
        symbols = symbols[: args.max_assets]
    return symbols


def parse_forecast_assets(value: str, all_assets: List[str], preset: str = "lite") -> List[str]:
    raw = value.strip().lower()
    if raw == "all":
        return list(all_assets)
    if raw == "default":
        defaults = SP500_FORECAST_DEFAULTS if preset == "sp500" else DEFAULT_FORECAST_ASSETS
        return [s for s in defaults if s in set(all_assets)]
    return [s for s in parse_csv_symbols(value) if s in set(all_assets)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap one-shot demo cache/data for Qmetrum backend")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user-id", default="1")

    parser.add_argument("--asset-preset", choices=["lite", "standard", "wide", "sp500"], default="lite")
    parser.add_argument("--assets", default="", help="Extra CSV symbols to include")
    parser.add_argument("--max-assets", type=int, default=None)

    parser.add_argument("--forecast-assets", default="default", help="CSV symbols, 'default', or 'all'")
    parser.add_argument("--skip-asset-forecasts", action="store_true")
    parser.add_argument("--skip-portfolio-warm", action="store_true")
    parser.add_argument("--skip-ui-artifacts", action="store_true", help="Skip portfolios/watchlists/alerts/screens upserts")
    parser.add_argument("--refresh-sp500", action="store_true", help="Force re-fetch and re-validate S&P 500 list from Wikipedia")

    parser.add_argument("--period", default="2y")
    parser.add_argument("--horizon-days", type=int, default=90)
    parser.add_argument("--n-paths", type=int, default=1000)
    parser.add_argument("--news-limit", type=int, default=10)
    parser.add_argument("--sleep-ms", type=int, default=0, help="Pause between asset warm calls")

    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"X-User-Id": str(args.user_id), "Content-Type": "application/json"})

    assets = build_assets_from_args(args, session, args.base_url)
    if not assets:
        print("No assets resolved.", file=sys.stderr)
        return 2

    forecast_assets = []
    if not args.skip_asset_forecasts:
        forecast_assets = parse_forecast_assets(args.forecast_assets, assets, preset=args.asset_preset)

    started = time.time()

    # Keep these for summary/reporting.
    asset_failures: Dict[str, List[str]] = {}
    portfolio_failures: Dict[int, List[str]] = {}

    print("Demo bootstrap configuration")
    print(json.dumps(
        {
            "base_url": args.base_url,
            "user_id": args.user_id,
            "asset_preset": args.asset_preset,
            "asset_count": len(assets),
            "asset_forecast_count": len(forecast_assets),
            "period": args.period,
            "horizon_days": args.horizon_days,
            "n_paths": args.n_paths,
            "news_limit": args.news_limit,
        },
        indent=2,
    ))

    portfolio_ids: List[int] = [1, 2, 3]
    watchlist_ids: Dict[str, int] = {}

    if not args.skip_ui_artifacts:
        portfolio_ids = upsert_portfolios(session, args.base_url)
        watchlist_ids = upsert_watchlists(session, args.base_url)
        upsert_alerts(session, args.base_url, watchlist_ids)
        upsert_screener_screens(session, args.base_url)

    print("\n== Warming asset caches ==")
    for idx, symbol in enumerate(assets, start=1):
        warm_fc = symbol in set(forecast_assets)
        print(f"  [{idx:>3}/{len(assets)}] {symbol} (forecast={'yes' if warm_fc else 'no'})")
        errors = warm_asset(
            session,
            args.base_url,
            symbol,
            period=args.period,
            horizon_days=args.horizon_days,
            n_paths=args.n_paths,
            news_limit=args.news_limit,
            warm_forecast=warm_fc,
        )
        if errors:
            asset_failures[symbol] = errors

        if args.sleep_ms > 0:
            time.sleep(max(0.0, args.sleep_ms / 1000.0))

    if not args.skip_portfolio_warm:
        print("\n== Warming portfolio caches ==")
        for pid in portfolio_ids:
            print(f"  portfolio {pid}")
            errors = warm_portfolio(
                session,
                args.base_url,
                pid,
                horizon_days=args.horizon_days,
            )
            if errors:
                portfolio_failures[pid] = errors

    evaluate_alerts(session, args.base_url)

    elapsed = time.time() - started

    summary = {
        "status": "ok" if not asset_failures and not portfolio_failures else "partial",
        "assets_total": len(assets),
        "assets_warmed": len(assets) - len(asset_failures),
        "assets_failed": len(asset_failures),
        "forecast_assets": forecast_assets,
        "portfolios_warmed": [] if args.skip_portfolio_warm else portfolio_ids,
        "portfolio_failures": portfolio_failures,
        "asset_failures": asset_failures,
        "elapsed_seconds": round(elapsed, 2),
    }

    print("\nBootstrap complete")
    print(json.dumps(summary, indent=2))

    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
