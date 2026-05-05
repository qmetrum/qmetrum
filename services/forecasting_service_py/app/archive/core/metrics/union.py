# app/core/metrics/union.py

from typing import Union
from .market import PriceMetric, ReturnsMetric
from .risk import RiskMetric, VolatilityMetric
from .forecast import ForecastMetric, MonteCarloMetric

Metric = Union[
    PriceMetric,
    ReturnsMetric,
    RiskMetric,
    VolatilityMetric,
    ForecastMetric,
    MonteCarloMetric
]