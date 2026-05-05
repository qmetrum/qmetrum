from typing import List, Optional

from app.core.metrics.models import ForecastMetric, RiskMetric, MonteCarloMetric


def build_price_forecast_metric(
    dates: List[str],
    forecast_prices: List[float],
    lower_ci: Optional[List[float]] = None,
    upper_ci: Optional[List[float]] = None,
    model_used: str = "unknown",
) -> ForecastMetric:
    return ForecastMetric(
        metric_type="forecast.price",
        name="Price Forecast",
        category="forecast",
        unit="price",
        frequency="daily",
        is_premium=False,
        x=dates,
        y=forecast_prices,
        lower=lower_ci,
        upper=upper_ci,
        meta={"model_used": model_used},
    )


def build_volatility_forecast_metric(
    dates: List[str],
    sigma_mean: List[float],
    lower: Optional[List[float]] = None,
    upper: Optional[List[float]] = None,
) -> ForecastMetric:
    return ForecastMetric(
        metric_type="forecast.volatility",
        name="Volatility Forecast",
        category="forecast",
        unit="vol",
        frequency="daily",
        is_premium=True,
        x=dates,
        y=sigma_mean,
        lower=lower,
        upper=upper,
        meta={"source": "garch"},
    )


def build_risk_metric(
    var_95: float,
    regime: str,
    fragility_score: float,
    stop_loss_price: float,
) -> RiskMetric:
    return RiskMetric(
        metric_type="risk.snapshot",
        name="Risk Snapshot",
        category="risk",
        unit=None,
        frequency="daily",
        is_premium=True,
        var_95=var_95,
        regime=regime,
        fragility_score=fragility_score,
        stop_loss_price=stop_loss_price,
    )


def build_monte_carlo_metric(
    dates: List[str],
    lower: List[float],
    median: List[float],
    upper: List[float],
) -> MonteCarloMetric:
    return MonteCarloMetric(
        metric_type="mc.price_cone",
        name="Monte Carlo Price Cone",
        category="risk",
        unit="price",
        frequency="daily",
        is_premium=True,
        x=dates,
        lower=lower,
        median=median,
        upper=upper,
        meta={"paths": "simulated"},
    )