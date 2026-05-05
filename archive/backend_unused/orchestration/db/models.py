# services/forecasting_service_py/app/db/models.py

from typing import List, Optional
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship, JSON, Column
from sqlalchemy import UniqueConstraint

# ----------------------------------------------------------------
# 1. USER & PORTFOLIO MANAGEMENT
# ----------------------------------------------------------------

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    portfolios: List["Portfolio"] = Relationship(back_populates="user")

class Portfolio(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    user_id: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: User = Relationship(back_populates="portfolios")
    positions: List["Position"] = Relationship(back_populates="portfolio")

class Position(SQLModel, table=True):
    """
    Represents a single holding in a portfolio.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolio.id")
    ticker: str = Field(index=True)
    quantity: float
    cost_basis: float = Field(default=0.0)
    asset_type: str = Field(default="EQUITY") # EQUITY, ETF, BOND
    
    portfolio: Portfolio = Relationship(back_populates="positions")

# ----------------------------------------------------------------
# 2. MARKET DATA (The Quant Engine)
# ----------------------------------------------------------------

class Asset(SQLModel, table=True):
    """
    Master table for all supported tickers.
    """
    ticker: str = Field(primary_key=True)
    name: str
    asset_class: str = Field(index=True) # EQUITY, ETF, BOND, CRYPTO
    exchange: Optional[str] = None
    currency: str = Field(default="USD")
    
    fundamentals: Optional["Fundamentals"] = Relationship(back_populates="asset")

class MarketData(SQLModel, table=True):
    """
    Time-Series Data. In production, this should be a Hypertable (TimescaleDB).
    Stores daily OHLCV data.
    """
    __table_args__ = (UniqueConstraint("ticker", "date", name="unique_ticker_date"),)
    
    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(foreign_key="asset.ticker", index=True)
    date: datetime = Field(index=True)
    
    open: float
    high: float
    low: float
    close: float
    volume: float
    adjusted_close: Optional[float] = None

class Fundamentals(SQLModel, table=True):
    """
    The 'Polymorphic' Table.
    Stores different metrics depending on asset_class, using nullable columns
    or JSON for specific deep data.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(foreign_key="asset.ticker", unique=True, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # -- COMMON --
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    beta: Optional[float] = None
    
    # -- EQUITY SPECIFIC --
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    dividend_yield: Optional[float] = None
    price_to_book: Optional[float] = None
    
    # -- ETF SPECIFIC --
    expense_ratio: Optional[float] = None
    nav_price: Optional[float] = None
    net_assets: Optional[float] = None
    
    # -- BOND SPECIFIC --
    yield_to_maturity: Optional[float] = None
    coupon_rate: Optional[float] = None
    maturity_date: Optional[datetime] = None
    
    # -- JSON EXTRAS (Holdings, Analyst Ratings) --
    # This stores the nested lists like "top_holdings" or "analyst_breakdown"
    extra_data: dict = Field(default={}, sa_column=Column(JSON))
    
    asset: Asset = Relationship(back_populates="fundamentals")

# ----------------------------------------------------------------
# 3. FORECAST CACHING
# ----------------------------------------------------------------

class ForecastCache(SQLModel, table=True):
    """
    Stores the result of the expensive HybridForecaster.
    Prevents re-running Quantum/LSTM logic if the data hasn't changed.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    run_date: datetime = Field(default_factory=datetime.utcnow, index=True)
    horizon_days: int
    
    # The Model used (e.g., "arima", "lstm")
    winner_model: str
    
    # We store the massive JSON response directly
    forecast_blob: dict = Field(sa_column=Column(JSON))
    
    # Quick access metrics for sorting/filtering
    final_predicted_price: float
    fragility_score: float
    var_95: float