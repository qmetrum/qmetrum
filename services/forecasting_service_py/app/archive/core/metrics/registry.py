from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class MetricDefinition:
    metric_type: str
    premium: bool
    description: str


METRIC_REGISTRY: Dict[str, MetricDefinition] = {
    "forecast.price": MetricDefinition(
        metric_type="forecast.price",
        premium=False,
        description="Forecasted price path with optional confidence bounds",
    ),
    "forecast.volatility": MetricDefinition(
        metric_type="forecast.volatility",
        premium=True,
        description="Forecasted volatility (e.g., GARCH) with volatility cone bounds",
    ),
    "risk.snapshot": MetricDefinition(
        metric_type="risk.snapshot",
        premium=True,
        description="Snapshot risk metrics (VaR, regime, fragility, stop-loss)",
    ),
    "mc.price_cone": MetricDefinition(
        metric_type="mc.price_cone",
        premium=True,
        description="Monte Carlo forecast cone for price path",
    ),
}