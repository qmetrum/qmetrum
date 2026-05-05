# app/core/metrics/forecast.py

from typing import Literal
from .base import MetricBase, ForecastPoint

class ForecastMetric(MetricBase):
    metric_type: Literal[
        "price_forecast",
        "volatility_forecast",
        "returns_forecast"
    ]
    horizon_days: int
    series: list[ForecastPoint]

class MonteCarloMetric(MetricBase):
    metric_type: Literal["monte_carlo", "quantum_mc"]
    horizon_days: int
    lower: list[float]
    median: list[float]
    upper: list[float]
