from datetime import datetime, timedelta
from typing import List, Dict, Optional

from sqlmodel import Session, select

from app.db.database import engine
from app.db.models import Asset, MarketData, FundamentalsSnapshot
from app.utils.data_fetcher import fetch_stock_data, fetch_fundamentals

_PERIOD_DAYS = {
    "1d": 1,
    "5d": 5,
    "1mo": 31,
    "3mo": 93,
    "6mo": 186,
    "1y": 366,
    "2y": 732,
    "5y": 1830,
    "10y": 3660,
    "ytd": 366,
    "max": 36500,
}


def _canonical_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _period_to_days(period: str) -> int:
    return _PERIOD_DAYS.get(str(period or "2y").lower(), 732)


def _ensure_asset_exists(session: Session, symbol: str) -> Asset:
    canon = _canonical_symbol(symbol)
    asset = session.get(Asset, canon)
    if asset:
        return asset

    now = datetime.utcnow()
    asset = Asset(
        symbol=canon,
        name=canon,
        asset_type="UNKNOWN",
        currency="USD",
        vendor="yahoo",
        vendor_symbol=canon,
        created_at=now,
        updated_at=now,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def _rows_to_price_series(rows: List[MarketData]) -> List[Dict]:
    return [
        {
            "date": row.date.strftime("%Y-%m-%d"),
            "price": float(row.close),
        }
        for row in rows
    ]


def _get_price_series_cached_internal(
    session: Session,
    symbol: str,
    period: str = "2y",
    force_refresh: bool = False,
) -> List[Dict]:
    canon = _canonical_symbol(symbol)
    cutoff = datetime.utcnow() - timedelta(days=_period_to_days(period))

    if not force_refresh:
        cached_rows = session.exec(
            select(MarketData)
            .where(MarketData.symbol == canon)
            .where(MarketData.date >= cutoff)
            .order_by(MarketData.date.asc())
        ).all()
        if cached_rows:
            return _rows_to_price_series(cached_rows)

    vendor_rows = fetch_stock_data(canon, period=period)
    if vendor_rows:
        _ensure_asset_exists(session, canon)
        now = datetime.utcnow()
        for row in vendor_rows:
            date_value = datetime.strptime(str(row["date"]), "%Y-%m-%d")
            close_price = float(row.get("price", 0.0) or 0.0)
            existing = session.exec(
                select(MarketData)
                .where(MarketData.symbol == canon)
                .where(MarketData.date == date_value)
            ).first()
            if existing:
                existing.close = close_price
                if existing.open == 0.0:
                    existing.open = close_price
                if existing.high == 0.0:
                    existing.high = close_price
                if existing.low == 0.0:
                    existing.low = close_price
                existing.updated_at = now
            else:
                session.add(
                    MarketData(
                        symbol=canon,
                        date=date_value,
                        open=close_price,
                        high=close_price,
                        low=close_price,
                        close=close_price,
                        volume=float(row.get("volume", 0.0) or 0.0),
                        source="yahoo",
                        created_at=now,
                        updated_at=now,
                    )
                )
        session.commit()

    final_rows = session.exec(
        select(MarketData)
        .where(MarketData.symbol == canon)
        .where(MarketData.date >= cutoff)
        .order_by(MarketData.date.asc())
    ).all()
    return _rows_to_price_series(final_rows)


def get_price_series_cached(
    symbol: str,
    period: str = "2y",
    force_refresh: bool = False,
    session: Optional[Session] = None,
) -> List[Dict]:
    if session is not None:
        return _get_price_series_cached_internal(session, symbol, period=period, force_refresh=force_refresh)

    with Session(engine) as local_session:
        return _get_price_series_cached_internal(local_session, symbol, period=period, force_refresh=force_refresh)


def _as_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _get_fundamentals_cached_internal(
    session: Session,
    symbol: str,
    max_age_hours: int = 24,
    force_refresh: bool = False,
) -> Dict:
    canon = _canonical_symbol(symbol)

    latest = session.exec(
        select(FundamentalsSnapshot)
        .where(FundamentalsSnapshot.symbol == canon)
        .order_by(FundamentalsSnapshot.as_of.desc())
    ).first()

    if latest and latest.payload and not force_refresh:
        age_hours = (datetime.utcnow() - latest.as_of).total_seconds() / 3600.0
        if age_hours <= max_age_hours:
            return latest.payload

    fresh = fetch_fundamentals(canon)
    if fresh:
        _ensure_asset_exists(session, canon)

        profile = fresh.get("profile", {}) if isinstance(fresh, dict) else {}
        valuation = fresh.get("valuation", {}) if isinstance(fresh, dict) else {}
        technicals = fresh.get("technicals", {}) if isinstance(fresh, dict) else {}

        now = datetime.utcnow()
        snapshot = FundamentalsSnapshot(
            symbol=canon,
            as_of=now,
            source=str(fresh.get("vendor", "yahoo")) if isinstance(fresh, dict) else "yahoo",
            asset_type=str(fresh.get("type", "UNKNOWN")) if isinstance(fresh, dict) else "UNKNOWN",
            sector=profile.get("sector") if isinstance(profile, dict) else None,
            industry=profile.get("industry") if isinstance(profile, dict) else None,
            currency=profile.get("currency") if isinstance(profile, dict) else None,
            market_cap=_as_float(valuation.get("market_cap") if isinstance(valuation, dict) else None),
            pe_ratio=_as_float(valuation.get("pe_ratio") if isinstance(valuation, dict) else None),
            ev_to_ebitda=_as_float(valuation.get("ev_to_ebitda") if isinstance(valuation, dict) else None),
            beta=_as_float(technicals.get("beta") if isinstance(technicals, dict) else None),
            payload=fresh,
        )
        session.add(snapshot)

        asset = session.get(Asset, canon)
        if asset:
            asset.name = profile.get("name", asset.name or canon)
            asset.asset_type = str(fresh.get("type", asset.asset_type)) if isinstance(fresh, dict) else asset.asset_type
            asset.exchange = profile.get("exchange", asset.exchange)
            asset.currency = profile.get("currency", asset.currency or "USD")
            asset.updated_at = now
            session.add(asset)

        session.commit()
        return fresh

    if latest and latest.payload:
        return latest.payload

    return {"type": "UNKNOWN", "profile": {"name": canon}}


def get_fundamentals_cached(
    symbol: str,
    max_age_hours: int = 24,
    force_refresh: bool = False,
    session: Optional[Session] = None,
) -> Dict:
    if session is not None:
        return _get_fundamentals_cached_internal(
            session,
            symbol,
            max_age_hours=max_age_hours,
            force_refresh=force_refresh,
        )

    with Session(engine) as local_session:
        return _get_fundamentals_cached_internal(
            local_session,
            symbol,
            max_age_hours=max_age_hours,
            force_refresh=force_refresh,
        )
