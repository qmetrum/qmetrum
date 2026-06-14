# services/forecasting_service_py/app/main.py

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
import pandas as pd
import os
import json
import hashlib
import uuid
from datetime import datetime, timedelta
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from sqlmodel import Session, select
from sqlalchemy import func, update

# --- LOGIC IMPORTS ---
from app.logic.forecasting_logic import HybridForecaster
from app.logic.quantum_iae_risk import estimate_var_cvar_iae
from app.logic.quantum_vqmc_trained import simulate_trained_vqmc, train_ansatz as train_vqmc_ansatz
from app.logic.quantum_portfolio_opt import optimise_portfolio as quantum_optimise_portfolio
from app.logic.quantum_kernel import quantum_regime_classify
from app.logic.quantum_entropy import systemic_risk_report
from app.logic.tensor_network_risk import tensor_network_risk
from app.logic.quantum_reservoir import fit_forecast_qrc, auto_tune_qrc, QRCConfig
from app.logic.qrc_cache import retune_and_save as qrc_retune_and_save, list_cached_tickers as qrc_list_cached_tickers, load_cached_config as qrc_load_cached_config
from app.bench.quantum_bench import run_full_benchmark, list_benchmark_runs, get_benchmark_run
from app.logic.portfolio_logic import PortfolioManager
from app.logic.var_backtest_runner import (
    run_portfolio_var_backtest,
    run_portfolio_var_backtest_comparison,
    effective_weight_mode,
)
# Updated Imports (News + Database)
from app.utils.data_fetcher import fetch_news
from app.services.market_store import get_price_series_cached, get_fundamentals_cached
from app.services.risk_client import calculate_risk, ping_risk_service
from app.services.runtime_hardening import check_ml_runtime
from app.db.database import init_db, engine
from app.db.models import (
    Portfolio,
    Position,
    Asset,
    ForecastCache,
    PortfolioForecastCache,
    ForecastJob,
    AssetRiskCache,
    AssetVolatilitySnapshot,
    NewsCache,
    RiskSimulationCache,
    Watchlist,
    WatchlistItem,
    AlertRule,
    AlertEvent,
    SavedScreen,
    User,
    UserStoragePreference,
    MarketData,
    PortfolioReportDataCache,
)
from app.vendors import get_vendor

