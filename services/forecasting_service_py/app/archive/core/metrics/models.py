from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


# ---- Base ----

class Metric(BaseModel):
    metric_type: str = Field(..., description="Unique metric id, e.g. 'forecast.price'")
    name: str = Field(..., description="Human readable name")
    category: str = Field(..., description="Group e.g. forecast/risk/price")
    unit: Optional[str] = Field(None, description="e.g. 'USD', '%', 'vol'")
    frequency: Optional[Literal["daily", "weekly", "monthly", "intraday"]] = "daily"
    is_premium: bool = False
    meta: Dict[str, Any] = Field(default_factory=dict)


# ---- ForecastMetric (used for price + volatility) ----

class ForecastMetric(Metric):
    metric_type: Literal["forecast.price", "forecast.volatility"]
    x: List[str] = Field(..., description="ISO dates, forecast horizon only")
    y: List[float] = Field(..., description="Forecast mean path")
    lower: Optional[List[float]] = Field(None, description="Lower CI (optional)")
    upper: Optional[List[float]] = Field(None, description="Upper CI (optional)")


# ---- RiskMetric (single snapshot) ----

class RiskMetric(Metric):
    metric_type: Literal["risk.snapshot"]
    var_95: float
    regime: str
    fragility_score: float
    stop_loss_price: float


# ---- MonteCarloMetric (price cone paths) ----

class MonteCarloMetric(Metric):
    metric_type: Literal["mc.price_cone"]
    x: List[str]
    lower: List[float]
    median: List[float]
    upper: List[float]


# Union type for FastAPI response_model
MetricUnion = Union[ForecastMetric, RiskMetric, MonteCarloMetric]