# app/core/metrics/base.py

from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime

class MetricBase(BaseModel):
    entity_id: str
    metric_type: str
    source: str
    frequency: Optional[Literal["daily", "weekly", "monthly", "quarterly"]] = None
    created_at: datetime = datetime.utcnow()

class TimeSeriesPoint(BaseModel):
    date: str
    value: float

class ForecastPoint(BaseModel):
    t: int
    mean: float
    p05: Optional[float] = None
    p50: Optional[float] = None
    p95: Optional[float] = None
