from dataclasses import dataclass
from app.core.metrics.market import PriceMetric, ReturnsMetric
from app.core.metrics.risk import RiskMetric, VolatilityMetric
from app.core.metrics.forecast import ForecastMetric, MonteCarloMetric

@dataclass
class MetricDefinition:
    name: str
    category: str
    producer: str
    premium: bool
    schema: type

METRIC_REGISTRY = {
    "price": MetricDefinition(
        name="price",
        category="market",
        producer="python",
        premium=False,
        schema=PriceMetric
    ),
    "returns": MetricDefinition(
        name="returns",
        category="market",
        producer="python",
        premium=False,
        schema=ReturnsMetric
    ),
    "risk": MetricDefinition(
        name="risk",
        category="risk",
        producer="r",
        premium=False,
        schema=RiskMetric
    ),
    "volatility_forecast": MetricDefinition(
        name="volatility_forecast",
        category="forecast",
        producer="r",
        premium=True,
        schema=ForecastMetric
    ),
    "monte_carlo": MetricDefinition(
        name="monte_carlo",
        category="risk",
        producer="r",
        premium=True,
        schema=MonteCarloMetric
    )
}