from app.reports.report_router import report_router
from app.agents.agents_router import agents_router
from app.auth import CognitoAuthMiddleware, auth_router
from app.auth.cognito import is_cognito_configured

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Qsight API")
# Cognito auth: validates Bearer tokens and rewrites X-User-Id from claims.
# No-op when COGNITO_USER_POOL_ID is not set (local dev). Mount before any
# router so it runs on every request.
app.add_middleware(CognitoAuthMiddleware)
app.include_router(report_router, prefix="/reports", tags=["Reports"])
app.include_router(agents_router, prefix="/agents", tags=["Agents"])
app.include_router(auth_router, prefix="/auth", tags=["Auth"])


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str) -> List[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


# Shared config
RISK_SERVICE_URL = os.getenv("RISK_SERVICE_URL", "http://127.0.0.1:8001")
VENDOR = get_vendor()
RISK_SERVICE_REQUIRED = _env_flag("RISK_SERVICE_REQUIRED", False)
ML_RUNTIME_STRICT = _env_flag("ML_RUNTIME_STRICT", False)
ALERT_SCHEDULER_ENABLED = _env_flag("ALERT_SCHEDULER_ENABLED", True)
ALERT_SCHEDULER_INTERVAL_SECONDS = int(os.getenv("ALERT_SCHEDULER_INTERVAL_SECONDS", "300"))
ALERT_EVENT_COOLDOWN_SECONDS = int(os.getenv("ALERT_EVENT_COOLDOWN_SECONDS", "900"))
DEFAULT_USER_ID = int(os.getenv("DEFAULT_USER_ID", "1"))
FORECAST_JOB_MAX_WORKERS = max(1, int(os.getenv("FORECAST_JOB_MAX_WORKERS", "2")))
FORECAST_JOB_DISPATCH_MODE = os.getenv("FORECAST_JOB_DISPATCH_MODE", "threadpool").strip().lower()
FORECAST_JOB_WORKER_POLL_SECONDS = float(os.getenv("FORECAST_JOB_WORKER_POLL_SECONDS", "1.0"))
ASSET_RISK_CACHE_MAX_AGE_MINUTES = int(os.getenv("ASSET_RISK_CACHE_MAX_AGE_MINUTES", "60"))
NEWS_CACHE_MAX_AGE_MINUTES = int(os.getenv("NEWS_CACHE_MAX_AGE_MINUTES", "30"))
PORTFOLIO_STORAGE_DEFAULT_ENABLED = _env_flag("PORTFOLIO_STORAGE_DEFAULT_ENABLED", True)
CORS_ALLOW_ORIGINS = _env_csv(
    "CORS_ALLOW_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
)
# Default regex allows Next dev on localhost/127.0.0.1/[::1] on any port (3000, 3001, etc.)
CORS_ALLOW_ORIGIN_REGEX = os.getenv(
    "CORS_ALLOW_ORIGIN_REGEX",
    r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$",
)
# Local dev default: allow all origins unless explicitly disabled.
CORS_ALLOW_ALL = _env_flag("CORS_ALLOW_ALL", True)

_alert_scheduler_thread = None
_alert_scheduler_stop = threading.Event()
_forecast_job_executor = ThreadPoolExecutor(max_workers=FORECAST_JOB_MAX_WORKERS, thread_name_prefix="portfolio-forecast")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if CORS_ALLOW_ALL else CORS_ALLOW_ORIGINS,
    allow_origin_regex=None if CORS_ALLOW_ALL else CORS_ALLOW_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


from fastapi import Request
from fastapi.responses import JSONResponse


@app.exception_handler(HTTPException)
async def _log_http_exception(request: Request, exc: HTTPException):
    if exc.status_code >= 400:
        logger.warning(
            "HTTP %s on %s %s -> %s",
            exc.status_code, request.method, request.url.path, exc.detail,
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# --- LIFECYCLE EVENTS ---
@app.on_event("startup")
def on_startup():
    """Initialize the Database on Server Startup"""
    init_db()
    _ensure_default_user()
    logger.info(
        "CORS configured: allow_all=%s origins=%s origin_regex=%s",
        CORS_ALLOW_ALL,
        "*" if CORS_ALLOW_ALL else CORS_ALLOW_ORIGINS,
        None if CORS_ALLOW_ALL else CORS_ALLOW_ORIGIN_REGEX,
    )
    logger.info("Forecast job dispatch mode: %s", FORECAST_JOB_DISPATCH_MODE)
    runtime_report = check_ml_runtime(refresh=True)
    app.state.runtime_report = runtime_report
    if not runtime_report.get("ok", False):
        message = runtime_report.get("message", "ML runtime compatibility check failed.")
        if ML_RUNTIME_STRICT:
            raise RuntimeError(message)
        logger.warning(message)

    risk_report = ping_risk_service()
    app.state.risk_service_report = risk_report
    if not risk_report.get("ok", False):
        message = risk_report.get("message", f"Risk service unavailable at {RISK_SERVICE_URL}")
        if RISK_SERVICE_REQUIRED:
            raise RuntimeError(message)
        logger.warning(message)

    _start_alert_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    _stop_alert_scheduler()
    try:
        _forecast_job_executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass

# --- DATA MODELS ---

class StockDataPoint(BaseModel):
    date: str
    price: float

class ScenarioInput(BaseModel):
    name: str
    initial_shock_pct: float = 0.0
    return_scale: float = 1.0
    drift_shift: float = 0.0

class ForecastRequest(BaseModel):
    ticker: str
    history: Optional[List[StockDataPoint]] = None
    horizon_days: int = 90
    scenarios: Optional[List[ScenarioInput]] = None

class AssetForecastRequest(BaseModel):
    horizon_days: int = 90
    scenarios: Optional[List[ScenarioInput]] = None

class QuantumRiskRequest(BaseModel):
    ticker: str
    prices: List[float]
    n_simulations: int = 5000
    horizon_days: int = 30
    random_seed: Optional[int] = None
    # Quantum method: "vqmc" (default, Variational QMC) or "iae" (Iterative Amplitude Estimation)
    method: str = "vqmc"
    # IAE-specific parameters (ignored when method="vqmc")
    confidence: float = 0.95
    num_uncertainty_qubits: int = 5
    epsilon_target: float = 0.005
    bisection_iters: int = 12

class PortfolioRequest(BaseModel):
    assets: Optional[List[dict]] = None # [{"ticker": "AAPL", "weight": 0.5}, ...]
    horizon_days: int = 90
    scenarios: Optional[List[ScenarioInput]] = None
    target_weights: Optional[Dict[str, float]] = None


class PortfolioQuantumRiskRequest(BaseModel):
    assets: Optional[List[dict]] = None
    horizon_days: int = 30
    n_simulations: int = 5000
    random_seed: Optional[int] = None


class PortfolioQuantumRebalanceRequest(BaseModel):
    assets: Optional[List[dict]] = None
    budget: Optional[int] = None       # Number of assets to select; defaults to ceil(N/2)
    risk_factor: float = 0.5           # q in mean-variance objective; 0=pure return, 1=pure risk
    qaoa_reps: int = 3                 # QAOA depth (p)
    cvar_alpha: float = 0.25           # CVaR tail fraction for aggregation
    random_seed: Optional[int] = None


class PortfolioQuantumRegimeRequest(BaseModel):
    assets: Optional[List[dict]] = None
    n_qubits: int = 4
    feature_map_reps: int = 2
    train_points: int = 200


class PortfolioTensorNetworkRiskRequest(BaseModel):
    assets: Optional[List[dict]] = None
    horizon_days: int = 30
    n_simulations: int = 2000
    physical_dim: int = 4
    bond_dim: int = 8
    random_seed: Optional[int] = None


class VarBacktestRequest(BaseModel):
    assets: Optional[List[dict]] = None
    confidence: float = 0.95
    horizon_days: int = 1
    est_window: int = 252
    n_backtest: int = 250
    method: str = "mps_fan"        # "mps_fan" | "historical" | "parametric"
    n_simulations: int = 500
    random_seed: Optional[int] = 42
    weight_mode: str = "constant"  # "constant" | "drift" (drift needs share quantities)


class VarBacktestCompareRequest(BaseModel):
    assets: Optional[List[dict]] = None
    confidence: float = 0.95
    horizon_days: int = 1
    est_window: int = 252
    n_backtest: int = 120          # lighter default: several methods run per request
    n_simulations: int = 400
    random_seed: Optional[int] = 42
    weight_mode: str = "constant"  # "constant" | "drift"


class QuantumBenchmarkRequest(BaseModel):
    universe: Optional[List[str]] = None
    save: bool = True


class QuantumReservoirForecastRequest(BaseModel):
    ticker: str
    prices: List[float]
    horizon_days: int = 30
    auto_tune: bool = True
    # Optional manual override when auto_tune=False
    n_qubits: Optional[int] = None
    reservoir_depth: Optional[int] = None
    input_scale: Optional[float] = None
    ridge_alpha: Optional[float] = None
    leak_rate: Optional[float] = None
    washout_steps: Optional[int] = None


class QRCRetuneRequest(BaseModel):
    tickers: List[str]                   # tickers to re-tune; prices fetched from market cache
    period: str = "2y"                   # history window for tuning

class PortfolioUpsertRequest(BaseModel):
    name: Optional[str] = None
    assets: List[dict]

class UserCreateRequest(BaseModel):
    email: str


class UserStoragePreferenceRequest(BaseModel):
    store_portfolio_runs: bool = True


class WatchlistRequest(BaseModel):
    name: str
    tickers: List[str]


class WatchlistUpdateRequest(BaseModel):
    name: Optional[str] = None
    tickers: Optional[List[str]] = None


class AlertRequest(BaseModel):
    name: str
    ticker: str
    alert_type: str = "price_threshold"
    direction: str = "above"
    threshold_value: float = 0.0
    lookback_days: int = 30
    watchlist_id: Optional[int] = None
    extra_config: Optional[Dict] = None
    is_active: bool = True


class AlertUpdateRequest(BaseModel):
    name: Optional[str] = None
    direction: Optional[str] = None
    threshold_value: Optional[float] = None
    lookback_days: Optional[int] = None
    is_active: Optional[bool] = None
    extra_config: Optional[Dict] = None


class ScreenerRunRequest(BaseModel):
    symbols: List[str]
    filters: Optional[Dict] = None
    limit: int = 100


class SavedScreenRequest(BaseModel):
    name: str
    description: Optional[str] = None
    filters: Dict

# --- ENDPOINTS ---

@app.get("/")
def health_check():
    return {"status": "active", "module": "Qsight API"}


@app.get("/healthz")
def healthz():
    """Liveness probe. Cheap by design — returns 200 if the process is alive.

    Use this for App Runner / load-balancer health checks. For deeper
    runtime/dependency checks (ML runtime, risk service ping, etc.) hit
    /health or /health/ready.
    """
    return {"status": "ok"}


@app.get("/health")
def service_health(refresh: bool = True):
    runtime_report = check_ml_runtime(refresh=True) if refresh else getattr(app.state, "runtime_report", None)
    risk_report = ping_risk_service() if refresh else getattr(app.state, "risk_service_report", None)
    healthy = bool(runtime_report and runtime_report.get("ok", False))
    if RISK_SERVICE_REQUIRED:
        healthy = healthy and bool(risk_report and risk_report.get("ok", False))
    return {
        "status": "healthy" if healthy else "degraded",
        "runtime": runtime_report,
        "risk_service": risk_report,
    }


@app.get("/health/ready")
def readiness_check():
    payload = service_health(refresh=True)
    if payload["status"] != "healthy":
        raise HTTPException(status_code=503, detail=payload)
    return payload

# -------------------------------------------------------------------
# Canonical Asset Helpers
# -------------------------------------------------------------------

def _canonical_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _ensure_default_user() -> None:
    with Session(engine) as session:
        existing = session.get(User, DEFAULT_USER_ID)
        if existing:
            return
        now = datetime.utcnow()
        email = "local@qmetrum.dev" if DEFAULT_USER_ID == 1 else f"local+{DEFAULT_USER_ID}@qmetrum.dev"
        session.add(
            User(
                id=DEFAULT_USER_ID,
                email=email,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _resolve_user_id(user_id: Optional[int], x_user_id: Optional[int]) -> int:
    # In production (Cognito configured), the only trusted source of identity
    # is the X-User-Id header that CognitoAuthMiddleware injected from a
    # verified JWT claim. The ?user_id= query param and DEFAULT_USER_ID
    # fallback are legacy diagnostic paths that would let anyone impersonate
    # any user, so we refuse them and 401 instead.
    if is_cognito_configured():
        if x_user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        return int(x_user_id)
    # Local dev (no Cognito env vars): keep the legacy resolution order so
    # `python main.py` + curl with X-User-Id, ?user_id=, or no creds still works.
    if user_id is not None:
        return int(user_id)
    if x_user_id is not None:
        return int(x_user_id)
    return DEFAULT_USER_ID


def _require_user(session: Session, user_id: Optional[int], x_user_id: Optional[int]) -> User:
    resolved = _resolve_user_id(user_id, x_user_id)
    user = session.get(User, resolved)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found or inactive")
    return user


def _get_user_storage_preference(session: Session, user_id: int) -> dict:
    row = session.exec(
        select(UserStoragePreference).where(UserStoragePreference.user_id == int(user_id))
    ).first()
    if row:
        return {
            "store_portfolio_runs": bool(row.store_portfolio_runs),
            "source": "user",
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
    return {
        "store_portfolio_runs": bool(PORTFOLIO_STORAGE_DEFAULT_ENABLED),
        "source": "default",
        "updated_at": None,
    }


def _set_user_storage_preference(session: Session, user_id: int, *, store_portfolio_runs: bool) -> UserStoragePreference:
    now = datetime.utcnow()
    row = session.exec(
        select(UserStoragePreference).where(UserStoragePreference.user_id == int(user_id))
    ).first()
    if row:
        row.store_portfolio_runs = bool(store_portfolio_runs)
        row.updated_at = now
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    row = UserStoragePreference(
        user_id=int(user_id),
        store_portfolio_runs=bool(store_portfolio_runs),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _portfolio_storage_enabled_for_user(session: Session, user_id: int) -> bool:
    preference = _get_user_storage_preference(session, int(user_id))
    return bool(preference.get("store_portfolio_runs", PORTFOLIO_STORAGE_DEFAULT_ENABLED))


def _ensure_asset(session: Session, symbol: str, fundamentals: Optional[dict] = None) -> Asset:
    canon = _canonical_symbol(symbol)
    asset = session.get(Asset, canon)
    now = datetime.utcnow()

    if not asset:
        asset = Asset(
            symbol=canon,
            name=canon,
            asset_type="UNKNOWN",
            currency="USD",
            vendor=VENDOR.name,
            vendor_symbol=canon,
            created_at=now,
            updated_at=now
        )
        session.add(asset)

    if fundamentals:
        profile = fundamentals.get("profile", {}) if isinstance(fundamentals, dict) else {}
        asset.name = profile.get("name", asset.name or canon)
        asset.asset_type = fundamentals.get("type", asset.asset_type) if isinstance(fundamentals, dict) else asset.asset_type
        asset.exchange = profile.get("exchange", asset.exchange)
        asset.currency = profile.get("currency", asset.currency or "USD")

    asset.updated_at = now
    session.commit()
    session.refresh(asset)
    return asset


def _scenario_to_dicts(scenarios: Optional[List[ScenarioInput]]) -> Optional[List[dict]]:
    if not scenarios:
        return None
    return [s.dict() for s in scenarios]


def _stable_json_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    return str(value)


def _json_compatible(payload: Any):
    return json.loads(json.dumps(payload, default=_json_default))


def _portfolio_latest_market_dates(session: Session, tickers: List[str]) -> Dict[str, Optional[str]]:
    if not tickers:
        return {}
    rows = session.exec(
        select(MarketData.symbol, func.max(MarketData.date))
        .where(MarketData.symbol.in_(tickers))
        .group_by(MarketData.symbol)
    ).all()
    latest = {str(symbol): (dt.isoformat() if dt else None) for symbol, dt in rows}
    for ticker in tickers:
        latest.setdefault(ticker, None)
    return latest


def _portfolio_forecast_input_hash(
    *,
    entity_type: str,
    entity_id: str,
    assets: List[dict],
    horizon_days: int,
    scenarios: Optional[List[dict]],
    target_weights: Optional[Dict[str, float]],
    latest_market_dates: Dict[str, Optional[str]],
) -> str:
    payload = {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "assets": assets,
        "horizon_days": int(horizon_days),
        "scenarios": scenarios or [],
        "target_weights": target_weights or {},
        "latest_market_dates": latest_market_dates,
    }
    return _stable_json_hash(payload)


def _portfolio_forecast_cache_read(
    session: Session,
    *,
    owner_user_id: int,
    entity_type: str,
    entity_id: str,
    input_hash: str,
) -> Optional[dict]:
    cached = session.exec(
        select(PortfolioForecastCache)
        .where(PortfolioForecastCache.owner_user_id == owner_user_id)
        .where(PortfolioForecastCache.entity_type == entity_type)
        .where(PortfolioForecastCache.entity_id == str(entity_id))
        .where(PortfolioForecastCache.input_hash == input_hash)
        .order_by(PortfolioForecastCache.updated_at.desc())
    ).first()
    if not cached or not cached.result_blob:
        return None
    result = copy.deepcopy(cached.result_blob)
    result.setdefault("cache", {})
    result["cache"].update(
        {
            "hit": True,
            "cache_type": "portfolio_forecast",
            "cache_id": cached.id,
            "created_at": cached.created_at.isoformat() if cached.created_at else None,
            "updated_at": cached.updated_at.isoformat() if cached.updated_at else None,
            "persisted": True,
        }
    )
    return {
        "cache_row": cached,
        "result": result,
    }


def _portfolio_forecast_cache_write(
    session: Session,
    *,
    owner_user_id: int,
    entity_type: str,
    entity_id: str,
    horizon_days: int,
    input_hash: str,
    data_last_date: Optional[datetime],
    request_payload: dict,
    result_blob: dict,
) -> PortfolioForecastCache:
    now = datetime.utcnow()
    existing = session.exec(
        select(PortfolioForecastCache)
        .where(PortfolioForecastCache.owner_user_id == owner_user_id)
        .where(PortfolioForecastCache.entity_type == entity_type)
        .where(PortfolioForecastCache.entity_id == str(entity_id))
        .where(PortfolioForecastCache.input_hash == input_hash)
    ).first()
    if existing:
        existing.horizon_days = int(horizon_days)
        existing.data_last_date = data_last_date
        existing.request_payload = request_payload
        existing.result_blob = result_blob
        existing.updated_at = now
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    row = PortfolioForecastCache(
        owner_user_id=int(owner_user_id),
        entity_type=entity_type,
        entity_id=str(entity_id),
        input_hash=input_hash,
        horizon_days=int(horizon_days),
        data_last_date=data_last_date,
        request_payload=request_payload,
        result_blob=result_blob,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _forecast_job_to_dict(job: ForecastJob) -> dict:
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "entity_type": job.entity_type,
        "entity_id": job.entity_id,
        "status": job.status,
        "progress": float(job.progress or 0.0),
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "result_cache_id": job.result_cache_id,
    }


def _portfolio_forecast_result_with_cache_meta(
    result_blob: dict,
    cache_row: Optional[PortfolioForecastCache],
    *,
    persisted: Optional[bool] = None,
) -> dict:
    result = copy.deepcopy(result_blob or {})
    persisted_flag = bool(cache_row) if persisted is None else bool(persisted)
    result.setdefault("cache", {})
    result["cache"].update(
        {
            "hit": bool(cache_row),
            "cache_type": "portfolio_forecast",
            "cache_id": cache_row.id if cache_row else None,
            "created_at": cache_row.created_at.isoformat() if cache_row and cache_row.created_at else None,
            "updated_at": cache_row.updated_at.isoformat() if cache_row and cache_row.updated_at else None,
            "persisted": persisted_flag,
        }
    )
    return result


def _adapt_nightly_blob_to_ui(blob: dict, portfolio_id: int) -> dict:
    """
    Transform the nightly batch's PortfolioReportDataCache blob into the
    PortfolioManager.analyze_portfolio() format that the UI expects.
    """
    fc = blob.get("forecast_result", {})
    rm = blob.get("risk_metrics", {})
    risk_data = blob.get("risk_data", {})
    qmc = blob.get("qmc_result", {})
    perf = blob.get("performance", {}) or fc.get("performance_metrics", {})
    weights = blob.get("weights", {})
    tickers = blob.get("tickers", [])
    fundamentals = blob.get("fundamentals", {})

    # Build forecast prices from forecast_result
    forecast_prices = fc.get("forecast_prices", blob.get("portfolio_prices", [])[-90:])
    forecast_dates = fc.get("forecast_dates", [])
    if not forecast_dates and forecast_prices:
        from datetime import datetime as dt, timedelta
        base = dt.utcnow()
        forecast_dates = [(base + timedelta(days=i+1)).strftime("%Y-%m-%d") for i in range(len(forecast_prices))]

    # Confidence intervals — try multiple key formats
    ci_lower = (
        fc.get("lower_ci", [])
        or fc.get("forecast_confidence_interval", {}).get("lower", [])
    )
    ci_upper = (
        fc.get("upper_ci", [])
        or fc.get("forecast_confidence_interval", {}).get("upper", [])
    )
    # Fallback: monte_carlo_cone within forecast_result
    if not ci_lower:
        mc_cone = fc.get("monte_carlo_cone", {})
        ci_lower = mc_cone.get("lower_bound", mc_cone.get("lower", []))
        ci_upper = mc_cone.get("upper_bound", mc_cone.get("upper", []))

    # Build holdings from asset_forecasts (prices stored by nightly batch)
    holdings = []
    asset_forecasts = blob.get("asset_forecasts", {})
    stored_prices = blob.get("latest_prices", {})
    for ticker in tickers:
        af = asset_forecasts.get(ticker, {})
        af_prices = af.get("forecast_prices", [])
        hist_prices = af.get("history_prices", [])
        current_price = stored_prices.get(ticker, 0) or (hist_prices[-1] if hist_prices else 0)
        forecast_return = (af_prices[-1] / current_price - 1) if af_prices and current_price else 0
        holdings.append({
            "ticker": ticker,
            "weight": weights.get(ticker, 0),
            "current_price": current_price,
            "forecast_return": forecast_return,
            "forecast_horizon_days": 90,
            "fundamentals": fundamentals.get(ticker, {}),
            "risk_metrics": af.get("risk_metrics", {}),
        })

    result = {
        "portfolio_id": portfolio_id,
        "portfolio_summary": {
            "forecast_prices": forecast_prices,
            "forecast_dates": forecast_dates,
            "risk_metrics": {
                "var_95": rm.get("var_95_daily", -0.02),
                "cvar_95": rm.get("cvar_95_daily", -0.03),
                "sharpe_ratio": rm.get("sharpe_ratio", 0),
                "sortino_ratio": rm.get("sortino_ratio", 0),
                "max_drawdown": rm.get("max_drawdown", 0),
                "annualized_volatility": rm.get("annualized_vol", 0),
                "beta": rm.get("beta", 1.0),
                "fragility_score": rm.get("fragility_score", 1.0),
                "regime": rm.get("regime", "Normal"),
            },
            "monte_carlo_cone": {
                "lower_bound": ci_lower,
                "median_path": forecast_prices,
                "upper_bound": ci_upper,
            },
            "drawdown_series": (blob.get("portfolio_summary_extras") or {}).get("drawdown_series") or fc.get("drawdown_series"),
            "monthly_returns": (blob.get("portfolio_summary_extras") or {}).get("monthly_returns") or fc.get("monthly_returns"),
            "upper_ci": (blob.get("portfolio_summary_extras") or {}).get("upper_ci"),
            "lower_ci": (blob.get("portfolio_summary_extras") or {}).get("lower_ci"),
            "indicators": fc.get("indicators", {}),
            "volatility": fc.get("volatility", {}),
            "performance_metrics": perf,
            "forecast_horizon_days": 90,
            "regime": {
                "current": rm.get("regime", "Normal"),
                "vol_ratio": rm.get("fragility_score", 1.0),
                "recent_vol": rm.get("annualized_vol", 0),
                "long_vol": rm.get("annualized_vol", 0),
            },
            "sector_exposure": {},
            "scenarios": (blob.get("portfolio_summary_extras") or {}).get("scenarios") or {},
            "scenarios_legacy": (blob.get("portfolio_summary_extras") or {}).get("scenarios_legacy") or {},
        },
        "stress_tests": [],
        "rebalancing": {"target": "current", "estimated_turnover": 0, "suggestions": []},
        "holdings": holdings,
        "cache": {"hit": True, "cache_type": "nightly_batch", "persisted": True},
        # Pass through raw data for frontend charts
        "portfolio_prices": blob.get("portfolio_prices", []),
        "dates": blob.get("dates", []),
        "risk_data": risk_data,
    }
    return result


def _compute_portfolio_forecast_result(
    *,
    portfolio_id: Optional[int],
    assets: List[dict],
    horizon_days: int,
    scenarios: Optional[List[dict]],
    target_weights: Optional[Dict[str, float]],
) -> dict:
    manager = PortfolioManager(assets)
    result = manager.analyze_portfolio(
        horizon_days=int(horizon_days),
        scenarios=scenarios,
        target_weights=target_weights,
    )
    if portfolio_id is not None:
        result["portfolio_id"] = int(portfolio_id)
    return result


def _claim_forecast_job_by_id(job_id: str) -> bool:
    now = datetime.utcnow()
    with Session(engine) as session:
        stmt = (
            update(ForecastJob)
            .where(ForecastJob.id == job_id)
            .where(ForecastJob.status == "queued")
            .values(
                status="running",
                progress=0.1,
                started_at=now,
                updated_at=now,
            )
        )
        result = session.exec(stmt)
        session.commit()
        rowcount = getattr(result, "rowcount", None)
        return bool(rowcount and rowcount > 0)


def _claim_next_forecast_job(job_type: str = "portfolio_forecast") -> Optional[str]:
    """
    Claim the oldest queued job atomically. Returns job_id or None.
    """
    # Small retry loop to handle races between multiple workers.
    for _ in range(5):
        with Session(engine) as session:
            candidate = session.exec(
                select(ForecastJob.id)
                .where(ForecastJob.job_type == job_type)
                .where(ForecastJob.status == "queued")
                .order_by(ForecastJob.created_at.asc())
            ).first()
        if not candidate:
            return None
        if _claim_forecast_job_by_id(str(candidate)):
            return str(candidate)
    return None


def _run_portfolio_forecast_job(job_id: str, assume_claimed: bool = False) -> bool:
    start_ts = datetime.utcnow()
    if not assume_claimed:
        claimed = _claim_forecast_job_by_id(job_id)
        if not claimed:
            with Session(engine) as session:
                existing = session.get(ForecastJob, job_id)
                if not existing:
                    logger.warning(f"Forecast job {job_id} not found.")
                else:
                    logger.info(
                        "Forecast job %s not claimed (status=%s); skipping duplicate run.",
                        job_id,
                        existing.status,
                    )
            return False

    with Session(engine) as session:
        job = session.get(ForecastJob, job_id)
        if not job:
            logger.warning(f"Forecast job {job_id} not found after claim.")
            return False
        # Backfill started_at if a legacy caller invoked assume_claimed=True without claim timestamp.
        if not job.started_at:
            job.started_at = start_ts
        job.updated_at = start_ts
        if job.status != "running":
            job.status = "running"
            job.progress = max(float(job.progress or 0.0), 0.1)
        session.add(job)
        session.commit()
        payload = copy.deepcopy(job.request_payload or {})

    try:
        assets = _normalize_assets(payload.get("assets"))
        scenarios = payload.get("scenarios") or None
        target_weights = payload.get("target_weights") or None
        horizon_days = int(payload.get("horizon_days", 90))
        owner_user_id = int(payload.get("owner_user_id"))
        entity_type = str(payload.get("entity_type", "portfolio"))
        entity_id = str(payload.get("entity_id"))
        portfolio_id = payload.get("portfolio_id")
        input_hash = str(payload.get("input_hash"))
        store_results = bool(payload.get("store_results", True))

        latest_market_dates = payload.get("latest_market_dates") or {}
        parsed_dates = [
            datetime.fromisoformat(v)
            for v in latest_market_dates.values()
            if isinstance(v, str) and v
        ]
        data_last_date = max(parsed_dates) if parsed_dates else None

        logger.info(
            "Forecast job %s running: entity=%s/%s assets=%s horizon=%s",
            job_id,
            entity_type,
            entity_id,
            len(assets),
            horizon_days,
        )
        result = _compute_portfolio_forecast_result(
            portfolio_id=int(portfolio_id) if portfolio_id is not None else None,
            assets=assets,
            horizon_days=horizon_days,
            scenarios=scenarios,
            target_weights=target_weights,
        )
        result_blob = _json_compatible(result)

        with Session(engine) as session:
            job = session.get(ForecastJob, job_id)
            if job:
                job.status = "completed"
                job.progress = 1.0
                if store_results:
                    cache_row = _portfolio_forecast_cache_write(
                        session,
                        owner_user_id=owner_user_id,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        horizon_days=horizon_days,
                        input_hash=input_hash,
                        data_last_date=data_last_date,
                        request_payload=_json_compatible(payload),
                        result_blob=result_blob,
                    )
                    job.result_cache_id = cache_row.id
                    job.result_blob = None  # source of truth is cache row
                else:
                    job.result_cache_id = None
                    job.result_blob = _portfolio_forecast_result_with_cache_meta(
                        result_blob,
                        None,
                        persisted=False,
                    )
                job.finished_at = datetime.utcnow()
                job.updated_at = datetime.utcnow()
                session.add(job)
                session.commit()
        logger.info("Forecast job %s completed.", job_id)
        return True
    except Exception as e:
        logger.exception(f"Forecast job {job_id} failed: {e}")
        with Session(engine) as session:
            job = session.get(ForecastJob, job_id)
            if job:
                job.status = "failed"
                job.progress = 1.0
                job.error_message = str(e)
                job.finished_at = datetime.utcnow()
                job.updated_at = datetime.utcnow()
                session.add(job)
                session.commit()
        return False


def process_next_portfolio_forecast_job() -> Optional[str]:
    """
    External worker entrypoint: claim next queued portfolio forecast job and execute it.
    Returns processed job_id or None when no queued job exists.
    """
    job_id = _claim_next_forecast_job(job_type="portfolio_forecast")
    if not job_id:
        return None
    _run_portfolio_forecast_job(job_id, assume_claimed=True)
    return job_id


def _enqueue_portfolio_forecast_job(
    *,
    owner_user_id: int,
    entity_type: str,
    entity_id: str,
    portfolio_id: Optional[int],
    assets: List[dict],
    horizon_days: int,
    scenarios: Optional[List[dict]],
    target_weights: Optional[Dict[str, float]],
    store_results: bool = True,
    force_refresh: bool = False,
) -> dict:
    with Session(engine) as session:
        latest_market_dates = _portfolio_latest_market_dates(session, [a["ticker"] for a in assets])
        input_hash = _portfolio_forecast_input_hash(
            entity_type=entity_type,
            entity_id=entity_id,
            assets=assets,
            horizon_days=horizon_days,
            scenarios=scenarios,
            target_weights=target_weights,
            latest_market_dates=latest_market_dates,
        )
        request_hash = _stable_json_hash(
            {
                "input_hash": input_hash,
                "store_results": bool(store_results),
            }
        )

        if store_results and not force_refresh:
            cached = _portfolio_forecast_cache_read(
                session,
                owner_user_id=owner_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                input_hash=input_hash,
            )
            if cached:
                return {
                    "mode": "cache",
                    "cache_hit": True,
                    "job_id": None,
                    "job": None,
                    "result": cached["result"],
                    "dispatch_backend": "cache",
                }

            # Fallback: check nightly batch cache (PortfolioReportDataCache)
            if portfolio_id is not None:
                report_cached = session.exec(
                    select(PortfolioReportDataCache)
                    .where(PortfolioReportDataCache.portfolio_id == int(portfolio_id))
                    .order_by(PortfolioReportDataCache.updated_at.desc())
                ).first()
                if report_cached and report_cached.result_blob:
                    result = _adapt_nightly_blob_to_ui(report_cached.result_blob, int(portfolio_id))
                    logger.info(f"Portfolio {portfolio_id} served from nightly batch cache (async path)")
                    return {
                        "mode": "cache",
                        "cache_hit": True,
                        "job_id": None,
                        "job": None,
                        "result": result,
                        "dispatch_backend": "nightly_cache",
                    }

        existing_job = session.exec(
            select(ForecastJob)
            .where(ForecastJob.owner_user_id == owner_user_id)
            .where(ForecastJob.job_type == "portfolio_forecast")
            .where(ForecastJob.entity_type == entity_type)
            .where(ForecastJob.entity_id == str(entity_id))
            .where(ForecastJob.request_hash == request_hash)
            .where(ForecastJob.status.in_(["queued", "running"]))
            .order_by(ForecastJob.created_at.desc())
        ).first()
        if existing_job:
            return {
                "mode": "job",
                "cache_hit": False,
                "job_id": existing_job.id,
                "job": _forecast_job_to_dict(existing_job),
                "result": None,
                "dispatch_backend": FORECAST_JOB_DISPATCH_MODE,
            }

        now = datetime.utcnow()
        job_id = uuid.uuid4().hex
        request_payload = _json_compatible(
            {
                "owner_user_id": owner_user_id,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "portfolio_id": portfolio_id,
                "assets": assets,
                "horizon_days": int(horizon_days),
                "scenarios": scenarios or [],
                "target_weights": target_weights or {},
                "input_hash": input_hash,
                "latest_market_dates": latest_market_dates,
                "store_results": bool(store_results),
            }
        )
        job = ForecastJob(
            id=job_id,
            owner_user_id=owner_user_id,
            job_type="portfolio_forecast",
            entity_type=entity_type,
            entity_id=str(entity_id),
            status="queued",
            request_hash=request_hash,
            request_payload=request_payload,
            progress=0.0,
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

    if FORECAST_JOB_DISPATCH_MODE == "threadpool":
        _forecast_job_executor.submit(_run_portfolio_forecast_job, job_id)
    else:
        logger.info(
            "Forecast job %s queued for external worker dispatch (mode=%s).",
            job_id,
            FORECAST_JOB_DISPATCH_MODE,
        )
    return {
        "mode": "job",
        "cache_hit": False,
        "job_id": job_id,
        "job": _forecast_job_to_dict(job),
        "result": None,
        "dispatch_backend": FORECAST_JOB_DISPATCH_MODE,
    }


def _get_forecast_job_response(
    session: Session,
    *,
    owner_user_id: int,
    job_id: str,
) -> dict:
    job = session.get(ForecastJob, job_id)
    if not job or int(job.owner_user_id) != int(owner_user_id):
        raise HTTPException(status_code=404, detail="Job not found")

    payload = {"job": _forecast_job_to_dict(job)}
    if job.status == "completed":
        cache_row = None
        if job.result_cache_id:
            cache_row = session.get(PortfolioForecastCache, job.result_cache_id)
        if cache_row and cache_row.result_blob:
            payload["result"] = _portfolio_forecast_result_with_cache_meta(cache_row.result_blob, cache_row)
        elif job.result_blob:
            payload["result"] = job.result_blob
    elif job.status == "failed":
        payload["error"] = job.error_message or "Job failed"
    return payload


def _get_simulation_cache_result(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    method: str,
    input_hash: str,
) -> Optional[dict]:
    cached = session.exec(
        select(RiskSimulationCache)
        .where(RiskSimulationCache.entity_type == entity_type)
        .where(RiskSimulationCache.entity_id == entity_id)
        .where(RiskSimulationCache.method == method)
        .where(RiskSimulationCache.input_hash == input_hash)
        .order_by(RiskSimulationCache.created_at.desc())
    ).first()
    if not cached or not cached.result_blob:
        return None

    result = copy.deepcopy(cached.result_blob)
    result.setdefault("cache", {})
    result["cache"].update(
        {
            "hit": True,
            "cache_type": "risk_simulation",
            "cache_id": cached.id,
            "created_at": cached.created_at.isoformat() if cached.created_at else None,
            "persisted": True,
        }
    )
    return result


def _save_simulation_cache_result(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    method: str,
    horizon_days: int,
    n_simulations: int,
    random_seed: Optional[int],
    input_hash: str,
    data_last_date: Optional[datetime],
    result_blob: dict,
) -> None:
    now = datetime.utcnow()
    existing = session.exec(
        select(RiskSimulationCache)
        .where(RiskSimulationCache.entity_type == entity_type)
        .where(RiskSimulationCache.entity_id == entity_id)
        .where(RiskSimulationCache.method == method)
        .where(RiskSimulationCache.input_hash == input_hash)
    ).first()

    if existing:
        existing.horizon_days = int(horizon_days)
        existing.n_simulations = int(n_simulations)
        existing.random_seed = random_seed
        existing.data_last_date = data_last_date
        existing.result_blob = result_blob
        existing.updated_at = now
        session.add(existing)
    else:
        session.add(
            RiskSimulationCache(
                entity_type=entity_type,
                entity_id=str(entity_id),
                method=method,
                horizon_days=int(horizon_days),
                n_simulations=int(n_simulations),
                random_seed=random_seed,
                input_hash=input_hash,
                data_last_date=data_last_date,
                result_blob=result_blob,
                created_at=now,
                updated_at=now,
            )
        )
    session.commit()


def _asset_risk_cache_read(
    session: Session,
    *,
    symbol: str,
    horizon_days: int,
    n_paths: int,
    data_last_date: Optional[datetime],
    max_age_minutes: int,
    allow_stale: bool = False,
) -> Optional[dict]:
    query = (
        select(AssetRiskCache)
        .where(AssetRiskCache.symbol == symbol)
        .where(AssetRiskCache.method == "classical_r")
        .where(AssetRiskCache.horizon_days == int(horizon_days))
        .where(AssetRiskCache.n_paths == int(n_paths))
        .order_by(AssetRiskCache.updated_at.desc())
    )
    if data_last_date is not None:
        query = query.where(AssetRiskCache.data_last_date == data_last_date)
    row = session.exec(query).first()
    if not row or not row.result_blob:
        return None

    age_minutes = (datetime.utcnow() - row.updated_at).total_seconds() / 60.0 if row.updated_at else 10**9
    is_fresh = age_minutes <= max_age_minutes
    if not is_fresh and not allow_stale:
        return None

    result = copy.deepcopy(row.result_blob)
    result.setdefault("cache", {})
    result["cache"].update(
        {
            "hit": True,
            "cache_type": "asset_risk",
            "cache_id": row.id,
            "fresh": bool(is_fresh),
            "stale": not bool(is_fresh),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "data_last_date": row.data_last_date.isoformat() if row.data_last_date else None,
        }
    )
    return {"cache_row": row, "result": result, "is_fresh": is_fresh}


def _asset_risk_cache_write(
    session: Session,
    *,
    symbol: str,
    horizon_days: int,
    n_paths: int,
    data_last_date: Optional[datetime],
    result_blob: dict,
) -> AssetRiskCache:
    now = datetime.utcnow()
    query = (
        select(AssetRiskCache)
        .where(AssetRiskCache.symbol == symbol)
        .where(AssetRiskCache.method == "classical_r")
        .where(AssetRiskCache.horizon_days == int(horizon_days))
        .where(AssetRiskCache.n_paths == int(n_paths))
        .where(AssetRiskCache.data_last_date == data_last_date)
    )
    existing = session.exec(query).first()
    if existing:
        existing.result_blob = result_blob
        existing.updated_at = now
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    row = AssetRiskCache(
        symbol=symbol,
        method="classical_r",
        horizon_days=int(horizon_days),
        n_paths=int(n_paths),
        data_last_date=data_last_date,
        result_blob=result_blob,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _value_as_float(value: Any) -> Optional[float]:
    if isinstance(value, list):
        if not value:
            return None
        return _value_as_float(value[0])
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _value_as_str(value: Any) -> Optional[str]:
    if isinstance(value, list):
        if not value:
            return None
        return _value_as_str(value[0])
    if value is None:
        return None
    try:
        return str(value)
    except Exception:
        return None


def _asset_volatility_snapshot_write(
    session: Session,
    *,
    symbol: str,
    horizon_days: int,
    n_paths: int,
    data_last_date: Optional[datetime],
    risk_payload: dict,
) -> AssetVolatilitySnapshot:
    sigma_hist = risk_payload.get("sigma_hist")
    if not isinstance(sigma_hist, list) or not sigma_hist:
        legacy_sigma_hist = risk_payload.get("volatility")
        sigma_hist = legacy_sigma_hist if isinstance(legacy_sigma_hist, list) else []

    sigma_fc_mean = risk_payload.get("sigma_fc_mean")
    if not isinstance(sigma_fc_mean, list):
        sigma_fc_mean = []

    snapshot_blob = {
        "sigma_hist": sigma_hist,
        "sigma_fc_mean": sigma_fc_mean,
        "sigma_mc_lower": risk_payload.get("sigma_mc_lower", []),
        "sigma_mc_median": risk_payload.get("sigma_mc_median", []),
        "sigma_mc_upper": risk_payload.get("sigma_mc_upper", []),
        "mc_lower": risk_payload.get("mc_lower", []),
        "mc_median": risk_payload.get("mc_median", []),
        "mc_upper": risk_payload.get("mc_upper", []),
    }
    now = datetime.utcnow()
    row = AssetVolatilitySnapshot(
        symbol=symbol,
        as_of=now,
        method="classical_r",
        horizon_days=int(horizon_days),
        n_paths=int(n_paths),
        data_last_date=data_last_date,
        sigma_latest=_value_as_float(sigma_hist[-1]) if sigma_hist else None,
        sigma_next=_value_as_float(sigma_fc_mean[0]) if sigma_fc_mean else None,
        var_95_latest=_value_as_float(risk_payload.get("var_95_latest")),
        fragility_score_latest=_value_as_float(risk_payload.get("fragility_score_latest")),
        regime_latest=_value_as_str(risk_payload.get("regime_latest")),
        snapshot_blob=_json_compatible(snapshot_blob),
        created_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _news_cache_read(
    session: Session,
    *,
    symbol: str,
    limit_count: int,
    source: str,
    max_age_minutes: int,
    allow_stale: bool = False,
) -> Optional[dict]:
    row = session.exec(
        select(NewsCache)
        .where(NewsCache.symbol == symbol)
        .where(NewsCache.limit_count == int(limit_count))
        .where(NewsCache.source == source)
        .order_by(NewsCache.updated_at.desc())
    ).first()
    if not row or not isinstance(row.items_blob, dict):
        return None

    now = datetime.utcnow()
    expires_at = row.expires_at
    is_fresh = bool(expires_at and expires_at >= now)
    if not is_fresh and max_age_minutes > 0 and row.updated_at:
        age_minutes = (now - row.updated_at).total_seconds() / 60.0
        is_fresh = age_minutes <= max_age_minutes
    if not is_fresh and not allow_stale:
        return None

    payload = copy.deepcopy(row.items_blob)
    payload.setdefault("cache", {})
    payload["cache"].update(
        {
            "hit": True,
            "cache_type": "news",
            "cache_id": row.id,
            "fresh": bool(is_fresh),
            "stale": not bool(is_fresh),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        }
    )
    return {"cache_row": row, "result": payload, "is_fresh": is_fresh}


def _news_cache_write(
    session: Session,
    *,
    symbol: str,
    limit_count: int,
    source: str,
    items: List[dict],
    ttl_minutes: int,
) -> NewsCache:
    now = datetime.utcnow()
    expires_at = now + timedelta(minutes=max(1, int(ttl_minutes or 1)))
    payload = {"ticker": symbol, "items": items}
    existing = session.exec(
        select(NewsCache)
        .where(NewsCache.symbol == symbol)
        .where(NewsCache.limit_count == int(limit_count))
        .where(NewsCache.source == source)
    ).first()
    if existing:
        existing.items_blob = payload
        existing.fetched_at = now
        existing.expires_at = expires_at
        existing.updated_at = now
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    row = NewsCache(
        symbol=symbol,
        source=source,
        limit_count=int(limit_count),
        items_blob=payload,
        fetched_at=now,
        expires_at=expires_at,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _asset_search_results(session: Session, q: str, limit: int) -> List[dict]:
    term = (q or "").strip()
    if not term:
        return []
    canon = _canonical_symbol(term)
    safe_limit = max(1, min(int(limit or 10), 50))

    rows = session.exec(
        select(Asset)
        .where(
            (Asset.symbol.contains(canon)) | (Asset.name.contains(term))
        )
        .order_by(Asset.symbol.asc())
        .limit(safe_limit)
    ).all()

    # Ingest exact symbol on demand when registry is missing it.
    if not rows and len(canon) <= 15:
        try:
            fundamentals = get_fundamentals_cached(canon, session=session)
            _ensure_asset(session, canon, fundamentals)
            rows = session.exec(
                select(Asset)
                .where(Asset.symbol == canon)
                .limit(1)
            ).all()
        except Exception as e:
            logger.warning("Asset search exact-symbol hydration failed for %s: %s", canon, str(e))

    results: List[dict] = []
    for row in rows[:safe_limit]:
        results.append(
            {
                "symbol": row.symbol,
                "name": row.name,
                "asset_type": row.asset_type,
                "exchange": row.exchange,
                "currency": row.currency,
                "vendor": row.vendor,
                "vendor_symbol": row.vendor_symbol,
            }
        )
    return results


def _build_path_from_returns(base_price: float, forecast_returns: List[float], scenario: dict) -> List[float]:
    shock = float(scenario.get("initial_shock_pct", 0.0) or 0.0)
    scale = float(scenario.get("return_scale", 1.0) or 1.0)
    drift_shift = float(scenario.get("drift_shift", 0.0) or 0.0)
    curr = base_price * (1 + shock)
    path = []
    for r in forecast_returns:
        curr = curr * (1 + (float(r) * scale) + drift_shift)
        path.append(float(curr))
    return path


def _attach_asset_scenarios(result: dict, custom_scenarios: Optional[List[dict]] = None) -> dict:
    # If the cached result already has VQMC fan-shaped scenarios (from predict()),
    # preserve them. Only generate deterministic flat-price scenarios as a fallback
    # when the fan data is absent (e.g. old cache entries from before VQMC scenarios).
    existing = result.get("scenarios")
    if isinstance(existing, dict) and existing:
        first_val = next(iter(v for k, v in existing.items() if not k.startswith("_")), None)
        if isinstance(first_val, dict) and "central" in first_val:
            # VQMC fan data already present; generate flat legacy paths alongside.
            if "scenarios_legacy" not in result:
                forecast_returns = result.get("forecast_returns", []) or []
                forecast_prices = result.get("forecast_prices", []) or []
                history_prices = result.get("history_prices", []) or []
                base_price = float(history_prices[-1]) if history_prices else (float(forecast_prices[0]) if forecast_prices else 0.0)
                legacy = {"base": forecast_prices}
                if forecast_returns:
                    for name in ["bull_10", "bear_10", "high_vol_regime", "low_vol_regime"]:
                        sc = {"bull_10": {"initial_shock_pct": 0.10}, "bear_10": {"initial_shock_pct": -0.10},
                              "high_vol_regime": {"return_scale": 1.25}, "low_vol_regime": {"return_scale": 0.75}}.get(name, {})
                        legacy[name] = _build_path_from_returns(base_price, forecast_returns, sc)
                result["scenarios_legacy"] = legacy
            return result

    # No VQMC fan data: generate deterministic flat-price scenarios (original behaviour).
    forecast_returns = result.get("forecast_returns", []) or []
    if not forecast_returns:
        result["scenarios"] = {"base": result.get("forecast_prices", [])}
        return result

    history_prices = result.get("history_prices", []) or []
    forecast_prices = result.get("forecast_prices", []) or []
    base_price = float(history_prices[-1]) if history_prices else (float(forecast_prices[0]) if forecast_prices else 0.0)
    scenario_defs = {
        "bull_10": {"name": "bull_10", "initial_shock_pct": 0.10, "return_scale": 1.0, "drift_shift": 0.0},
        "bear_10": {"name": "bear_10", "initial_shock_pct": -0.10, "return_scale": 1.0, "drift_shift": 0.0},
        "high_vol_regime": {"name": "high_vol_regime", "initial_shock_pct": 0.0, "return_scale": 1.25, "drift_shift": 0.0},
        "low_vol_regime": {"name": "low_vol_regime", "initial_shock_pct": 0.0, "return_scale": 0.75, "drift_shift": 0.0},
    }
    for scenario in custom_scenarios or []:
        name = str(scenario.get("name", "")).strip()
        if not name:
            continue
        scenario_defs[name] = scenario

    scenario_paths = {"base": result.get("forecast_prices", [])}
    for name, scenario in scenario_defs.items():
        scenario_paths[name] = _build_path_from_returns(base_price, forecast_returns, scenario)

    result["scenarios"] = scenario_paths
    return result


def _strip_asset_scenarios(result: dict) -> dict:
    sanitized = copy.deepcopy(result or {})
    sanitized.pop("scenarios", None)
    return sanitized


def _watchlist_to_dict(watchlist: Watchlist, items: List[WatchlistItem]) -> dict:
    return {
        "watchlist_id": watchlist.id,
        "user_id": watchlist.user_id,
        "name": watchlist.name,
        "tickers": [item.ticker for item in items],
        "created_at": watchlist.created_at.isoformat(),
        "updated_at": watchlist.updated_at.isoformat(),
    }


SAVED_ASSETS_WATCHLIST_NAME = "__saved_assets__"


def _get_or_create_saved_watchlist(session: Session, user: User) -> Watchlist:
    wl = session.exec(
        select(Watchlist)
        .where(Watchlist.user_id == user.id)
        .where(Watchlist.name == SAVED_ASSETS_WATCHLIST_NAME)
    ).first()
    if wl:
        return wl
    now = datetime.utcnow()
    wl = Watchlist(user_id=user.id, name=SAVED_ASSETS_WATCHLIST_NAME, created_at=now, updated_at=now)
    session.add(wl)
    session.commit()
    session.refresh(wl)
    return wl


def _build_screener_row(symbol: str, fundamentals: dict) -> dict:
    fundamentals = fundamentals or {}
    valuation = fundamentals.get("valuation", {}) or {}
    profile = fundamentals.get("profile", {}) or {}
    profitability = fundamentals.get("profitability", {}) or {}
    technicals = fundamentals.get("technicals", {}) or {}

    return {
        "ticker": symbol,
        "type": fundamentals.get("type", "UNKNOWN"),
        "name": profile.get("name", symbol),
        "sector": profile.get("sector", "Unknown"),
        "market_cap": valuation.get("market_cap"),
        "pe_ratio": valuation.get("pe_ratio"),
        "ev_to_ebitda": valuation.get("ev_to_ebitda"),
        "profit_margin": profitability.get("profit_margin"),
        "beta": technicals.get("beta"),
    }


def _passes_screener_filters(row: dict, filters: dict) -> bool:
    filters = filters or {}

    def _num(key):
        val = row.get(key)
        return float(val) if val is not None else None

    min_market_cap = filters.get("min_market_cap")
    if min_market_cap is not None:
        val = _num("market_cap")
        if val is None or val < float(min_market_cap):
            return False

    max_market_cap = filters.get("max_market_cap")
    if max_market_cap is not None:
        val = _num("market_cap")
        if val is None or val > float(max_market_cap):
            return False

    min_pe = filters.get("min_pe_ratio")
    if min_pe is not None:
        val = _num("pe_ratio")
        if val is None or val < float(min_pe):
            return False

    max_pe = filters.get("max_pe_ratio")
    if max_pe is not None:
        val = _num("pe_ratio")
        if val is None or val > float(max_pe):
            return False

    min_ev = filters.get("min_ev_to_ebitda")
    if min_ev is not None:
        val = _num("ev_to_ebitda")
        if val is None or val < float(min_ev):
            return False

    max_ev = filters.get("max_ev_to_ebitda")
    if max_ev is not None:
        val = _num("ev_to_ebitda")
        if val is None or val > float(max_ev):
            return False

    min_margin = filters.get("min_profit_margin")
    if min_margin is not None:
        val = _num("profit_margin")
        if val is None or val < float(min_margin):
            return False

    max_margin = filters.get("max_profit_margin")
    if max_margin is not None:
        val = _num("profit_margin")
        if val is None or val > float(max_margin):
            return False

    min_beta = filters.get("min_beta")
    if min_beta is not None:
        val = _num("beta")
        if val is None or val < float(min_beta):
            return False

    max_beta = filters.get("max_beta")
    if max_beta is not None:
        val = _num("beta")
        if val is None or val > float(max_beta):
            return False

    sector_in = filters.get("sector_in")
    if sector_in:
        allowed = {str(x).lower() for x in sector_in}
        if str(row.get("sector", "")).lower() not in allowed:
            return False

    type_in = filters.get("type_in")
    if type_in:
        allowed = {str(x).upper() for x in type_in}
        if str(row.get("type", "UNKNOWN")).upper() not in allowed:
            return False

    return True


def _is_triggered(value: float, direction: str, threshold: float) -> bool:
    if str(direction).lower() == "below":
        return value <= threshold
    return value >= threshold


def _evaluate_alert_rule(rule: AlertRule) -> dict:
    ticker = rule.ticker
    direction = str(rule.direction or "above").lower()
    threshold = float(rule.threshold_value or 0.0)
    lookback_days = int(rule.lookback_days or 30)
    extra = rule.extra_config or {}
    alert_type = str(rule.alert_type or "price_threshold").lower()

    prices = get_price_series_cached(ticker, period="1y")
    if not prices:
        return {
            "alert_id": rule.id,
            "ticker": ticker,
            "alert_type": alert_type,
            "triggered": False,
            "reason": "No price data available",
        }

    close_prices = [float(x["price"]) for x in prices]
    latest_price = float(close_prices[-1])

    if alert_type == "price_threshold":
        value = latest_price
        triggered = _is_triggered(value, direction, threshold)
        return {
            "alert_id": rule.id,
            "ticker": ticker,
            "alert_type": alert_type,
            "triggered": bool(triggered),
            "value": float(value),
            "threshold": float(threshold),
            "direction": direction,
        }

    if alert_type == "anomaly":
        series = pd.Series(close_prices).pct_change().dropna()
        if len(series) < max(lookback_days, 5):
            return {
                "alert_id": rule.id,
                "ticker": ticker,
                "alert_type": alert_type,
                "triggered": False,
                "reason": "Insufficient returns history",
            }
        sample = series.tail(lookback_days)
        z_threshold = float(extra.get("zscore_threshold", threshold if threshold > 0 else 2.5))
        mean = float(sample.mean())
        std = float(sample.std())
        latest_ret = float(series.iloc[-1])
        zscore = 0.0 if std == 0 else abs((latest_ret - mean) / std)
        triggered = zscore >= z_threshold
        return {
            "alert_id": rule.id,
            "ticker": ticker,
            "alert_type": alert_type,
            "triggered": bool(triggered),
            "zscore": float(zscore),
            "threshold": float(z_threshold),
            "latest_return": float(latest_ret),
        }

    if alert_type == "forecast_divergence":
        horizon = int(extra.get("horizon_days", max(5, min(90, lookback_days))))
        forecast = generate_forecast(ForecastRequest(ticker=ticker, horizon_days=horizon))
        forecast_prices = forecast.get("forecast_prices", []) or []
        if not forecast_prices:
            return {
                "alert_id": rule.id,
                "ticker": ticker,
                "alert_type": alert_type,
                "triggered": False,
                "reason": "Forecast unavailable",
            }
        recent_window = min(lookback_days, len(close_prices) - 1)
        base_idx = -recent_window - 1
        realized_return = (close_prices[-1] / close_prices[base_idx]) - 1 if recent_window > 0 else 0.0
        forecast_return = (float(forecast_prices[-1]) / latest_price) - 1 if latest_price > 0 else 0.0
        divergence = forecast_return - realized_return
        div_threshold = float(extra.get("divergence_threshold", abs(threshold) if threshold != 0 else 0.05))
        triggered = abs(divergence) >= div_threshold
        return {
            "alert_id": rule.id,
            "ticker": ticker,
            "alert_type": alert_type,
            "triggered": bool(triggered),
            "forecast_return": float(forecast_return),
            "realized_return": float(realized_return),
            "divergence": float(divergence),
            "threshold": float(div_threshold),
        }

    return {
        "alert_id": rule.id,
        "ticker": ticker,
        "alert_type": alert_type,
        "triggered": False,
        "reason": f"Unsupported alert_type: {alert_type}",
    }


def _evaluate_alerts_internal(
    alert_ids: Optional[List[int]] = None,
    active_only: bool = True,
    persist: bool = True,
    owner_user_id: Optional[int] = None,
) -> dict:
    with Session(engine) as session:
        query = select(AlertRule)
        if owner_user_id is not None:
            query = query.where(AlertRule.user_id == owner_user_id)
        if active_only:
            query = query.where(AlertRule.is_active == True)  # noqa: E712
        alerts = session.exec(query).all()

        if alert_ids:
            allowed = set(alert_ids)
            alerts = [a for a in alerts if a.id in allowed]

        evaluations = []
        for alert in alerts:
            try:
                result = _evaluate_alert_rule(alert)
            except Exception as e:
                result = {
                    "alert_id": alert.id,
                    "ticker": alert.ticker,
                    "alert_type": alert.alert_type,
                    "triggered": False,
                    "reason": f"Evaluation failed: {str(e)}",
                }

            now = datetime.utcnow()
            triggered = bool(result.get("triggered", False))
            cooldown_seconds = int((alert.extra_config or {}).get("cooldown_seconds", ALERT_EVENT_COOLDOWN_SECONDS))
            suppressed_by_cooldown = False
            last_triggered_at = None

            if persist and triggered and cooldown_seconds > 0:
                last_triggered = session.exec(
                    select(AlertEvent)
                    .where(AlertEvent.alert_id == alert.id)
                    .where(AlertEvent.triggered == True)  # noqa: E712
                    .order_by(AlertEvent.evaluated_at.desc())
                ).first()
                if last_triggered and last_triggered.evaluated_at:
                    last_triggered_at = last_triggered.evaluated_at
                    suppress_before = now - timedelta(seconds=cooldown_seconds)
                    if last_triggered.evaluated_at >= suppress_before:
                        suppressed_by_cooldown = True

            result["cooldown_seconds"] = cooldown_seconds
            result["suppressed_by_cooldown"] = suppressed_by_cooldown
            result["last_triggered_at"] = last_triggered_at.isoformat() if last_triggered_at else None
            result["event_persisted"] = (not suppressed_by_cooldown) if persist else False
            evaluations.append(result)

            if persist:
                if not suppressed_by_cooldown:
                    session.add(
                        AlertEvent(
                            alert_id=alert.id,
                            ticker=alert.ticker,
                            alert_type=alert.alert_type,
                            triggered=triggered,
                            payload=result,
                            evaluated_at=now,
                        )
                    )

        if persist:
            session.commit()

    triggered = [item for item in evaluations if item.get("triggered")]
    return {
        "evaluated_count": len(evaluations),
        "triggered_count": len(triggered),
        "items": evaluations,
    }


def _alert_scheduler_loop() -> None:
    logger.info(
        "Alert scheduler started (interval=%ss, enabled=%s).",
        ALERT_SCHEDULER_INTERVAL_SECONDS,
        ALERT_SCHEDULER_ENABLED,
    )
    while not _alert_scheduler_stop.is_set():
        started = datetime.utcnow()
        try:
            summary = _evaluate_alerts_internal(active_only=True, persist=True)
            logger.info(
                "Scheduled alert evaluation completed: evaluated=%s triggered=%s",
                summary["evaluated_count"],
                summary["triggered_count"],
            )
        except Exception as e:
            logger.error("Scheduled alert evaluation failed: %s", str(e))

        elapsed = (datetime.utcnow() - started).total_seconds()
        sleep_for = max(1, ALERT_SCHEDULER_INTERVAL_SECONDS - int(elapsed))
        _alert_scheduler_stop.wait(sleep_for)

    logger.info("Alert scheduler stopped.")


def _start_alert_scheduler() -> None:
    global _alert_scheduler_thread

    if not ALERT_SCHEDULER_ENABLED:
        logger.info("Alert scheduler is disabled by configuration.")
        return

    if _alert_scheduler_thread is not None and _alert_scheduler_thread.is_alive():
        return

    _alert_scheduler_stop.clear()
    _alert_scheduler_thread = threading.Thread(
        target=_alert_scheduler_loop,
        name="alert-scheduler",
        daemon=True,
    )
    _alert_scheduler_thread.start()


def _stop_alert_scheduler() -> None:
    global _alert_scheduler_thread

    _alert_scheduler_stop.set()
    if _alert_scheduler_thread is not None and _alert_scheduler_thread.is_alive():
        _alert_scheduler_thread.join(timeout=5)
    _alert_scheduler_thread = None

# -------------------------------------------------------------------
# Unified Asset API (V1)
# -------------------------------------------------------------------

@app.get("/assets/search")
def search_assets(q: str, limit: int = 10):
    """
    Search canonical asset registry (with exact-symbol hydrate on miss).
    """
    term = (q or "").strip()
    if not term:
        return {"items": [], "query": q, "count": 0}
    with Session(engine) as session:
        items = _asset_search_results(session, term, limit)
    return {"items": items, "query": term, "count": len(items)}


@app.get("/assets/{asset_id}/profile")
def get_asset_profile(asset_id: str):
    """
    Returns standardized asset profile + fundamentals.
    """
    try:
        with Session(engine) as session:
            fundamentals = get_fundamentals_cached(asset_id, session=session)
            if not fundamentals:
                raise HTTPException(status_code=404, detail="No fundamentals found")
            asset = _ensure_asset(session, asset_id, fundamentals)
            ticker = asset.symbol
        return {"ticker": ticker, **fundamentals}
    except Exception as e:
        logger.error(f"Profile fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/assets/{asset_id}/fundamentals")
def get_asset_fundamentals(asset_id: str):
    """
    Returns standardized fundamentals for the asset.
    """
    try:
        with Session(engine) as session:
            fundamentals = get_fundamentals_cached(asset_id, session=session)
            if not fundamentals:
                raise HTTPException(status_code=404, detail="No fundamentals found")
            asset = _ensure_asset(session, asset_id, fundamentals)
            ticker = asset.symbol
        return {"ticker": ticker, "fundamentals": fundamentals}
    except Exception as e:
        logger.error(f"Fundamentals fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/assets/{asset_id}/price")
def get_asset_price(asset_id: str, period: str = "2y"):
    """
    Returns historical price series for the asset.
    """
    try:
        with Session(engine) as session:
            asset = _ensure_asset(session, asset_id)
            ticker = asset.symbol
            raw_data = get_price_series_cached(ticker, period=period, session=session)
        if not raw_data:
            raise HTTPException(status_code=404, detail="No price data found for ticker")
        return {"ticker": ticker, "period": period, "series": raw_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Price fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/assets/{asset_id}/news")
def get_asset_news(asset_id: str, limit: int = 5, refresh: bool = False):
    """
    Returns latest news for the asset (DB-first with TTL cache).
    """
    try:
        with Session(engine) as session:
            asset = _ensure_asset(session, asset_id)
            ticker = asset.symbol
            if not refresh:
                cached = _news_cache_read(
                    session,
                    symbol=ticker,
                    limit_count=int(limit),
                    source=str(VENDOR.name),
                    max_age_minutes=NEWS_CACHE_MAX_AGE_MINUTES,
                    allow_stale=False,
                )
                if cached:
                    return cached["result"]

        news = fetch_news(ticker, limit=limit)
        result = {"ticker": ticker, "items": news, "cache": {"hit": False, "cache_type": "news"}}

        try:
            with Session(engine) as session:
                _news_cache_write(
                    session,
                    symbol=ticker,
                    limit_count=int(limit),
                    source=str(VENDOR.name),
                    items=_json_compatible(news),
                    ttl_minutes=NEWS_CACHE_MAX_AGE_MINUTES,
                )
        except Exception as cache_err:
            logger.warning(f"News cache write failed for {ticker}: {cache_err}")

        return result
    except Exception as e:
        try:
            with Session(engine) as session:
                asset = _ensure_asset(session, asset_id)
                ticker = asset.symbol
                stale = _news_cache_read(
                    session,
                    symbol=ticker,
                    limit_count=int(limit),
                    source=str(VENDOR.name),
                    max_age_minutes=NEWS_CACHE_MAX_AGE_MINUTES,
                    allow_stale=True,
                )
                if stale:
                    stale["result"].setdefault("warnings", [])
                    stale["result"]["warnings"].append(f"Serving stale cached news: {str(e)}")
                    return stale["result"]
        except Exception:
            pass
        logger.error(f"News fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/assets/{asset_id}/risk")
def get_asset_risk(asset_id: str, horizon_days: int = 90, n_paths: int = 1000, refresh: bool = False):
    """
    Returns risk metrics + Monte Carlo cones from the R risk engine (DB-first cache).
    """
    try:
        data_last_date: Optional[datetime] = None
        with Session(engine) as session:
            asset = _ensure_asset(session, asset_id)
            ticker = asset.symbol
            raw_data = get_price_series_cached(ticker, period="2y", session=session)
            if raw_data:
                try:
                    data_last_date = datetime.strptime(str(raw_data[-1]["date"]), "%Y-%m-%d")
                except Exception:
                    data_last_date = None
            if raw_data and not refresh:
                cached = _asset_risk_cache_read(
                    session,
                    symbol=ticker,
                    horizon_days=int(horizon_days),
                    n_paths=int(n_paths),
                    data_last_date=data_last_date,
                    max_age_minutes=ASSET_RISK_CACHE_MAX_AGE_MINUTES,
                    allow_stale=False,
                )
                if cached:
                    return cached["result"]
                # Try stale cache — serve pre-computed data instead of computing live
                stale_cached = _asset_risk_cache_read(
                    session,
                    symbol=ticker,
                    horizon_days=int(horizon_days),
                    n_paths=int(n_paths),
                    data_last_date=data_last_date,
                    max_age_minutes=999999,
                    allow_stale=True,
                )
                if stale_cached:
                    logger.info(f"Serving stale risk cache for {ticker}")
                    return stale_cached["result"]
        if not raw_data:
            raise HTTPException(status_code=404, detail="No price data found for ticker")

        prices = [row["price"] for row in raw_data]
        try:
            data = calculate_risk(
                prices=prices,
                horizon=int(horizon_days),
                n_paths=int(n_paths),
                require_success=True,
            )
        except Exception as e:
            # Fallback to stale cached risk if available.
            with Session(engine) as session:
                stale = _asset_risk_cache_read(
                    session,
                    symbol=ticker,
                    horizon_days=int(horizon_days),
                    n_paths=int(n_paths),
                    data_last_date=data_last_date,
                    max_age_minutes=ASSET_RISK_CACHE_MAX_AGE_MINUTES,
                    allow_stale=True,
                )
                if stale:
                    stale["result"].setdefault("warnings", [])
                    stale["result"]["warnings"].append(f"Serving stale cached risk: {str(e)}")
                    return stale["result"]
            raise HTTPException(status_code=502, detail=f"Risk service unavailable: {str(e)}")

        data["ticker"] = ticker
        data.setdefault("cache", {})
        data["cache"].update(
            {
                "hit": False,
                "cache_type": "asset_risk",
                "data_last_date": data_last_date.isoformat() if data_last_date else None,
            }
        )

        try:
            with Session(engine) as session:
                _asset_risk_cache_write(
                    session,
                    symbol=ticker,
                    horizon_days=int(horizon_days),
                    n_paths=int(n_paths),
                    data_last_date=data_last_date,
                    result_blob=_json_compatible(data),
                )
        except Exception as cache_err:
            logger.warning(f"Risk cache write failed for {ticker}: {cache_err}")

        if refresh:
            try:
                with Session(engine) as session:
                    _asset_volatility_snapshot_write(
                        session,
                        symbol=ticker,
                        horizon_days=int(horizon_days),
                        n_paths=int(n_paths),
                        data_last_date=data_last_date,
                        risk_payload=data,
                    )
            except Exception as snapshot_err:
                logger.warning(f"Volatility snapshot write failed for {ticker}: {snapshot_err}")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Risk fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/assets/{asset_id}/forecast")
def forecast_asset(asset_id: str, payload: Optional[AssetForecastRequest] = None, horizon_days: int = 90):
    """
    Convenience wrapper around /forecast for unified routing.
    """
    try:
        with Session(engine) as session:
            asset = _ensure_asset(session, asset_id)
            ticker = asset.symbol
        req = ForecastRequest(
            ticker=ticker,
            horizon_days=payload.horizon_days if payload else horizon_days,
            scenarios=payload.scenarios if payload else None,
        )
        return generate_forecast(req)
    except Exception as e:
        logger.error(f"Asset forecast failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/forecast")
def generate_forecast(payload: ForecastRequest):
    try:
        scenario_defs = _scenario_to_dicts(payload.scenarios)

        # 1. Fetch Data
        if payload.history and len(payload.history) > 0:
            logger.info(f"Using provided history for {payload.ticker}")
            raw_data = [item.dict() for item in payload.history]
            fundamentals = {} 
        else:
            logger.info(f"Fetching data for {payload.ticker}...")
            with Session(engine) as session:
                _ensure_asset(session, payload.ticker)
                raw_data = get_price_series_cached(payload.ticker, period="2y", session=session)
                fundamentals = get_fundamentals_cached(payload.ticker, session=session)

        if not raw_data:
            raise HTTPException(status_code=404, detail="No data found for ticker")

        # 2. Prepare Data
        df = pd.DataFrame(raw_data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')

        # --- Cache lookup (skip when user provides custom history) ---
        # Scenarios are response-only and intentionally excluded from stored blobs.
        use_cache = not (payload.history and len(payload.history) > 0)
        data_last_date = df['date'].iloc[-1].to_pydatetime()
        if use_cache:
            with Session(engine) as session:
                cached = session.exec(
                    select(ForecastCache)
                    .where(ForecastCache.ticker == payload.ticker)
                    .where(ForecastCache.horizon_days == payload.horizon_days)
                    .where(ForecastCache.data_last_date == data_last_date)
                    .order_by(ForecastCache.run_date.desc())
                ).first()
                if cached and cached.forecast_blob:
                    result = copy.deepcopy(cached.forecast_blob)
                    # Preserve VQMC fan scenarios from cache if present;
                    # _attach_asset_scenarios will detect them and skip overwriting.
                    result.setdefault("metadata", {})
                    result["metadata"].update({
                        "model_version": cached.model_version,
                        "training_window": {
                            "start": cached.training_window_start.isoformat() if cached.training_window_start else None,
                            "end": cached.training_window_end.isoformat() if cached.training_window_end else None
                        },
                        "last_train_date": cached.run_date.isoformat()
                    })
                    result["cache"] = {
                        "hit": True,
                        "run_date": cached.run_date.isoformat(),
                        "data_last_date": data_last_date.isoformat()
                    }
                    _attach_asset_scenarios(result, scenario_defs)
                    return result

        # 3. Try ANY cached result for this ticker (even if data_last_date doesn't match exactly)
        if use_cache:
            with Session(engine) as session:
                stale_cached = session.exec(
                    select(ForecastCache)
                    .where(ForecastCache.ticker == payload.ticker)
                    .where(ForecastCache.horizon_days == payload.horizon_days)
                    .order_by(ForecastCache.run_date.desc())
                ).first()
                if stale_cached and stale_cached.forecast_blob:
                    logger.info(f"Serving stale cache for {payload.ticker} (cached date: {stale_cached.data_last_date})")
                    result = copy.deepcopy(stale_cached.forecast_blob)
                    result.setdefault("metadata", {})
                    result["metadata"].update({
                        "model_version": stale_cached.model_version,
                        "training_window": {
                            "start": stale_cached.training_window_start.isoformat() if stale_cached.training_window_start else None,
                            "end": stale_cached.training_window_end.isoformat() if stale_cached.training_window_end else None
                        },
                        "last_train_date": stale_cached.run_date.isoformat()
                    })
                    result["cache"] = {
                        "hit": True,
                        "stale": True,
                        "run_date": stale_cached.run_date.isoformat(),
                        "data_last_date": stale_cached.data_last_date.isoformat() if stale_cached.data_last_date else None,
                    }
                    # Ensure history data is present
                    if "history_prices" not in result:
                        result["history_prices"] = df['price'].tolist()
                        result["history_dates"] = df['date'].dt.strftime('%Y-%m-%d').tolist()
                    _attach_asset_scenarios(result, scenario_defs)
                    return result

        # 4. No cache at all — compute live (only for assets never seen before)
        logger.info(f"No cache found for {payload.ticker}, computing live forecast")
        forecaster = HybridForecaster()
        forecaster.fundamentals = fundamentals
        forecaster.train(df)

        result = forecaster.predict(forecast_horizon_days=payload.horizon_days)
        result['ticker'] = payload.ticker
        result["fundamentals"] = fundamentals
        result["history_prices"] = df['price'].tolist()
        result["history_dates"] = df['date'].dt.strftime('%Y-%m-%d').tolist()

        model_version = os.getenv("FORECAST_MODEL_VERSION", "v1")
        training_start = df['date'].iloc[0].to_pydatetime()
        training_end = df['date'].iloc[-1].to_pydatetime()
        result.setdefault("metadata", {})
        result["metadata"].update({
            "model_version": model_version,
            "training_window": {
                "start": training_start.isoformat(),
                "end": training_end.isoformat()
            },
            "last_train_date": datetime.utcnow().isoformat()
        })
        result["cache"] = {
            "hit": False,
            "data_last_date": training_end.isoformat()
        }
        _attach_asset_scenarios(result, scenario_defs)

        # Cache write
        if use_cache:
            try:
                final_pred = result["forecast_prices"][-1] if result.get("forecast_prices") else 0.0
                fragility = result.get("risk_metrics", {}).get("fragility_score", 0.0)
                var_95 = result.get("risk_metrics", {}).get("var_95", 0.0)
                scenario_free_result = _strip_asset_scenarios(result)
                with Session(engine) as session:
                    cache = ForecastCache(
                        ticker=payload.ticker,
                        run_date=datetime.utcnow(),
                        horizon_days=payload.horizon_days,
                        winner_model=result.get("model_used", "unknown"),
                        model_version=model_version,
                        training_window_start=training_start,
                        training_window_end=training_end,
                        data_last_date=data_last_date,
                        forecast_blob=scenario_free_result,
                        final_predicted_price=float(final_pred or 0.0),
                        fragility_score=float(fragility or 0.0),
                        var_95=float(var_95 or 0.0)
                    )
                    session.add(cache)
                    session.commit()
            except Exception as e:
                logger.warning(f"Forecast cache write failed: {e}")

        return result

    except Exception as e:
        logger.error(f"Forecast failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/simulate_quantum_risk")
def simulate_quantum_risk(payload: QuantumRiskRequest):
    try:
        method = (payload.method or "vqmc").lower()
        logger.info(f"Running Quantum Risk for {payload.ticker} (method={method})")

        if method == "iae":
            results = estimate_var_cvar_iae(
                historical_prices=payload.prices,
                horizon_days=payload.horizon_days,
                confidence=payload.confidence,
                num_uncertainty_qubits=payload.num_uncertainty_qubits,
                epsilon_target=payload.epsilon_target,
                bisection_iters=payload.bisection_iters,
            )
        elif method == "vqmc_trained":
            results = simulate_trained_vqmc(
                historical_prices=payload.prices,
                ticker=payload.ticker,
                horizon_days=payload.horizon_days,
                n_simulations=payload.n_simulations,
                random_seed=payload.random_seed,
            )
        elif method == "vqmc":
            # Legacy alias: VQMC now routes to the trained Qiskit ansatz.
            results = simulate_trained_vqmc(
                historical_prices=payload.prices,
                ticker=payload.ticker,
                horizon_days=payload.horizon_days,
                n_simulations=payload.n_simulations,
                random_seed=payload.random_seed,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown quantum method: {method}")

        results["ticker"] = payload.ticker
        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quantum simulation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/forecast_portfolio")
def forecast_portfolio(payload: PortfolioRequest):
    try:
        assets = _normalize_assets(payload.assets)
        if not assets:
            raise HTTPException(status_code=400, detail="assets are required")

        # Try nightly cache — match by tickers
        requested_tickers = set(a["ticker"] for a in assets)
        try:
            with Session(engine) as session:
                all_cached = session.exec(
                    select(PortfolioReportDataCache)
                    .order_by(PortfolioReportDataCache.updated_at.desc())
                ).all()
                for cached in all_cached:
                    if cached.result_blob:
                        cached_tickers = set(cached.result_blob.get("tickers", []))
                        if requested_tickers == cached_tickers:
                            logger.info(f"forecast_portfolio served from nightly cache (portfolio {cached.portfolio_id})")
                            return _adapt_nightly_blob_to_ui(cached.result_blob, cached.portfolio_id)
        except Exception as e:
            logger.warning(f"Nightly cache lookup failed: {e}")

        scenario_defs = _scenario_to_dicts(payload.scenarios)
        target_weights = _normalize_target_weights(
            payload.target_weights,
            known_tickers=[a["ticker"] for a in assets],
        )
        logger.info(f"Processing portfolio live: {len(assets)} assets")
        manager = PortfolioManager(assets)
        result = manager.analyze_portfolio(
            horizon_days=payload.horizon_days,
            scenarios=scenario_defs,
            target_weights=target_weights,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Portfolio forecast failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------------
# Unified Portfolio API (V1)
# -------------------------------------------------------------------

def _parse_portfolio_id(portfolio_id: str) -> int:
    try:
        return int(portfolio_id)
    except Exception:
        raise HTTPException(status_code=400, detail="portfolio_id must be an integer")


def _latest_two_closes(session: Session, tickers: List[str]) -> Dict[str, tuple]:
    """Return `{ticker: (latest_close, prev_close)}`. Either entry may be None
    if MarketData has insufficient rows for that ticker. Used to derive
    current_value / unrealized_pnl / daily_pnl for opt-in cost-basis positions."""
    out: Dict[str, tuple] = {}
    for ticker in tickers:
        rows = session.exec(
            select(MarketData.close)
            .where(MarketData.symbol == ticker)
            .order_by(MarketData.date.desc())
            .limit(2)
        ).all()
        latest = float(rows[0]) if len(rows) >= 1 else None
        prev = float(rows[1]) if len(rows) >= 2 else None
        out[ticker] = (latest, prev)
    return out


def _portfolio_to_dict(
    portfolio: Portfolio,
    positions: List[Position],
    session: Optional[Session] = None,
) -> dict:
    # Opt-in $ tracking: positions where the user has supplied cost_basis (and
    # quantity) get current_value / unrealized_pnl / daily_pnl. Weight-only
    # positions keep their existing shape, untouched.
    priced_tickers = [p.ticker for p in positions if p.cost_basis > 0 and p.quantity > 0]
    closes: Dict[str, tuple] = (
        _latest_two_closes(session, priced_tickers)
        if priced_tickers and session is not None
        else {}
    )

    assets: List[dict] = []
    total_cost_basis = 0.0
    total_current_value = 0.0
    total_daily_pnl = 0.0
    any_value_computed = False

    for p in positions:
        asset = {
            "ticker": p.ticker,
            "weight": p.weight,
            "quantity": p.quantity,
            "cost_basis": p.cost_basis,
            "asset_type": p.asset_type,
            "purchase_date": p.purchase_date.isoformat() if p.purchase_date else None,
        }
        if p.cost_basis > 0 and p.quantity > 0:
            latest, prev = closes.get(p.ticker, (None, None))
            if latest is not None:
                current_value = p.quantity * latest
                pnl = current_value - p.cost_basis
                asset["current_price"] = latest
                asset["current_value"] = current_value
                asset["unrealized_pnl"] = pnl
                asset["unrealized_pnl_pct"] = (pnl / p.cost_basis) if p.cost_basis else 0.0
                if prev is not None:
                    asset["daily_pnl"] = p.quantity * (latest - prev)
                    total_daily_pnl += asset["daily_pnl"]
                total_cost_basis += p.cost_basis
                total_current_value += current_value
                any_value_computed = True
        assets.append(asset)

    result = {
        "portfolio_id": portfolio.id,
        "user_id": portfolio.user_id,
        "name": portfolio.name,
        "assets": assets,
        "created_at": portfolio.created_at.isoformat(),
        "updated_at": portfolio.updated_at.isoformat(),
        "has_cost_basis_data": any(p.cost_basis > 0 for p in positions),
    }
    if any_value_computed:
        total_pnl = total_current_value - total_cost_basis
        result["totals"] = {
            "cost_basis": total_cost_basis,
            "current_value": total_current_value,
            "unrealized_pnl": total_pnl,
            "unrealized_pnl_pct": (total_pnl / total_cost_basis) if total_cost_basis else 0.0,
            "daily_pnl": total_daily_pnl,
        }
    return result

def _normalize_assets(assets: Optional[List[dict]]) -> List[dict]:
    if not assets:
        return []

    normalized: List[dict] = []
    seen = set()

    for item in assets:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="assets must be a list of objects")

        ticker = str(item.get("ticker", "")).strip().upper()
        if not ticker:
            raise HTTPException(status_code=400, detail="each asset must include a ticker")
        if ticker in seen:
            raise HTTPException(status_code=400, detail=f"duplicate ticker: {ticker}")
        seen.add(ticker)

        weight = float(item.get("weight", 0.0) or 0.0)
        if weight < 0:
            raise HTTPException(status_code=400, detail=f"negative weight for {ticker}")

        normalized.append({
            **item,
            "ticker": ticker,
            "weight": weight
        })

    total_weight = sum(a.get("weight", 0.0) for a in normalized)
    if total_weight > 0 and abs(total_weight - 1.0) > 0.01:
        raise HTTPException(status_code=400, detail="weights must sum to 1.0 (+/- 0.01)")

    return normalized


def _normalize_target_weights(
    target_weights: Optional[Dict[str, float]],
    known_tickers: Optional[List[str]] = None
) -> Optional[Dict[str, float]]:
    if not target_weights:
        return None

    normalized: Dict[str, float] = {}
    allowed = set(known_tickers or [])
    for ticker, weight in target_weights.items():
        canon = _canonical_symbol(ticker)
        val = float(weight or 0.0)
        if val < 0:
            raise HTTPException(status_code=400, detail=f"negative target weight for {canon}")
        if allowed and canon not in allowed:
            raise HTTPException(status_code=400, detail=f"target weight ticker not in portfolio: {canon}")
        normalized[canon] = val

    total_weight = sum(normalized.values())
    if total_weight > 0 and abs(total_weight - 1.0) > 0.01:
        raise HTTPException(status_code=400, detail="target_weights must sum to 1.0 (+/- 0.01)")

    if allowed:
        for ticker in allowed:
            normalized.setdefault(ticker, 0.0)

    return normalized


@app.get("/portfolios")
def list_portfolios(
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """
    List all portfolios for the current user.
    """
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        portfolios = session.exec(
            select(Portfolio).where(Portfolio.user_id == user.id).order_by(Portfolio.updated_at.desc())
        ).all()
        result = []
        for p in portfolios:
            positions = session.exec(
                select(Position).where(Position.portfolio_id == p.id)
            ).all()
            result.append(_portfolio_to_dict(p, positions, session=session))
        return {"items": result}


@app.post("/portfolios")
def create_portfolio(
    payload: PortfolioUpsertRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """
    Create a new portfolio with an auto-generated id.
    """
    if not payload.name:
        raise HTTPException(status_code=400, detail="name is required for new portfolio")

    now = datetime.utcnow()
    assets = _normalize_assets(payload.assets)
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        portfolio = Portfolio(user_id=user.id, name=payload.name, created_at=now, updated_at=now)
        session.add(portfolio)
        session.commit()
        session.refresh(portfolio)

        for item in assets:
            ticker = item.get("ticker")
            _ensure_asset(session, ticker)
            position = Position(
                portfolio_id=portfolio.id,
                ticker=ticker,
                weight=float(item.get("weight", 0.0) or 0.0),
                quantity=float(item.get("quantity", 0.0) or 0.0),
                cost_basis=float(item.get("cost_basis", 0.0) or 0.0),
                asset_type=item.get("asset_type") or "EQUITY"
            )
            session.add(position)

        session.commit()
        positions = session.exec(
            select(Position).where(Position.portfolio_id == portfolio.id)
        ).all()
        return _portfolio_to_dict(portfolio, positions, session=session)


@app.get("/portfolios/{portfolio_id}")
def get_portfolio(
    portfolio_id: str,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """
    Fetch a stored portfolio by id.
    """
    pid = _parse_portfolio_id(portfolio_id)
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        portfolio = session.exec(
            select(Portfolio).where(Portfolio.id == pid).where(Portfolio.user_id == user.id)
        ).first()
        if not portfolio:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        positions = session.exec(
            select(Position).where(Position.portfolio_id == pid)
        ).all()
        return _portfolio_to_dict(portfolio, positions, session=session)


@app.put("/portfolios/{portfolio_id}")
def upsert_portfolio(
    portfolio_id: str,
    payload: PortfolioUpsertRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """
    Create or update a portfolio.
    """
    pid = _parse_portfolio_id(portfolio_id)
    now = datetime.utcnow()
    assets = _normalize_assets(payload.assets) if payload.assets is not None else []
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        portfolio = session.exec(
            select(Portfolio).where(Portfolio.id == pid).where(Portfolio.user_id == user.id)
        ).first()
        if not portfolio:
            if not payload.name:
                raise HTTPException(status_code=400, detail="name is required for new portfolio")
            portfolio = Portfolio(id=pid, user_id=user.id, name=payload.name, created_at=now, updated_at=now)
            session.add(portfolio)
            session.commit()
            session.refresh(portfolio)
        else:
            if payload.name:
                portfolio.name = payload.name
            portfolio.updated_at = now

        # Replace positions
        existing_positions = session.exec(
            select(Position).where(Position.portfolio_id == pid)
        ).all()
        for pos in existing_positions:
            session.delete(pos)

        for item in assets:
            ticker = item.get("ticker")
            _ensure_asset(session, ticker)
            position = Position(
                portfolio_id=pid,
                ticker=ticker,
                weight=float(item.get("weight", 0.0) or 0.0),
                quantity=float(item.get("quantity", 0.0) or 0.0),
                cost_basis=float(item.get("cost_basis", 0.0) or 0.0),
                asset_type=item.get("asset_type") or "EQUITY"
            )
            session.add(position)

        session.commit()
        session.refresh(portfolio)
        positions = session.exec(
            select(Position).where(Position.portfolio_id == pid)
        ).all()
        return _portfolio_to_dict(portfolio, positions, session=session)


@app.delete("/portfolios/{portfolio_id}")
def delete_portfolio(
    portfolio_id: str,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """
    Delete a portfolio and its positions.
    """
    pid = _parse_portfolio_id(portfolio_id)
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        portfolio = session.exec(
            select(Portfolio).where(Portfolio.id == pid).where(Portfolio.user_id == user.id)
        ).first()
        if not portfolio:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        positions = session.exec(
            select(Position).where(Position.portfolio_id == pid)
        ).all()
        for pos in positions:
            session.delete(pos)
        session.delete(portfolio)
        session.commit()
        return {"deleted": True, "portfolio_id": pid}


@app.post("/portfolios/{portfolio_id}/forecast")
def forecast_portfolio_v2(
    portfolio_id: str,
    payload: PortfolioRequest,
    async_mode: bool = True,
    force_refresh: bool = False,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """
    Unified portfolio forecast endpoint.
    - async_mode=true (default): returns cached result or enqueues/polls via /jobs/{id}
    - async_mode=false: computes inline (DB-cached) and returns result envelope
    """
    try:
        pid = _parse_portfolio_id(portfolio_id)
        assets = payload.assets or []
        owner_user_id: int
        store_portfolio_runs: bool
        with Session(engine) as session:
            user = _require_user(session, user_id, x_user_id)
            owner_user_id = int(user.id)
            store_portfolio_runs = _portfolio_storage_enabled_for_user(session, owner_user_id)
            portfolio = session.exec(
                select(Portfolio).where(Portfolio.id == pid).where(Portfolio.user_id == user.id)
            ).first()
            if not portfolio:
                raise HTTPException(status_code=404, detail="Portfolio not found")
            if not assets:
                positions = session.exec(
                    select(Position).where(Position.portfolio_id == pid)
                ).all()
                assets = [{"ticker": p.ticker, "weight": p.weight} for p in positions]

        assets = _normalize_assets(assets)
        if not assets:
            raise HTTPException(status_code=400, detail="portfolio has no assets")
        scenario_defs = _scenario_to_dicts(payload.scenarios)
        target_weights = _normalize_target_weights(
            payload.target_weights,
            known_tickers=[a["ticker"] for a in assets],
        )

        if async_mode:
            submit = _enqueue_portfolio_forecast_job(
                owner_user_id=owner_user_id,
                entity_type="portfolio",
                entity_id=str(pid),
                portfolio_id=pid,
                assets=assets,
                horizon_days=payload.horizon_days,
                scenarios=scenario_defs,
                target_weights=target_weights,
                store_results=store_portfolio_runs,
                force_refresh=force_refresh,
            )
            submit["async_mode"] = True
            submit["storage_enabled"] = store_portfolio_runs
            return submit

        logger.info(
            "Processing portfolio %s inline: assets=%s horizon=%s force_refresh=%s",
            portfolio_id,
            len(assets),
            payload.horizon_days,
            force_refresh,
        )

        latest_market_dates: Dict[str, Optional[str]]
        input_hash: str
        cached_result: Optional[dict] = None
        parsed_dates: List[datetime] = []
        with Session(engine) as session:
            latest_market_dates = _portfolio_latest_market_dates(session, [a["ticker"] for a in assets])
            input_hash = _portfolio_forecast_input_hash(
                entity_type="portfolio",
                entity_id=str(pid),
                assets=assets,
                horizon_days=payload.horizon_days,
                scenarios=scenario_defs,
                target_weights=target_weights,
                latest_market_dates=latest_market_dates,
            )
            if store_portfolio_runs and not force_refresh:
                cached = _portfolio_forecast_cache_read(
                    session,
                    owner_user_id=owner_user_id,
                    entity_type="portfolio",
                    entity_id=str(pid),
                    input_hash=input_hash,
                )
                if cached:
                    cached_result = cached["result"]
            parsed_dates = [
                datetime.fromisoformat(v)
                for v in (latest_market_dates or {}).values()
                if isinstance(v, str) and v
            ]

        # Fallback: check PortfolioReportDataCache (populated by nightly batch)
        if cached_result is None and not force_refresh:
            try:
                with Session(engine) as session2:
                    report_cached = session2.exec(
                        select(PortfolioReportDataCache)
                        .where(PortfolioReportDataCache.portfolio_id == pid)
                        .order_by(PortfolioReportDataCache.updated_at.desc())
                    ).first()
                    if report_cached and report_cached.result_blob:
                        cached_result = _adapt_nightly_blob_to_ui(report_cached.result_blob, pid)
                        logger.info(f"Portfolio {pid} served from nightly batch cache")
            except Exception as e:
                logger.warning(f"Nightly cache read failed: {e}")

        if cached_result is not None:
            return {
                "mode": "cache",
                "async_mode": False,
                "cache_hit": True,
                "job_id": None,
                "job": None,
                "storage_enabled": True,
                "result": cached_result,
            }

        result = _compute_portfolio_forecast_result(
            portfolio_id=pid,
            assets=assets,
            horizon_days=payload.horizon_days,
            scenarios=scenario_defs,
            target_weights=target_weights,
        )
        result_blob = _json_compatible(result)
        data_last_date = max(parsed_dates) if parsed_dates else None
        request_payload = _json_compatible(
            {
                "owner_user_id": owner_user_id,
                "entity_type": "portfolio",
                "entity_id": str(pid),
                "portfolio_id": pid,
                "assets": assets,
                "horizon_days": int(payload.horizon_days),
                "scenarios": scenario_defs or [],
                "target_weights": target_weights or {},
                "input_hash": input_hash,
                "latest_market_dates": latest_market_dates,
                "execution_mode": "inline",
            }
        )
        cache_row = None
        if store_portfolio_runs:
            try:
                with Session(engine) as session:
                    cache_row = _portfolio_forecast_cache_write(
                        session,
                        owner_user_id=owner_user_id,
                        entity_type="portfolio",
                        entity_id=str(pid),
                        horizon_days=payload.horizon_days,
                        input_hash=input_hash,
                        data_last_date=data_last_date,
                        request_payload=request_payload,
                        result_blob=result_blob,
                    )
            except Exception as e:
                logger.warning(f"Inline portfolio forecast cache write failed: {e}")

        return {
            "mode": "live",
            "async_mode": False,
            "cache_hit": False,
            "job_id": None,
            "job": None,
            "storage_enabled": store_portfolio_runs,
            "result": _portfolio_forecast_result_with_cache_meta(
                result_blob,
                cache_row,
                persisted=bool(store_portfolio_runs and cache_row),
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Portfolio forecast failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/jobs/{job_id}")
def get_forecast_job(
    job_id: str,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        return _get_forecast_job_response(session, owner_user_id=user.id, job_id=job_id)


@app.post("/portfolios/{portfolio_id}/simulate_quantum_risk")
def simulate_portfolio_quantum_risk(
    portfolio_id: str,
    payload: PortfolioQuantumRiskRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """
    Runs quantum Monte Carlo on a synthetic portfolio price series.
    Uses stored portfolio holdings when payload.assets is omitted.
    """
    try:
        pid = _parse_portfolio_id(portfolio_id)
        assets = payload.assets or []
        store_portfolio_runs = True
        with Session(engine) as session:
            user = _require_user(session, user_id, x_user_id)
            portfolio = session.exec(
                select(Portfolio).where(Portfolio.id == pid).where(Portfolio.user_id == user.id)
            ).first()
            if not portfolio:
                raise HTTPException(status_code=404, detail="Portfolio not found")
            store_portfolio_runs = _portfolio_storage_enabled_for_user(session, int(user.id))
            if not assets:
                positions = session.exec(
                    select(Position).where(Position.portfolio_id == pid)
                ).all()
                assets = [{"ticker": p.ticker, "weight": p.weight} for p in positions]

        assets = _normalize_assets(assets)
        if not assets:
            raise HTTPException(status_code=400, detail="assets are required")

        # Try to serve from any existing cache before computing
        if store_portfolio_runs:
            try:
                with Session(engine) as session:
                    any_cached = _get_simulation_cache_result(
                        session,
                        entity_type="portfolio",
                        entity_id=str(pid),
                        method="quantum_vqmc",
                        input_hash="",  # empty to skip exact match
                    )
                    if not any_cached:
                        # Try any cached result for this portfolio regardless of hash
                        from app.db.models import RiskSimulationCache as RSC
                        any_row = session.exec(
                            select(RSC)
                            .where(RSC.entity_type == "portfolio")
                            .where(RSC.entity_id == str(pid))
                            .where(RSC.method == "quantum_vqmc")
                            .order_by(RSC.created_at.desc())
                        ).first()
                        if any_row and any_row.result_blob:
                            logger.info(f"Serving cached quantum risk for portfolio {pid}")
                            result = copy.deepcopy(any_row.result_blob)
                            result["cache"] = {"hit": True, "cache_type": "nightly_batch"}
                            return result
                    elif any_cached:
                        logger.info(f"Serving cached quantum risk for portfolio {pid}")
                        return any_cached
            except Exception as e:
                logger.warning(f"Quantum risk cache read failed: {e}")

        logger.info(f"Computing portfolio quantum risk for portfolio {pid}: {len(assets)} assets")
        manager = PortfolioManager(assets)
        synthetic_bundle = manager.build_synthetic_history()
        if synthetic_bundle.get("error"):
            raise HTTPException(status_code=404, detail=synthetic_bundle["error"])

        synthetic_prices = synthetic_bundle.get("synthetic_prices", []) or []
        synthetic_dates = synthetic_bundle.get("synthetic_dates", []) or []
        if len(synthetic_prices) < 100:
            raise HTTPException(status_code=400, detail="Insufficient synthetic history for quantum simulation")

        horizon_days = int(payload.horizon_days)
        n_simulations = int(payload.n_simulations)
        random_seed = int(payload.random_seed) if payload.random_seed is not None else None
        data_last_date = datetime.fromisoformat(synthetic_dates[-1]) if synthetic_dates else None
        input_hash = _stable_json_hash(
            {
                "portfolio_id": pid,
                "method": "quantum_vqmc",
                "assets": assets,
                "horizon_days": horizon_days,
                "n_simulations": n_simulations,
                "random_seed": random_seed,
                # Hash synthetic series so cache invalidates when market data changes.
                "synthetic_prices": [round(float(p), 8) for p in synthetic_prices],
            }
        )

        if store_portfolio_runs:
            try:
                with Session(engine) as session:
                    cached = _get_simulation_cache_result(
                        session,
                        entity_type="portfolio",
                        entity_id=str(pid),
                        method="quantum_vqmc",
                        input_hash=input_hash,
                    )
                if cached:
                    return cached
            except Exception as e:
                logger.warning(f"Portfolio quantum cache read failed: {e}")

        # Portfolio-level VQMC: synthesise a ticker id from the portfolio id so the
        # trained module caches parameters per-portfolio-portfolio rather than per-asset.
        result = simulate_trained_vqmc(
            historical_prices=synthetic_prices,
            ticker=f"PORTFOLIO_{pid}",
            horizon_days=horizon_days,
            n_simulations=n_simulations,
            random_seed=random_seed,
        )
        result["portfolio_id"] = pid
        result["holdings"] = assets
        result["history"] = {
            "dates": synthetic_dates,
            "prices": synthetic_prices,
        }
        if synthetic_dates and synthetic_prices:
            result["history_summary"] = {
                "points": len(synthetic_prices),
                "start_date": synthetic_dates[0],
                "end_date": synthetic_dates[-1],
                "start_price": float(synthetic_prices[0]),
                "end_price": float(synthetic_prices[-1]),
            }
        result["cache"] = {
            "hit": False,
            "cache_type": "risk_simulation",
            "input_hash": input_hash,
            "method": "quantum_vqmc",
            "persisted": bool(store_portfolio_runs),
        }

        if store_portfolio_runs:
            try:
                with Session(engine) as session:
                    _save_simulation_cache_result(
                        session,
                        entity_type="portfolio",
                        entity_id=str(pid),
                        method="quantum_vqmc",
                        horizon_days=horizon_days,
                        n_simulations=n_simulations,
                        random_seed=random_seed,
                        input_hash=input_hash,
                        data_last_date=data_last_date,
                        result_blob=result,
                    )
            except Exception as e:
                logger.warning(f"Portfolio quantum cache write failed: {e}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Portfolio quantum simulation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/portfolios/{portfolio_id}/quantum_rebalance")
def quantum_rebalance_portfolio(
    portfolio_id: str,
    payload: PortfolioQuantumRebalanceRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """Quantum-optimised asset selection via QAOA + CVaR (Qiskit Finance).

    Formulates mean-variance selection as a QUBO and solves it on a quantum
    sampler (local simulator or IBM Runtime QPU, controlled by QUANTUM_BACKEND).
    """
    try:
        pid = _parse_portfolio_id(portfolio_id)
        assets = payload.assets or []
        with Session(engine) as session:
            user = _require_user(session, user_id, x_user_id)
            portfolio = session.exec(
                select(Portfolio).where(Portfolio.id == pid).where(Portfolio.user_id == user.id)
            ).first()
            if not portfolio:
                raise HTTPException(status_code=404, detail="Portfolio not found")
            if not assets:
                positions = session.exec(
                    select(Position).where(Position.portfolio_id == pid)
                ).all()
                assets = [{"ticker": p.ticker, "weight": p.weight} for p in positions]

        assets = _normalize_assets(assets)
        if len(assets) < 2:
            raise HTTPException(status_code=400, detail="Need at least 2 assets for quantum rebalance")

        manager = PortfolioManager(assets)
        data_map, _ = manager._fetch_batch_data()
        if len(data_map) < 2:
            raise HTTPException(status_code=404, detail="Insufficient market data for quantum rebalance")

        result = quantum_optimise_portfolio(
            data_map=data_map,
            tickers=manager.tickers,
            budget=payload.budget,
            risk_factor=payload.risk_factor,
            reps=payload.qaoa_reps,
            cvar_alpha=payload.cvar_alpha,
            seed=payload.random_seed,
        )
        result["portfolio_id"] = pid
        result["current_holdings"] = assets
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quantum rebalance failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/portfolios/{portfolio_id}/quantum_regime")
def quantum_regime_portfolio(
    portfolio_id: str,
    payload: PortfolioQuantumRegimeRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """Classify the portfolio's current volatility regime via a quantum-kernel SVC."""
    try:
        pid = _parse_portfolio_id(portfolio_id)
        assets = payload.assets or []
        with Session(engine) as session:
            user = _require_user(session, user_id, x_user_id)
            portfolio = session.exec(
                select(Portfolio).where(Portfolio.id == pid).where(Portfolio.user_id == user.id)
            ).first()
            if not portfolio:
                raise HTTPException(status_code=404, detail="Portfolio not found")
            if not assets:
                positions = session.exec(
                    select(Position).where(Position.portfolio_id == pid)
                ).all()
                assets = [{"ticker": p.ticker, "weight": p.weight} for p in positions]

        assets = _normalize_assets(assets)
        if not assets:
            raise HTTPException(status_code=400, detail="assets are required")

        manager = PortfolioManager(assets)
        synthetic = manager.build_synthetic_history()
        if synthetic.get("error"):
            raise HTTPException(status_code=404, detail=synthetic["error"])
        prices = pd.Series(
            synthetic["synthetic_prices"],
            index=pd.to_datetime(synthetic["synthetic_dates"]),
        )

        result = quantum_regime_classify(
            prices=prices,
            n_qubits=payload.n_qubits,
            reps=payload.feature_map_reps,
            train_points=payload.train_points,
        )
        result["portfolio_id"] = pid
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quantum regime classification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/portfolios/{portfolio_id}/quantum_systemic_risk")
def quantum_systemic_risk_portfolio(
    portfolio_id: str,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """Quantum-information systemic-risk metrics for a portfolio.

    Reports correlation-matrix von Neumann entropy (spectral diversification)
    and portfolio entanglement entropy (amplitude-encoded weight state).
    """
    try:
        pid = _parse_portfolio_id(portfolio_id)
        with Session(engine) as session:
            user = _require_user(session, user_id, x_user_id)
            portfolio = session.exec(
                select(Portfolio).where(Portfolio.id == pid).where(Portfolio.user_id == user.id)
            ).first()
            if not portfolio:
                raise HTTPException(status_code=404, detail="Portfolio not found")
            positions = session.exec(
                select(Position).where(Position.portfolio_id == pid)
            ).all()
            assets = [{"ticker": p.ticker, "weight": p.weight} for p in positions]

        assets = _normalize_assets(assets)
        if len(assets) < 2:
            raise HTTPException(status_code=400, detail="Need at least 2 assets for systemic-risk metrics")

        manager = PortfolioManager(assets)
        data_map, _ = manager._fetch_batch_data()
        if len(data_map) < 2:
            raise HTTPException(status_code=404, detail="Insufficient market data for systemic-risk metrics")

        weights = {a["ticker"]: float(a["weight"]) for a in assets}
        report = systemic_risk_report(data_map=data_map, weights=weights)
        report["portfolio_id"] = pid
        return report
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quantum systemic risk failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/portfolios/{portfolio_id}/tensor_network_risk")
def tensor_network_risk_portfolio(
    portfolio_id: str,
    payload: PortfolioTensorNetworkRiskRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """Quantum-inspired tensor-network (MPS) Monte Carlo for portfolio risk."""
    try:
        pid = _parse_portfolio_id(portfolio_id)
        assets = payload.assets or []
        with Session(engine) as session:
            user = _require_user(session, user_id, x_user_id)
            portfolio = session.exec(
                select(Portfolio).where(Portfolio.id == pid).where(Portfolio.user_id == user.id)
            ).first()
            if not portfolio:
                raise HTTPException(status_code=404, detail="Portfolio not found")
            if not assets:
                positions = session.exec(
                    select(Position).where(Position.portfolio_id == pid)
                ).all()
                assets = [{"ticker": p.ticker, "weight": p.weight} for p in positions]

        assets = _normalize_assets(assets)
        if len(assets) < 2:
            raise HTTPException(status_code=400, detail="Need at least 2 assets for tensor-network risk")
        if len(assets) > 6:
            raise HTTPException(status_code=400, detail="Current MPS fit is only feasible for up to 6 assets")

        manager = PortfolioManager(assets)
        data_map, _ = manager._fetch_batch_data()
        if len(data_map) < 2:
            raise HTTPException(status_code=404, detail="Insufficient market data for tensor-network risk")

        weights = {a["ticker"]: float(a["weight"]) for a in assets}
        result = tensor_network_risk(
            data_map=data_map,
            weights=weights,
            horizon_days=payload.horizon_days,
            n_simulations=payload.n_simulations,
            d=payload.physical_dim,
            chi=payload.bond_dim,
            random_seed=payload.random_seed,
        )
        result["portfolio_id"] = pid
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tensor-network risk failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/portfolios/{portfolio_id}/var_backtest")
def var_backtest_portfolio(
    portfolio_id: str,
    payload: VarBacktestRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """Backtest portfolio VaR 95 by as-of replay, scored with Kupiec POF +
    Christoffersen coverage tests. Uses stored holdings when assets omitted.

    method="mps_fan" refits the MPS-copula fan each day (heavy, ~tens of
    seconds — cached); method="historical" is an instant empirical-percentile
    cross-check. Result is cached in RiskSimulationCache keyed on the inputs +
    latest market dates, so identical re-runs are free.
    """
    try:
        pid = _parse_portfolio_id(portfolio_id)
        assets = payload.assets or []
        store_portfolio_runs = True
        with Session(engine) as session:
            user = _require_user(session, user_id, x_user_id)
            portfolio = session.exec(
                select(Portfolio).where(Portfolio.id == pid).where(Portfolio.user_id == user.id)
            ).first()
            if not portfolio:
                raise HTTPException(status_code=404, detail="Portfolio not found")
            store_portfolio_runs = _portfolio_storage_enabled_for_user(session, int(user.id))
            if not assets:
                positions = session.exec(
                    select(Position).where(Position.portfolio_id == pid)
                ).all()
                assets = [
                    {"ticker": p.ticker, "weight": p.weight, "quantity": p.quantity,
                     "purchase_date": p.purchase_date.isoformat() if p.purchase_date else None}
                    for p in positions
                ]

        assets = _normalize_assets(assets)
        if not assets:
            raise HTTPException(status_code=400, detail="assets are required")

        method = str(payload.method)
        confidence = float(payload.confidence)
        horizon_days = int(payload.horizon_days)
        est_window = int(payload.est_window)
        n_backtest = int(payload.n_backtest)
        n_simulations = int(payload.n_simulations)
        random_seed = int(payload.random_seed) if payload.random_seed is not None else None
        weight_mode = str(payload.weight_mode)
        # Effective mode drives the cache key: a weight-only portfolio that requests
        # drift falls back to constant AND still hits the constant (prewarmed) cache.
        eff_mode = effective_weight_mode(weight_mode, assets)
        cache_method = f"var_backtest_{method}" + ("_drift" if eff_mode == "drift" else "")
        # Keep the constant hash on the minimal {ticker,weight} shape (back-compat with
        # already-cached runs); include quantity/purchase_date only when drift uses them.
        hash_assets = assets if eff_mode == "drift" else [
            {"ticker": a["ticker"], "weight": a["weight"]} for a in assets
        ]

        with Session(engine) as session:
            latest_market_dates = _portfolio_latest_market_dates(
                session, [a["ticker"] for a in assets]
            )
        input_hash = _stable_json_hash(
            {
                "portfolio_id": pid,
                "method": cache_method,
                "assets": hash_assets,
                "confidence": confidence,
                "horizon_days": horizon_days,
                "est_window": est_window,
                "n_backtest": n_backtest,
                "n_simulations": n_simulations,
                "random_seed": random_seed,
                # Hash latest market dates so cache invalidates as new data lands.
                "latest_market_dates": latest_market_dates,
            }
        )

        if store_portfolio_runs:
            try:
                with Session(engine) as session:
                    cached = _get_simulation_cache_result(
                        session,
                        entity_type="portfolio",
                        entity_id=str(pid),
                        method=cache_method,
                        input_hash=input_hash,
                    )
                if cached:
                    return cached
            except Exception as e:
                logger.warning(f"VaR backtest cache read failed: {e}")

        logger.info(f"Computing VaR backtest for portfolio {pid}: method={method}, {len(assets)} assets")
        result = run_portfolio_var_backtest(
            assets=assets,
            confidence=confidence,
            horizon_days=horizon_days,
            est_window=est_window,
            n_backtest=n_backtest,
            method=method,
            n_simulations=n_simulations,
            random_seed=random_seed,
            weight_mode=weight_mode,
        )
        result = _json_compatible(result)
        result["portfolio_id"] = pid
        result["cache"] = {
            "hit": False,
            "cache_type": "risk_simulation",
            "input_hash": input_hash,
            "method": cache_method,
            "persisted": bool(store_portfolio_runs),
        }

        if store_portfolio_runs:
            try:
                with Session(engine) as session:
                    _save_simulation_cache_result(
                        session,
                        entity_type="portfolio",
                        entity_id=str(pid),
                        method=cache_method,
                        horizon_days=horizon_days,
                        n_simulations=n_simulations,
                        random_seed=random_seed,
                        input_hash=input_hash,
                        data_last_date=None,
                        result_blob=result,
                    )
            except Exception as e:
                logger.warning(f"VaR backtest cache write failed: {e}")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        # data/shape problems (too little history, <2 assets, etc.) are client-actionable
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"VaR backtest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/portfolios/{portfolio_id}/var_backtest_compare")
def var_backtest_compare_portfolio(
    portfolio_id: str,
    payload: VarBacktestCompareRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    """Compare VaR 95 methods side by side over the SAME backtest window:
    historical, parametric (normal/vol-based), and an MPS physical-dim sweep
    (d=4, d=8). Answers "which volatility model passes VaR 95" and shows whether
    finer MPS binning fixes the anti-conservative d=4 tails. Heavy (refits the
    MPS fan per day for each d) — cached in RiskSimulationCache.
    """
    try:
        pid = _parse_portfolio_id(portfolio_id)
        assets = payload.assets or []
        store_portfolio_runs = True
        with Session(engine) as session:
            user = _require_user(session, user_id, x_user_id)
            portfolio = session.exec(
                select(Portfolio).where(Portfolio.id == pid).where(Portfolio.user_id == user.id)
            ).first()
            if not portfolio:
                raise HTTPException(status_code=404, detail="Portfolio not found")
            store_portfolio_runs = _portfolio_storage_enabled_for_user(session, int(user.id))
            if not assets:
                positions = session.exec(
                    select(Position).where(Position.portfolio_id == pid)
                ).all()
                assets = [
                    {"ticker": p.ticker, "weight": p.weight, "quantity": p.quantity,
                     "purchase_date": p.purchase_date.isoformat() if p.purchase_date else None}
                    for p in positions
                ]

        assets = _normalize_assets(assets)
        if not assets:
            raise HTTPException(status_code=400, detail="assets are required")

        confidence = float(payload.confidence)
        horizon_days = int(payload.horizon_days)
        est_window = int(payload.est_window)
        n_backtest = int(payload.n_backtest)
        n_simulations = int(payload.n_simulations)
        random_seed = int(payload.random_seed) if payload.random_seed is not None else None
        weight_mode = str(payload.weight_mode)
        eff_mode = effective_weight_mode(weight_mode, assets)
        cache_method = "var_backtest_compare" + ("_drift" if eff_mode == "drift" else "")
        hash_assets = assets if eff_mode == "drift" else [
            {"ticker": a["ticker"], "weight": a["weight"]} for a in assets
        ]

        with Session(engine) as session:
            latest_market_dates = _portfolio_latest_market_dates(
                session, [a["ticker"] for a in assets]
            )
        input_hash = _stable_json_hash(
            {
                "portfolio_id": pid,
                "method": cache_method,
                "assets": hash_assets,
                "confidence": confidence,
                "horizon_days": horizon_days,
                "est_window": est_window,
                "n_backtest": n_backtest,
                "n_simulations": n_simulations,
                "random_seed": random_seed,
                "latest_market_dates": latest_market_dates,
            }
        )

        if store_portfolio_runs:
            try:
                with Session(engine) as session:
                    cached = _get_simulation_cache_result(
                        session,
                        entity_type="portfolio",
                        entity_id=str(pid),
                        method=cache_method,
                        input_hash=input_hash,
                    )
                if cached:
                    return cached
            except Exception as e:
                logger.warning(f"VaR backtest compare cache read failed: {e}")

        logger.info(f"Computing VaR backtest comparison for portfolio {pid}: {len(assets)} assets")
        result = run_portfolio_var_backtest_comparison(
            assets=assets,
            confidence=confidence,
            horizon_days=horizon_days,
            est_window=est_window,
            n_backtest=n_backtest,
            n_simulations=n_simulations,
            random_seed=random_seed,
            weight_mode=weight_mode,
        )
        result = _json_compatible(result)
        result["portfolio_id"] = pid
        result["cache"] = {
            "hit": False,
            "cache_type": "risk_simulation",
            "input_hash": input_hash,
            "method": cache_method,
            "persisted": bool(store_portfolio_runs),
        }

        if store_portfolio_runs:
            try:
                with Session(engine) as session:
                    _save_simulation_cache_result(
                        session,
                        entity_type="portfolio",
                        entity_id=str(pid),
                        method=cache_method,
                        horizon_days=horizon_days,
                        n_simulations=n_simulations,
                        random_seed=random_seed,
                        input_hash=input_hash,
                        data_last_date=None,
                        result_blob=result,
                    )
            except Exception as e:
                logger.warning(f"VaR backtest compare cache write failed: {e}")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"VaR backtest comparison failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/quantum/train_ansatz")
def train_quantum_ansatz(payload: QuantumRiskRequest):
    """Train and persist a per-ticker VQMC ansatz on the supplied historical prices."""
    try:
        result = train_vqmc_ansatz(
            historical_prices=payload.prices,
            ticker=payload.ticker,
            maxiter=75,
            seed=payload.random_seed,
        )
        return result
    except Exception as e:
        logger.error(f"Ansatz training failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/quantum/qrc/retune")
def qrc_retune(payload: QRCRetuneRequest):
    """Weekly re-tune job: run QRC auto-tune per ticker and persist the best config.

    Kept out of the nightly batch — HybridForecaster reads from the cache and
    fits in ~3s per asset. This endpoint is the slow weekly path. Each ticker is
    independent; a future worker-pool wrapper can parallelise across tickers
    (CPU-bound numpy — ProcessPoolExecutor preferred over Threads due to the GIL).
    """
    results: List[Dict[str, Any]] = []
    for ticker in payload.tickers:
        try:
            raw = get_price_series_cached(ticker, period=payload.period)
            prices = [float(row["price"]) for row in (raw or []) if row.get("price") is not None]
            if len(prices) < 80:
                results.append({"ticker": ticker, "ok": False, "error": f"Insufficient history ({len(prices)} points)"})
                continue
            saved = qrc_retune_and_save(ticker, prices)
            results.append({"ticker": ticker, "ok": True, "payload": saved})
        except Exception as e:
            logger.exception("QRC retune failed for %s", ticker)
            results.append({"ticker": ticker, "ok": False, "error": str(e)})
    return {"retuned": results, "n_tickers": len(payload.tickers)}


@app.get("/quantum/qrc/cached")
def qrc_cached_tickers():
    return {"cached": qrc_list_cached_tickers()}


@app.get("/quantum/qrc/cached/{ticker}")
def qrc_cached_config(ticker: str):
    raw = get_price_series_cached(ticker, period="2y")
    n_points = len([row for row in (raw or []) if row.get("price") is not None])
    loaded = qrc_load_cached_config(ticker, current_n_points=n_points)
    return {
        "ticker": ticker,
        "source": loaded["source"],
        "stale_triggers": loaded["stale_triggers"],
        "cached_payload": loaded["payload"],
    }


@app.post("/quantum/reservoir_forecast")
def quantum_reservoir_forecast(payload: QuantumReservoirForecastRequest):
    """Quantum Reservoir Computing one-step-ahead forecaster with auto-tune."""
    try:
        cfg = None
        if not payload.auto_tune:
            cfg = QRCConfig(
                n_qubits=int(payload.n_qubits or 6),
                reservoir_depth=int(payload.reservoir_depth or 2),
                input_scale=float(payload.input_scale if payload.input_scale is not None else 1.0),
                ridge_alpha=float(payload.ridge_alpha if payload.ridge_alpha is not None else 1e-2),
                leak_rate=float(payload.leak_rate if payload.leak_rate is not None else 0.0),
                washout_steps=int(payload.washout_steps if payload.washout_steps is not None else 50),
            )
        result = fit_forecast_qrc(
            prices=payload.prices,
            horizon=payload.horizon_days,
            auto_tune=payload.auto_tune,
            config=cfg,
        )
        result["ticker"] = payload.ticker
        return result
    except Exception as e:
        logger.error(f"QRC forecast failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/quantum/benchmark/run")
def run_quantum_benchmark(payload: QuantumBenchmarkRequest):
    """Execute the full benchmark suite (local + IBM if credentials are set) and persist the report."""
    try:
        return run_full_benchmark(universe=payload.universe, save=payload.save)
    except Exception as e:
        logger.error(f"Quantum benchmark failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/quantum/benchmark/runs")
def list_quantum_benchmark_runs():
    return {"runs": list_benchmark_runs()}


@app.get("/quantum/benchmark/runs/{run_id}")
def get_quantum_benchmark_run(run_id: str):
    doc = get_benchmark_run(run_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    return doc


# -------------------------------------------------------------------
# Users API
# -------------------------------------------------------------------

@app.post("/users")
def create_user(payload: UserCreateRequest):
    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email is required")

    with Session(engine) as session:
        existing = session.exec(select(User).where(User.email == email)).first()
        if existing:
            return existing
        now = datetime.utcnow()
        user = User(email=email, is_active=True, created_at=now, updated_at=now)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


@app.get("/users/{user_id}")
def get_user(user_id: int):
    with Session(engine) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user


@app.get("/users/{user_id}/storage-preferences")
def get_user_storage_preferences(user_id: int):
    with Session(engine) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        pref = _get_user_storage_preference(session, user_id)
        return {
            "user_id": int(user_id),
            "store_portfolio_runs": bool(pref["store_portfolio_runs"]),
            "source": pref["source"],
            "updated_at": pref["updated_at"],
        }


@app.put("/users/{user_id}/storage-preferences")
def set_user_storage_preferences(user_id: int, payload: UserStoragePreferenceRequest):
    with Session(engine) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        row = _set_user_storage_preference(
            session,
            user_id=user_id,
            store_portfolio_runs=bool(payload.store_portfolio_runs),
        )
        return {
            "user_id": int(user_id),
            "store_portfolio_runs": bool(row.store_portfolio_runs),
            "source": "user",
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


@app.get("/users")
def list_users(active_only: bool = True):
    with Session(engine) as session:
        query = select(User)
        if active_only:
            query = query.where(User.is_active == True)  # noqa: E712
        users = session.exec(query.order_by(User.id.asc())).all()
        return {"items": users}


# -------------------------------------------------------------------
# Watchlists API
# -------------------------------------------------------------------

@app.get("/watchlists")
def list_watchlists(
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        watchlists = session.exec(
            select(Watchlist)
            .where(Watchlist.user_id == user.id)
            .where(Watchlist.name != SAVED_ASSETS_WATCHLIST_NAME)
            .order_by(Watchlist.updated_at.desc())
        ).all()
        response = []
        for watchlist in watchlists:
            items = session.exec(
                select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id)
            ).all()
            response.append(_watchlist_to_dict(watchlist, items))
        return {"items": response}


@app.post("/watchlists")
def create_watchlist(
    payload: WatchlistRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    now = datetime.utcnow()
    tickers = [_canonical_symbol(t) for t in payload.tickers]
    unique = []
    seen = set()
    for t in tickers:
        if t and t not in seen:
            unique.append(t)
            seen.add(t)

    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        watchlist = Watchlist(user_id=user.id, name=payload.name, created_at=now, updated_at=now)
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)

        for ticker in unique:
            _ensure_asset(session, ticker)
            session.add(WatchlistItem(watchlist_id=watchlist.id, ticker=ticker))

        session.commit()
        items = session.exec(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id)
        ).all()
        return _watchlist_to_dict(watchlist, items)


@app.get("/watchlists/{watchlist_id}")
def get_watchlist(
    watchlist_id: int,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        watchlist = session.exec(
            select(Watchlist).where(Watchlist.id == watchlist_id).where(Watchlist.user_id == user.id)
        ).first()
        if not watchlist:
            raise HTTPException(status_code=404, detail="Watchlist not found")
        items = session.exec(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist_id)
        ).all()
        return _watchlist_to_dict(watchlist, items)


@app.put("/watchlists/{watchlist_id}")
def update_watchlist(
    watchlist_id: int,
    payload: WatchlistUpdateRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        watchlist = session.exec(
            select(Watchlist).where(Watchlist.id == watchlist_id).where(Watchlist.user_id == user.id)
        ).first()
        if not watchlist:
            raise HTTPException(status_code=404, detail="Watchlist not found")

        if payload.name is not None:
            watchlist.name = payload.name

        if payload.tickers is not None:
            existing = session.exec(
                select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist_id)
            ).all()
            for item in existing:
                session.delete(item)

            tickers = [_canonical_symbol(t) for t in payload.tickers]
            unique = []
            seen = set()
            for t in tickers:
                if t and t not in seen:
                    unique.append(t)
                    seen.add(t)

            for ticker in unique:
                _ensure_asset(session, ticker)
                session.add(WatchlistItem(watchlist_id=watchlist.id, ticker=ticker))

        watchlist.updated_at = datetime.utcnow()
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)

        items = session.exec(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist_id)
        ).all()
        return _watchlist_to_dict(watchlist, items)


@app.delete("/watchlists/{watchlist_id}")
def delete_watchlist(
    watchlist_id: int,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        watchlist = session.exec(
            select(Watchlist).where(Watchlist.id == watchlist_id).where(Watchlist.user_id == user.id)
        ).first()
        if not watchlist:
            raise HTTPException(status_code=404, detail="Watchlist not found")
        items = session.exec(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist_id)
        ).all()
        for item in items:
            session.delete(item)
        session.delete(watchlist)
        session.commit()
        return {"deleted": True, "watchlist_id": watchlist_id}


@app.get("/saved-assets")
def list_saved_assets(
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        wl = _get_or_create_saved_watchlist(session, user)
        items = session.exec(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)
        ).all()
        return {"tickers": [item.ticker for item in items]}


@app.post("/saved-assets")
def add_saved_asset(
    payload: dict,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    ticker = _canonical_symbol(str(payload.get("ticker", "")))
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        wl = _get_or_create_saved_watchlist(session, user)
        existing = session.exec(
            select(WatchlistItem)
            .where(WatchlistItem.watchlist_id == wl.id)
            .where(WatchlistItem.ticker == ticker)
        ).first()
        if not existing:
            _ensure_asset(session, ticker)
            session.add(WatchlistItem(watchlist_id=wl.id, ticker=ticker))
            wl.updated_at = datetime.utcnow()
            session.add(wl)
            session.commit()
        items = session.exec(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)
        ).all()
        return {"tickers": [item.ticker for item in items]}


@app.delete("/saved-assets/{ticker}")
def remove_saved_asset(
    ticker: str,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    canon = _canonical_symbol(ticker)
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        wl = _get_or_create_saved_watchlist(session, user)
        row = session.exec(
            select(WatchlistItem)
            .where(WatchlistItem.watchlist_id == wl.id)
            .where(WatchlistItem.ticker == canon)
        ).first()
        if row:
            session.delete(row)
            wl.updated_at = datetime.utcnow()
            session.add(wl)
            session.commit()
        items = session.exec(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)
        ).all()
        return {"tickers": [item.ticker for item in items]}


@app.get("/watchlists/{watchlist_id}/snapshot")
def get_watchlist_snapshot(
    watchlist_id: int,
    period: str = "3mo",
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        watchlist = session.exec(
            select(Watchlist).where(Watchlist.id == watchlist_id).where(Watchlist.user_id == user.id)
        ).first()
        if not watchlist:
            raise HTTPException(status_code=404, detail="Watchlist not found")
        items = session.exec(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist_id)
        ).all()

    rows = []
    for item in items:
        ticker = item.ticker
        prices = get_price_series_cached(ticker, period=period)
        fundamentals = get_fundamentals_cached(ticker)
        close_prices = [float(x["price"]) for x in prices] if prices else []
        latest = close_prices[-1] if close_prices else None
        prev = close_prices[-2] if len(close_prices) >= 2 else None
        change_1d = ((latest / prev) - 1) if latest is not None and prev and prev != 0 else None
        ret = pd.Series(close_prices).pct_change().dropna() if len(close_prices) >= 2 else pd.Series(dtype=float)
        vol_30d = float(ret.tail(30).std() * (252 ** 0.5)) if len(ret) > 0 else None

        rows.append({
            "ticker": ticker,
            "latest_price": latest,
            "change_1d": change_1d,
            "vol_30d": vol_30d,
            "market_cap": (fundamentals.get("valuation", {}) or {}).get("market_cap"),
            "pe_ratio": (fundamentals.get("valuation", {}) or {}).get("pe_ratio"),
            "sparkline": close_prices[-30:] if close_prices else [],
        })

    return {"watchlist_id": watchlist_id, "items": rows}


# -------------------------------------------------------------------
# Alerts API
# -------------------------------------------------------------------

@app.get("/alerts")
def list_alerts(
    active_only: bool = True,
    watchlist_id: Optional[int] = None,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        query = select(AlertRule)
        query = query.where(AlertRule.user_id == user.id)
        if active_only:
            query = query.where(AlertRule.is_active == True)  # noqa: E712
        if watchlist_id is not None:
            query = query.where(AlertRule.watchlist_id == watchlist_id)
        alerts = session.exec(query.order_by(AlertRule.updated_at.desc())).all()
        return {"items": alerts}


@app.post("/alerts")
def create_alert(
    payload: AlertRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    ticker = _canonical_symbol(payload.ticker)
    now = datetime.utcnow()
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        _ensure_asset(session, ticker)
        if payload.watchlist_id is not None:
            watchlist = session.exec(
                select(Watchlist)
                .where(Watchlist.id == payload.watchlist_id)
                .where(Watchlist.user_id == user.id)
            ).first()
            if not watchlist:
                raise HTTPException(status_code=404, detail="Watchlist not found")

        alert = AlertRule(
            user_id=user.id,
            name=payload.name,
            ticker=ticker,
            watchlist_id=payload.watchlist_id,
            alert_type=payload.alert_type,
            direction=payload.direction,
            threshold_value=float(payload.threshold_value),
            lookback_days=int(payload.lookback_days),
            is_active=bool(payload.is_active),
            extra_config=payload.extra_config or {},
            created_at=now,
            updated_at=now,
        )
        session.add(alert)
        session.commit()
        session.refresh(alert)
        return alert


@app.put("/alerts/{alert_id}")
def update_alert(
    alert_id: int,
    payload: AlertUpdateRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        alert = session.exec(
            select(AlertRule).where(AlertRule.id == alert_id).where(AlertRule.user_id == user.id)
        ).first()
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        if payload.name is not None:
            alert.name = payload.name
        if payload.direction is not None:
            alert.direction = payload.direction
        if payload.threshold_value is not None:
            alert.threshold_value = float(payload.threshold_value)
        if payload.lookback_days is not None:
            alert.lookback_days = int(payload.lookback_days)
        if payload.is_active is not None:
            alert.is_active = bool(payload.is_active)
        if payload.extra_config is not None:
            alert.extra_config = payload.extra_config
        alert.updated_at = datetime.utcnow()

        session.add(alert)
        session.commit()
        session.refresh(alert)
        return alert


@app.delete("/alerts/{alert_id}")
def delete_alert(
    alert_id: int,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        alert = session.exec(
            select(AlertRule).where(AlertRule.id == alert_id).where(AlertRule.user_id == user.id)
        ).first()
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        session.delete(alert)
        session.commit()
        return {"deleted": True, "alert_id": alert_id}


@app.post("/alerts/evaluate")
def evaluate_alerts(
    alert_ids: Optional[List[int]] = None,
    active_only: bool = True,
    persist: bool = True,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
    return _evaluate_alerts_internal(
        alert_ids=alert_ids,
        active_only=active_only,
        persist=persist,
        owner_user_id=user.id,
    )


@app.get("/alerts/events")
def list_alert_events(
    limit: int = 100,
    alert_id: Optional[int] = None,
    ticker: Optional[str] = None,
    triggered_only: bool = False,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        user_alert_ids = session.exec(
            select(AlertRule.id).where(AlertRule.user_id == user.id)
        ).all()
        if not user_alert_ids:
            return {"items": []}

        query = select(AlertEvent)
        query = query.where(AlertEvent.alert_id.in_(user_alert_ids))
        if alert_id is not None:
            query = query.where(AlertEvent.alert_id == alert_id)
        if ticker:
            query = query.where(AlertEvent.ticker == _canonical_symbol(ticker))
        if triggered_only:
            query = query.where(AlertEvent.triggered == True)  # noqa: E712
        rows = session.exec(
            query.order_by(AlertEvent.evaluated_at.desc()).limit(max(1, min(limit, 1000)))
        ).all()
        return {"items": rows}


# -------------------------------------------------------------------
# Screener API
# -------------------------------------------------------------------

@app.post("/screener/run")
def run_screener(payload: ScreenerRunRequest):
    symbols = [_canonical_symbol(s) for s in payload.symbols if str(s).strip()]
    if not symbols:
        raise HTTPException(status_code=400, detail="symbols are required")

    rows = []
    for symbol in symbols:
        fundamentals = get_fundamentals_cached(symbol)
        row = _build_screener_row(symbol, fundamentals)
        if _passes_screener_filters(row, payload.filters or {}):
            rows.append(row)

    limit = max(1, min(int(payload.limit), 1000))
    return {
        "count": len(rows),
        "items": rows[:limit],
        "filters": payload.filters or {},
    }


@app.post("/screener/screens")
def create_saved_screen(
    payload: SavedScreenRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    now = datetime.utcnow()
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        screen = SavedScreen(
            user_id=user.id,
            name=payload.name,
            description=payload.description,
            filters=payload.filters,
            created_at=now,
            updated_at=now,
        )
        session.add(screen)
        session.commit()
        session.refresh(screen)
        return screen


@app.get("/screener/screens")
def list_saved_screens(
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        screens = session.exec(
            select(SavedScreen)
            .where(SavedScreen.user_id == user.id)
            .order_by(SavedScreen.updated_at.desc())
        ).all()
        return {"items": screens}


@app.get("/screener/screens/{screen_id}")
def get_saved_screen(
    screen_id: int,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        screen = session.exec(
            select(SavedScreen).where(SavedScreen.id == screen_id).where(SavedScreen.user_id == user.id)
        ).first()
        if not screen:
            raise HTTPException(status_code=404, detail="Saved screen not found")
        return screen


@app.put("/screener/screens/{screen_id}")
def update_saved_screen(
    screen_id: int,
    payload: SavedScreenRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        screen = session.exec(
            select(SavedScreen).where(SavedScreen.id == screen_id).where(SavedScreen.user_id == user.id)
        ).first()
        if not screen:
            raise HTTPException(status_code=404, detail="Saved screen not found")
        screen.name = payload.name
        screen.description = payload.description
        screen.filters = payload.filters
        screen.updated_at = datetime.utcnow()
        session.add(screen)
        session.commit()
        session.refresh(screen)
        return screen


@app.delete("/screener/screens/{screen_id}")
def delete_saved_screen(
    screen_id: int,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user(session, user_id, x_user_id)
        screen = session.exec(
            select(SavedScreen).where(SavedScreen.id == screen_id).where(SavedScreen.user_id == user.id)
        ).first()
        if not screen:
            raise HTTPException(status_code=404, detail="Saved screen not found")
        session.delete(screen)
        session.commit()
        return {"deleted": True, "screen_id": screen_id}

@app.get("/news/{ticker}")
def get_news(ticker: str):
    """Fetches news for the UI widget"""
    return fetch_news(ticker)
