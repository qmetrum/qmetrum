# app/core/metrics/risk.py

from typing import Literal
from .base import MetricBase, TimeSeriesPoint

class RiskMetric(MetricBase):
    metric_type: Literal["risk"]
    values: dict[str, float | str]

class VolatilityMetric(MetricBase):
    metric_type: Literal["volatility"]
    series: list[TimeSeriesPoint]