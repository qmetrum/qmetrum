from app.core.metrics.forecast import ForecastMetric, MonteCarloMetric
from app.core.metrics.risk import RiskMetric
from app.core.metrics.base import ForecastPoint, TimeSeriesPoint


def build_risk_metrics(entity_id: str, r_payload: dict):
    metrics = []

    # --- 1. Risk snapshot ---
    metrics.append(
        RiskMetric(
            entity_id=entity_id,
            metric_type="risk",
            values={
                "var_95": r_payload.get("var_95_latest"),
                "regime": r_payload.get("regime_latest"),
                "fragility_score": r_payload.get("fragility_score_latest"),
            },
            source="garch"
        )
    )

    # --- 2. Volatility forecast (mean + cone) ---
    sigma_mean = r_payload.get("sigma_fc_mean", [])
    sigma_l = r_payload.get("sigma_mc_lower", [])
    sigma_m = r_payload.get("sigma_mc_median", [])
    sigma_u = r_payload.get("sigma_mc_upper", [])

    if sigma_mean:
        metrics.append(
            ForecastMetric(
                entity_id=entity_id,
                metric_type="volatility_forecast",
                horizon_days=len(sigma_mean),
                series=[
                    ForecastPoint(
                        t=i + 1,
                        mean=sigma_mean[i],
                        p05=sigma_l[i] if i < len(sigma_l) else None,
                        p50=sigma_m[i] if i < len(sigma_m) else None,
                        p95=sigma_u[i] if i < len(sigma_u) else None,
                    )
                    for i in range(len(sigma_mean))
                ],
                source="garch"
            )
        )

    # --- 3. Monte Carlo price cone ---
    mc_l = r_payload.get("mc_lower", [])
    mc_m = r_payload.get("mc_median", [])
    mc_u = r_payload.get("mc_upper", [])

    if mc_l and mc_m and mc_u:
        metrics.append(
            MonteCarloMetric(
                entity_id=entity_id,
                metric_type="monte_carlo",
                horizon_days=len(mc_l),
                lower=mc_l,
                median=mc_m,
                upper=mc_u,
                source="garch"
            )
        )

    return metrics
