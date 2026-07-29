from typing import List, Optional
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON, UniqueConstraint

from app.utils.timeutil import UtcDateTime, utcnow

# Instants (created_at, evaluated_at, expires_at, ...) use UtcDateTime, so they
# come back from the database timezone-aware and serialise with an explicit UTC
# offset. Columns holding a calendar date instead of a moment — `date` on the
# market tables, data_last_date, the training-window bounds, purchase_date — stay
# naive on purpose: they are midnight-anchored days whose timezone is meaningless,
# and they are written from strptime() and fed to pandas, where mixing aware and
# naive values is its own bug. See app/utils/timeutil.py.


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    cognito_sub: Optional[str] = Field(default=None, index=True, unique=True)
    name: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class UserStoragePreference(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_userstoragepreference_user"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    store_portfolio_runs: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class Asset(SQLModel, table=True):
    """
    Canonical asset registry.
    """
    symbol: str = Field(primary_key=True)
    name: str = Field(default="")
    asset_type: str = Field(default="UNKNOWN", index=True)
    asset_class: str = Field(default="US_EQUITY", index=True)  # US_EQUITY | INTL_INDEX | ETF | BOND_ETF | COMMODITY | CRYPTO | INDEX
    exchange: Optional[str] = None
    currency: str = Field(default="USD")
    vendor: str = Field(default="yahoo")
    vendor_symbol: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class ForecastCache(SQLModel, table=True):
    """
    Stores forecast responses to avoid recomputation.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    run_date: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    horizon_days: int

    winner_model: str
    model_version: str = Field(default="v1")

    training_window_start: Optional[datetime] = None
    training_window_end: Optional[datetime] = None
    data_last_date: Optional[datetime] = None

    forecast_blob: dict = Field(sa_column=Column(JSON))

    final_predicted_price: float = Field(default=0.0)
    fragility_score: float = Field(default=0.0)
    var_95: float = Field(default=0.0)


class RiskSimulationCache(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "method",
            "input_hash",
            name="uq_risksimulationcache_key",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True)  # asset | portfolio
    entity_id: str = Field(index=True)    # ticker or portfolio id
    method: str = Field(index=True)       # e.g. quantum_vqmc
    horizon_days: int = Field(index=True)
    n_simulations: int = Field(default=0)
    random_seed: Optional[int] = Field(default=None, index=True)
    input_hash: str = Field(index=True)
    data_last_date: Optional[datetime] = Field(default=None, index=True)
    result_blob: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class PortfolioForecastCache(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "entity_type",
            "entity_id",
            "input_hash",
            name="uq_portfolioforecastcache_key",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_user_id: int = Field(foreign_key="user.id", index=True)
    entity_type: str = Field(index=True, default="portfolio")  # portfolio | portfolio_adhoc
    entity_id: str = Field(index=True)  # portfolio id or synthetic request id
    input_hash: str = Field(index=True)
    horizon_days: int = Field(index=True)
    data_last_date: Optional[datetime] = Field(default=None, index=True)
    request_payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    result_blob: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class ForecastJob(SQLModel, table=True):
    id: str = Field(primary_key=True)
    owner_user_id: int = Field(foreign_key="user.id", index=True)
    job_type: str = Field(index=True)  # portfolio_forecast
    entity_type: str = Field(index=True, default="portfolio")
    entity_id: str = Field(index=True)
    status: str = Field(index=True, default="queued")  # queued | running | completed | failed
    request_hash: str = Field(index=True)
    request_payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    progress: float = Field(default=0.0)
    error_message: Optional[str] = None
    result_cache_id: Optional[int] = Field(default=None, index=True)
    result_blob: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    started_at: Optional[datetime] = Field(default=None, index=True, sa_type=UtcDateTime)
    finished_at: Optional[datetime] = Field(default=None, index=True, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)


class AssetRiskCache(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "horizon_days",
            "n_paths",
            "method",
            "data_last_date",
            name="uq_assetriskcache_key",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(foreign_key="asset.symbol", index=True)
    method: str = Field(default="classical_r", index=True)
    horizon_days: int = Field(index=True)
    n_paths: int = Field(index=True)
    data_last_date: Optional[datetime] = Field(default=None, index=True)
    result_blob: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class AssetVolatilitySnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(foreign_key="asset.symbol", index=True)
    as_of: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    method: str = Field(default="classical_r", index=True)
    horizon_days: int = Field(index=True)
    n_paths: int = Field(index=True)
    data_last_date: Optional[datetime] = Field(default=None, index=True)
    sigma_latest: Optional[float] = Field(default=None, index=True)
    sigma_next: Optional[float] = Field(default=None, index=True)
    var_95_latest: Optional[float] = Field(default=None, index=True)
    fragility_score_latest: Optional[float] = Field(default=None, index=True)
    regime_latest: Optional[str] = Field(default=None, index=True)
    snapshot_blob: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)


class NewsCache(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "limit_count",
            "source",
            name="uq_newscache_symbol_limit_source",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(foreign_key="asset.symbol", index=True)
    source: str = Field(default="yahoo", index=True)
    limit_count: int = Field(default=10, index=True)
    items_blob: dict = Field(default_factory=dict, sa_column=Column(JSON))
    fetched_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    expires_at: Optional[datetime] = Field(default=None, index=True, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class MarketData(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_marketdata_symbol_date"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(foreign_key="asset.symbol", index=True)
    date: datetime = Field(index=True)
    open: float = Field(default=0.0)
    high: float = Field(default=0.0)
    low: float = Field(default=0.0)
    close: float = Field(default=0.0)
    volume: float = Field(default=0.0)
    source: str = Field(default="yahoo")
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class FundamentalsSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(foreign_key="asset.symbol", index=True)
    as_of: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    source: str = Field(default="yahoo")
    asset_type: str = Field(default="UNKNOWN", index=True)
    sector: Optional[str] = Field(default=None, index=True)
    industry: Optional[str] = None
    currency: Optional[str] = None
    market_cap: Optional[float] = Field(default=None, index=True)
    pe_ratio: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    beta: Optional[float] = None
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))

class Portfolio(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)

    positions: List["Position"] = Relationship(back_populates="portfolio")


class Position(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolio.id", index=True)
    ticker: str = Field(index=True)
    weight: float = Field(default=0.0)
    quantity: float = Field(default=0.0)
    cost_basis: float = Field(default=0.0)
    purchase_date: Optional[datetime] = Field(default=None)
    asset_type: str = Field(default="EQUITY")

    portfolio: Optional[Portfolio] = Relationship(back_populates="positions")


class Watchlist(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)

    items: List["WatchlistItem"] = Relationship(back_populates="watchlist")


class WatchlistItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    watchlist_id: int = Field(foreign_key="watchlist.id", index=True)
    ticker: str = Field(index=True)
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)

    watchlist: Optional[Watchlist] = Relationship(back_populates="items")


class AlertRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str
    ticker: str = Field(index=True)
    watchlist_id: Optional[int] = Field(default=None, foreign_key="watchlist.id", index=True)
    alert_type: str = Field(default="price_threshold", index=True)  # price_threshold | anomaly | forecast_divergence
    direction: str = Field(default="above")  # above | below
    threshold_value: float = Field(default=0.0)
    lookback_days: int = Field(default=30)
    is_active: bool = Field(default=True, index=True)
    extra_config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class AlertEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    alert_id: Optional[int] = Field(default=None, foreign_key="alertrule.id", index=True)
    ticker: str = Field(index=True)
    alert_type: str = Field(index=True)
    triggered: bool = Field(default=False, index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    evaluated_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)


class AlertFeedback(SQLModel, table=True):
    """One user's verdict on one alert event: was it worth sending?

    Two jobs. Immediately it drives per-user notification muting, which is the
    defence against alert fatigue. Over time it accumulates labels — an alert
    marked unhelpful during a calm stretch is a false positive, one marked
    helpful around a real move is a true positive — which is the labeled data a
    detector catalog otherwise needs hand-curating.
    """
    __table_args__ = (
        UniqueConstraint("alert_event_id", "user_id",
                         name="uq_alertfeedback_event_user"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    alert_event_id: int = Field(foreign_key="alertevent.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    # "useful" | "not_useful"
    rating: str = Field(index=True)
    reason: Optional[str] = Field(default=None)
    # Denormalised so muting and label export do not need a join back through
    # AlertEvent -> AlertRule for every row.
    ticker: str = Field(default="", index=True)
    alert_kind: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)


class UserAlertPreference(SQLModel, table=True):
    """Per-user notification behaviour. One row per user, created on demand."""
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_useralertpreference_user"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    email_enabled: bool = Field(default=True)
    # INFO | ALERT | WARNING | ANOMALY — anything below this is stored but not emailed.
    min_severity: str = Field(default="ALERT")
    # Local quiet hours, inclusive start / exclusive end, 0-23. Equal values = no quiet period.
    quiet_hours_start: int = Field(default=0)
    quiet_hours_end: int = Field(default=0)
    quiet_hours_tz_offset_min: int = Field(default=0)
    # Explicit mutes plus the auto-mutes earned by repeated "not useful" marks.
    muted_tickers: list = Field(default_factory=list, sa_column=Column(JSON))
    muted_kinds: list = Field(default_factory=list, sa_column=Column(JSON))
    # Consecutive "not_useful" marks on a (ticker, kind) before it auto-mutes.
    # 0 disables auto-muting.
    auto_mute_after: int = Field(default=3)
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class SavedScreen(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str
    description: Optional[str] = None
    filters: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class ScenarioSession(SQLModel, table=True):
    """A saved Scenario Builder session: the scenario set plus the results it
    produced, so a user can reload a full session after logging back in (even
    on another device)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str
    portfolio_id: Optional[str] = Field(default=None)
    portfolio_value: Optional[float] = Field(default=None)
    scenarios: dict = Field(default_factory=dict, sa_column=Column(JSON))  # {items: [...]}
    results: dict = Field(default_factory=dict, sa_column=Column(JSON))    # fans, dates, comparison
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class IntraDayQuote(SQLModel, table=True):
    """One row per symbol, upserted on morning refresh."""
    symbol: str = Field(primary_key=True, foreign_key="asset.symbol")
    last_price: float = Field(default=0.0)
    change_pct: float = Field(default=0.0)
    as_of: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    source: str = Field(default="yahoo")
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class BenchmarkReturn(SQLModel, table=True):
    """Pre-computed returns replacing np.random in reports."""
    __table_args__ = (
        UniqueConstraint("benchmark_symbol", "date", "period", name="uq_benchmarkreturn_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    benchmark_symbol: str = Field(index=True)
    date: datetime = Field(index=True)
    period: str = Field(default="daily", index=True)  # daily | monthly
    return_pct: float = Field(default=0.0)
    cumulative_return: float = Field(default=0.0)

    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class PortfolioReportDataCache(SQLModel, table=True):
    """Pre-computed portfolio data blob for instant report/UI serving."""
    __table_args__ = (
        UniqueConstraint("portfolio_id", "input_hash", name="uq_portfolioreportdatacache_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolio.id", index=True)
    input_hash: str = Field(index=True)
    horizon_days: int = Field(default=90, index=True)
    data_last_date: Optional[datetime] = Field(default=None, index=True)
    result_blob: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class AssetReturn(SQLModel, table=True):
    """Pre-computed per-asset returns for contribution analysis."""
    __table_args__ = (
        UniqueConstraint("symbol", "date", "period", name="uq_assetreturn_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(foreign_key="asset.symbol", index=True)
    date: datetime = Field(index=True)
    period: str = Field(default="daily", index=True)  # daily | monthly
    return_pct: float = Field(default=0.0)

    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class RegimeThreshold(SQLModel, table=True):
    """Per-asset-class regime classification thresholds.

    The runtime regime classifier reads the *latest active row per
    asset_class*. Calibration jobs insert new rows and deactivate the
    previous active row for the same class — preserving history.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_class: str = Field(index=True)
    high: float = Field(default=1.50)
    low: float = Field(default=0.80)
    is_active: bool = Field(default=True, index=True)
    source: str = Field(default="default-seed")
    years_of_history: Optional[int] = Field(default=None)
    calibrated_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)


class AgentRun(SQLModel, table=True):
    """Log of every LLM agent invocation: prompt hash, output, usage, latency."""
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_name: str = Field(index=True)
    model: str = Field(index=True)
    input_hash: str = Field(index=True)
    output: str = Field(default="")
    prompt_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    latency_ms: int = Field(default=0)
    status: str = Field(default="ok", index=True)  # ok | error
    error: Optional[str] = Field(default=None)
    extra: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=UtcDateTime)
