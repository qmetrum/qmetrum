# app/core/metrics/market.py

from typing import Literal
from .base import MetricBase, TimeSeriesPoint

class PriceMetric(MetricBase):
    metric_type: Literal["price"]
    currency: str
    series: list[TimeSeriesPoint]

class ReturnsMetric(MetricBase):
    metric_type: Literal["returns"]
    values: dict[str, float]
