# services/forecasting_service_py/app/logic/portfolio_logic.py

import numpy as np
import pandas as pd
import logging
from concurrent.futures import ThreadPoolExecutor
from app.logic.forecasting_logic import HybridForecaster
from app.logic.forecast_extensions import build_drawdown_series, build_monthly_returns
from app.logic.tensor_network_risk import sample_standardised_joint_returns
from app.logic.adversarial_discovery import discover_worst_case
from app.logic.regime import portfolio_thresholds
from app.services.market_store import get_price_series_cached, get_fundamentals_cached

logger = logging.getLogger(__name__)

class PortfolioManager:
    """
    Orchestrates the forecasting of N assets and aggregates them
    into a Unified Portfolio View using 'Bottom-Up Forecast, Top-Down Risk'.
    """
    def __init__(self, portfolio_config: list[dict]):
        """
        :param portfolio_config: List of dicts [{'ticker': 'AAPL', 'weight': 0.6}, ...]
        """
        self.portfolio_config = portfolio_config
        self.weights = {item['ticker']: item['weight'] for item in portfolio_config}
        self.tickers = list(self.weights.keys())
        
        # Normalize weights to sum to 1.0 (Safety check)
        total_w = sum(self.weights.values())
        if total_w > 0:
            self.weights = {k: v/total_w for k, v in self.weights.items()}

    def _fetch_batch_data(self):
        """
        Simulation of DB Batch Fetch. 
        In production, this would query your Postgres 'Prices' table.
        """
        data_map = {}
        fundamentals_map = {}
        
        # We use ThreadPool to fetch concurrently (simulating optimized DB read)
        def fetch_one(ticker):
            # 1. Fetch Price History
            raw = get_price_series_cached(ticker, period="2y")
            df = pd.DataFrame(raw)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date').sort_index()
                # 2. Fetch Fundamentals
                fund = get_fundamentals_cached(ticker)
                return ticker, df, fund
            return ticker, None, None

        with ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(fetch_one, self.tickers)
            
        for ticker, df, fund in results:
            if df is not None:
                data_map[ticker] = df
                fundamentals_map[ticker] = fund
                
        return data_map, fundamentals_map

    def _run_single_forecast(self, ticker, df, horizon, fundamentals):
        """Helper to run one forecast instance."""
        try:
            forecaster = HybridForecaster()
            forecaster.fundamentals = fundamentals or {}
            # We reset the index to column for the forecaster expected format
            df_reset = df.reset_index()
            forecaster.train(df_reset)
            result = forecaster.predict(forecast_horizon_days=horizon)
            return ticker, result
        except Exception as e:
            logger.error(f"Failed to forecast {ticker}: {e}")
            return ticker, None

    def build_synthetic_history(self):
        """
        Build a synthetic portfolio price series (index starts at 100) from holdings.
        Returns a dict so callers (e.g. quantum simulation endpoint) can reuse it.
        """
        data_map, fund_map = self._fetch_batch_data()

        if not data_map:
            return {
                "error": "No market data found for portfolio tickers.",
                "synthetic_prices": [],
                "synthetic_dates": [],
                "data_map": {},
                "fundamentals_map": fund_map,
            }

        common_index = None
        for df in data_map.values():
            if common_index is None:
                common_index = df.index
            else:
                common_index = common_index.intersection(df.index)

        if common_index is None or len(common_index) == 0:
            return {
                "error": "No overlapping dates across portfolio tickers.",
                "synthetic_prices": [],
                "synthetic_dates": [],
                "data_map": data_map,
                "fundamentals_map": fund_map,
            }

        portfolio_returns = pd.Series(0.0, index=common_index)
        for ticker, df in data_map.items():
            aligned_df = df.loc[common_index]
            daily_ret = aligned_df["price"].pct_change().fillna(0)
            portfolio_returns += daily_ret * self.weights.get(ticker, 0.0)

        synthetic_history = (1 + portfolio_returns).cumprod() * 100
        synthetic_df = pd.DataFrame({
            "date": synthetic_history.index,
            "price": synthetic_history.values
        })

        return {
            "error": None,
            "synthetic_prices": synthetic_history.astype(float).tolist(),
            "synthetic_dates": synthetic_history.index.strftime("%Y-%m-%d").tolist(),
            "portfolio_returns": portfolio_returns.astype(float).tolist(),
            "synthetic_df": synthetic_df,
            "data_map": data_map,
            "fundamentals_map": fund_map,
        }

    def analyze_portfolio(self, horizon_days=90, scenarios=None, target_weights=None):
        # 1. GET DATA + SYNTHETIC HISTORY (Batch)
        synthetic_bundle = self.build_synthetic_history()
        if synthetic_bundle.get("error"):
            logger.warning(synthetic_bundle["error"])
            return {
                "error": synthetic_bundle["error"],
                "portfolio_summary": None,
                "holdings": []
            }

        data_map = synthetic_bundle["data_map"]
        fund_map = synthetic_bundle["fundamentals_map"]
        synthetic_df = synthetic_bundle["synthetic_df"]
        synthetic_history = pd.Series(
            synthetic_bundle["synthetic_prices"],
            index=pd.to_datetime(synthetic_bundle["synthetic_dates"])
        )
        portfolio_returns = pd.Series(
            synthetic_bundle["portfolio_returns"],
            index=pd.to_datetime(synthetic_bundle["synthetic_dates"])
        )

        # --- Regime Detection ---
        # 1. Drawdown override: ≥10% from a rolling 60-day peak ⇒ "Drawdown".
        # 2. Otherwise, vol-ratio with hysteresis (median of last 5 days).
        # 3. High/Low thresholds are weight-averaged from the portfolio's
        #    per-asset-class thresholds (treasury ETFs are calmer, crypto is
        #    noisier — calibrated table at app/data/regime_thresholds.json).
        recent_window = 21
        long_window = 126
        hysteresis_days = 5
        drawdown_threshold = -0.10  # -10% from rolling peak

        # Look up portfolio-tailored thresholds
        holdings_for_thresholds = [
            {"ticker": t, "weight": float(self.weights.get(t, 0.0) or 0.0)}
            for t in self.tickers
        ]
        high_thr, low_thr, regime_class_weights = portfolio_thresholds(
            holdings_for_thresholds, fund_map
        )

        clean_prices = synthetic_history.dropna()
        clean_returns = portfolio_returns.dropna()

        # Snapshot vol stats — always defined so the cache blob has real values
        # regardless of which branch sets `regime` below.
        recent_vol = (
            float(clean_returns.tail(recent_window).std())
            if len(clean_returns) >= 2 else 0.0
        )
        long_vol = (
            float(clean_returns.tail(long_window).std())
            if len(clean_returns) >= 2 else 0.0
        )
        vol_ratio = (recent_vol / long_vol) if long_vol and long_vol > 0 else 1.0

        # Drawdown check
        dd_lookback = min(60, len(clean_prices))
        drawdown = 0.0
        if dd_lookback >= 5:
            window_prices = clean_prices.tail(dd_lookback).to_numpy(dtype=float)
            peak = float(np.maximum.accumulate(window_prices)[-1])
            last = float(window_prices[-1])
            if peak > 0:
                drawdown = (last / peak) - 1.0

        if drawdown < drawdown_threshold:
            regime = "Drawdown"
        else:
            # Hysteresis-smoothed vol ratio (median of last N daily ratios) when we
            # have enough history; otherwise use the snapshot vol_ratio above.
            if len(clean_returns) >= long_window + hysteresis_days:
                ratios: list[float] = []
                for i in range(hysteresis_days):
                    end = len(clean_returns) - i
                    recent = clean_returns.iloc[end - recent_window:end]
                    long = clean_returns.iloc[end - long_window:end]
                    if len(recent) < recent_window or len(long) < long_window:
                        continue
                    r_vol = float(recent.std())
                    l_vol = float(long.std())
                    if l_vol > 0:
                        ratios.append(r_vol / l_vol)
                if ratios:
                    vol_ratio = float(np.median(ratios))

            if vol_ratio > high_thr:
                regime = "High_Vol"
            elif vol_ratio < low_thr:
                regime = "Low_Vol"
            else:
                regime = "Normal"

        # --- Sector / Rate mapping from fundamentals ---
        sector_exposure = {}
        rate_sensitive_weight = 0.0
        for ticker in self.tickers:
            weight = float(self.weights.get(ticker, 0.0))
            fund = fund_map.get(ticker, {}) or {}
            profile = fund.get("profile", {}) if isinstance(fund, dict) else {}
            sector = profile.get("sector", "Unknown") or "Unknown"
            sector_exposure[sector] = float(sector_exposure.get(sector, 0.0) + weight)

            fund_type = str(fund.get("type", "")).upper() if isinstance(fund, dict) else ""
            if "bond_metrics" in fund or fund_type in {"BOND", "FUTURE"}:
                rate_sensitive_weight += weight

        # 4. RUN INDIVIDUAL FORECASTS (Bottom-Up)
        individual_forecasts = {}
        with ThreadPoolExecutor() as executor:
           # Pass 'fund_map[t]' into the function
            futures = [
                executor.submit(self._run_single_forecast, t, data_map[t], horizon_days, fund_map.get(t, {})) 
                for t in self.tickers if t in data_map
            ]
            for f in futures:
                t, res = f.result()
                if res: individual_forecasts[t] = res

        # 5. AGGREGATE FORECASTS
        # Portfolio Forecast Returns = Sum(Weight_i * Forecast_Returns_i)
        # We need to align the forecast arrays carefully
        
        # Initialize with zeros
        agg_forecast_returns = np.zeros(horizon_days)
        
        for ticker, res in individual_forecasts.items():
            f_rets = np.array(res['forecast_returns'])
            # Handle length mismatch safety
            length = min(len(f_rets), horizon_days)
            agg_forecast_returns[:length] += f_rets[:length] * self.weights[ticker]

        # Reconstruct Portfolio Price Forecast from Aggregate Returns
        last_synth_price = synthetic_history.iloc[-1]
        agg_prices = []
        curr = last_synth_price
        for r in agg_forecast_returns:
            nxt = curr * (1 + r)
            agg_prices.append(nxt)
            curr = nxt

        # --- Scenario Paths (defaults + custom) ---
        def build_path(base_price, returns, shock_pct=0.0, scale=1.0, drift_shift=0.0):
            path = []
            curr_price = float(base_price) * (1 + float(shock_pct))
            for r in returns:
                curr_price = curr_price * (1 + (float(r) * float(scale)) + float(drift_shift))
                path.append(float(curr_price))
            return path

        scenario_defs = {
            "bull_10": {"initial_shock_pct": 0.10, "return_scale": 1.0, "drift_shift": 0.0},
            "bear_10": {"initial_shock_pct": -0.10, "return_scale": 1.0, "drift_shift": 0.0},
            "high_vol_regime": {"initial_shock_pct": 0.0, "return_scale": 1.25, "drift_shift": 0.0},
            "low_vol_regime": {"initial_shock_pct": 0.0, "return_scale": 0.75, "drift_shift": 0.0},
        }
        for scenario in scenarios or []:
            name = str(scenario.get("name", "")).strip()
            if not name:
                continue
            scenario_defs[name] = scenario

        # --- MPS-copula scenario fans ---
        # Try to sample the portfolio's joint return distribution non-parametrically
        # via a tensor-network MPS. The MPS is used only as a copula: it captures the
        # cross-asset dependence structure on standardised returns. Per-asset marginals
        # are reconstructed from scenario knobs (shock / return_scale / drift_shift).
        # If MPS fit fails (too few assets, insufficient history, etc.), we fall back
        # to the historical deterministic single-path scenario builder.
        mps_ok = False
        mps_info = None
        try:
            mps_sample = sample_standardised_joint_returns(
                data_map=data_map,
                tickers_order=self.tickers,
                n_steps=horizon_days,
                n_simulations=500,
                d=4,
                chi=8,
                random_seed=42,
            )
            z = mps_sample["z_samples"]                  # (T, S, N)
            kept_tickers = mps_sample["tickers"]
            mu_vec = mps_sample["asset_mu"]              # (N,) historical log-return mean
            sd_vec = mps_sample["asset_sigma"]           # (N,) historical log-return std
            w_vec = np.array([float(self.weights.get(t, 0.0)) for t in kept_tickers], dtype=float)
            if w_vec.sum() > 0 and len(kept_tickers) >= 2:
                w_vec = w_vec / w_vec.sum()
                mps_ok = True
                mps_info = mps_sample["mps"]
        except Exception as e:
            logger.warning(f"MPS copula fit failed, using deterministic scenarios: {e}")

        def _fan_from_mps(shock_pct: float, scale: float, drift_shift: float):
            """Reconstruct price-path fan from MPS z-samples under the given scenario knobs.

            Per-asset log-return per step:
                r_i_t = mu_i + sigma_i * scale * z_i_t + drift_shift
            The MPS (as copula) contributes z; the knobs re-shape the marginals.
            """
            r = mu_vec + sd_vec * scale * z + float(drift_shift)     # (T, S, N)
            port_r = np.einsum("tsn,n->ts", r, w_vec)                # (T, S)
            base = float(last_synth_price) * (1.0 + float(shock_pct))
            paths = base * np.exp(np.cumsum(port_r, axis=0))         # (T, S)
            return {
                "central":  np.percentile(paths, 50,   axis=1).tolist(),
                "lower_1s": np.percentile(paths, 16,   axis=1).tolist(),
                "upper_1s": np.percentile(paths, 84,   axis=1).tolist(),
                "lower_2s": np.percentile(paths, 2.5,  axis=1).tolist(),
                "upper_2s": np.percentile(paths, 97.5, axis=1).tolist(),
            }

        scenarios_fan = {}
        scenarios_legacy = {"base": agg_prices}
        for name, sc in scenario_defs.items():
            scenarios_legacy[name] = build_path(
                last_synth_price,
                agg_forecast_returns,
                shock_pct=sc.get("initial_shock_pct", 0.0),
                scale=sc.get("return_scale", 1.0),
                drift_shift=sc.get("drift_shift", 0.0),
            )

        if mps_ok:
            # Base: no shock, no scale, no drift-shift — just the copula-sampled fan.
            scenarios_fan["base"] = _fan_from_mps(0.0, 1.0, 0.0)
            for name, sc in scenario_defs.items():
                scenarios_fan[name] = _fan_from_mps(
                    shock_pct=float(sc.get("initial_shock_pct", 0.0)),
                    scale=float(sc.get("return_scale", 1.0)),
                    drift_shift=float(sc.get("drift_shift", 0.0)),
                )
            scenarios_fan["_mps"] = mps_info  # audit: max_bond_dim_used etc.

            # --- Adversarial worst-case discovery (classical GD + MPS fan) ---
            try:
                adv = discover_worst_case(
                    data_map=data_map,
                    weights=self.weights,
                    horizon_days=horizon_days,
                    n_sims=500,
                    n_restarts=30,
                )
                adv_def = adv["scenario_def"]
                scenarios_fan["worst_case_cvar"] = _fan_from_mps(
                    shock_pct=float(adv_def["initial_shock_pct"]),
                    scale=float(adv_def.get("return_scale", 1.0)),
                    drift_shift=float(adv_def.get("drift_shift", 0.0)),
                )
                scenarios_fan["worst_case_cvar"]["_discovery"] = {
                    "cvar": adv["cvar"],
                    "shock_pcts": adv["shock_pcts"],
                    "shock_vector_sigma": adv["shock_vector_sigma"],
                    "runtime_ms": adv["runtime_ms"],
                }
                scenarios_legacy["worst_case_cvar"] = build_path(
                    last_synth_price, agg_forecast_returns,
                    shock_pct=adv_def["initial_shock_pct"],
                    scale=adv_def.get("return_scale", 1.0),
                    drift_shift=adv_def.get("drift_shift", 0.0),
                )
                logger.info(
                    "Adversarial discovery: CVaR=%.4f shock=%.1f%% runtime=%dms",
                    adv["cvar"], adv["agg_shock_pct"] * 100, adv["runtime_ms"],
                )
            except Exception as e:
                logger.warning(f"Adversarial scenario discovery failed: {e}")
        else:
            # Degenerate fan: central == legacy deterministic path, no bands.
            for name, pth in scenarios_legacy.items():
                scenarios_fan[name] = {"central": pth}

        # --- Stress Tests ---
        stress_tests = []
        if len(portfolio_returns) >= 2:
            daily_vol = portfolio_returns.std()
            # 1-day shocks
            for sigma in [2, 3]:
                shock_ret = -sigma * daily_vol
                stress_tests.append({
                    "name": f"one_day_{sigma}sigma",
                    "horizon_days": 1,
                    "shock_return": float(shock_ret),
                    "shocked_price": float(last_synth_price * (1 + shock_ret))
                })
            # 5-day shock (scaled by sqrt(5))
            shock_ret_5d = -2 * daily_vol * np.sqrt(5)
            stress_tests.append({
                "name": "five_day_2sigma",
                "horizon_days": 5,
                "shock_return": float(shock_ret_5d),
                "shocked_price": float(last_synth_price * (1 + shock_ret_5d))
            })
        # Fixed shocks
        for pct in [-0.10, -0.20]:
            stress_tests.append({
                "name": f"market_{int(abs(pct)*100)}pct",
                "horizon_days": 1,
                "shock_return": float(pct),
                "shocked_price": float(last_synth_price * (1 + pct))
            })

        # Sector shocks from mapped fundamentals
        top_sectors = sorted(sector_exposure.items(), key=lambda x: x[1], reverse=True)[:3]
        for sector, exposure in top_sectors:
            sector_drop = -0.12
            portfolio_impact = sector_drop * exposure
            stress_tests.append({
                "name": f"sector_shock_{str(sector).lower().replace(' ', '_')}",
                "sector": sector,
                "sector_weight": float(exposure),
                "assumed_sector_return": float(sector_drop),
                "shock_return": float(portfolio_impact),
                "shocked_price": float(last_synth_price * (1 + portfolio_impact))
            })

        # Rate shocks for rate-sensitive exposure
        rate_up_impact = -0.05 * rate_sensitive_weight  # +100 bps
        rate_down_impact = 0.04 * rate_sensitive_weight # -100 bps
        stress_tests.append({
            "name": "rate_up_100bp",
            "rate_sensitive_weight": float(rate_sensitive_weight),
            "shock_return": float(rate_up_impact),
            "shocked_price": float(last_synth_price * (1 + rate_up_impact))
        })
        stress_tests.append({
            "name": "rate_down_100bp",
            "rate_sensitive_weight": float(rate_sensitive_weight),
            "shock_return": float(rate_down_impact),
            "shocked_price": float(last_synth_price * (1 + rate_down_impact))
        })

        # --- Rebalancing Suggestions (custom or equal-weight target) ---
        rebalancing = []
        turnover = 0.0
        if self.tickers:
            if target_weights:
                target_map = {t: float(target_weights.get(t, 0.0)) for t in self.tickers}
                target_label = "custom"
            else:
                equal_weight = 1.0 / len(self.tickers)
                target_map = {t: float(equal_weight) for t in self.tickers}
                target_label = "equal_weight"

            for t in self.tickers:
                w = self.weights.get(t, 0.0)
                tw = target_map.get(t, 0.0)
                delta = tw - w
                turnover += abs(delta)
                action = "buy" if delta > 0 else "sell" if delta < 0 else "hold"
                rebalancing.append({
                    "ticker": t,
                    "current_weight": float(w),
                    "target_weight": float(tw),
                    "delta_weight": float(delta),
                    "action": action
                })
        else:
            target_label = "equal_weight"
            
        # 6. RUN RISK ON SYNTHETIC PORTFOLIO (Top-Down Risk)
        # We treat the "Synthetic Portfolio" as if it were a single stock and run the Risk Engine on it.
        # This gives us the VaR and Fragility of the *entire* portfolio, accounting for correlation.
        
        # Create a temporary forecaster just to run the risk modules on synthetic data
        risk_engine = HybridForecaster()
        risk_engine.train(synthetic_df) # Train on the index 100...
        
        # We don't need the forecast from this, just the risk metrics & indicators
        # But we run predict to generate the "Cone" for the portfolio
        portfolio_risk_result = risk_engine.predict(forecast_horizon_days=horizon_days)

        # --- Re-centre the R cone width onto agg_prices so the CI band straddles the
        # portfolio forecast line. The raw monte_carlo_cone returned by predict() is
        # computed on the synthetic-series random walk and is not centred on agg_prices,
        # so using it directly as a UI band produces asymmetric / one-sided display.
        cone = portfolio_risk_result.get('monte_carlo_cone') or {}
        cone_lo = cone.get('lower_bound') or []
        cone_md = cone.get('median_bound') or []
        cone_hi = cone.get('upper_bound') or []
        h = min(len(agg_prices), len(cone_lo), len(cone_hi))
        if h > 0:
            fp = np.asarray(agg_prices[:h], dtype=float)
            lo = np.asarray(cone_lo[:h], dtype=float)
            hi = np.asarray(cone_hi[:h], dtype=float)
            md = np.asarray(cone_md[:h], dtype=float) if len(cone_md) >= h else 0.5 * (lo + hi)
            lower_ci = (fp - np.maximum(md - lo, 0.0)).tolist()
            upper_ci = (fp + np.maximum(hi - md, 0.0)).tolist()
        else:
            lower_ci = [p * 0.95 for p in agg_prices]
            upper_ci = [p * 1.05 for p in agg_prices]

        # --- Drawdown and monthly returns with forecast CI (portfolio-level) ---
        synth_dates_str = [str(d.date()) for d in synthetic_history.index]
        try:
            drawdown_series = build_drawdown_series(
                historical_prices=synthetic_history.astype(float).tolist(),
                forecast_prices=agg_prices,
                lower_ci=lower_ci,
                upper_ci=upper_ci,
                historical_dates=synth_dates_str,
                forecast_dates=portfolio_risk_result['forecast_dates'],
            )
        except Exception as e:
            logger.warning(f"portfolio drawdown_series build failed: {e}")
            drawdown_series = None
        try:
            monthly_returns = build_monthly_returns(
                historical_dates=synth_dates_str,
                historical_prices=synthetic_history.astype(float).tolist(),
                forecast_dates=portfolio_risk_result['forecast_dates'],
                forecast_prices=agg_prices,
                lower_ci=lower_ci,
                upper_ci=upper_ci,
            )
        except Exception as e:
            logger.warning(f"portfolio monthly_returns build failed: {e}")
            monthly_returns = None

        # 7. CONSTRUCT RESPONSE
        response = {
            "portfolio_summary": {
                "forecast_prices": agg_prices,
                "forecast_dates": portfolio_risk_result['forecast_dates'], # Use dates from risk engine
                "upper_ci": upper_ci,                                      # re-centred on agg_prices
                "lower_ci": lower_ci,
                "risk_metrics": portfolio_risk_result['risk_metrics'],     # Portfolio-level VaR
                "monte_carlo_cone": portfolio_risk_result.get('monte_carlo_cone'),  # raw R cone
                "drawdown_series": drawdown_series,
                "monthly_returns": monthly_returns,
                "indicators": portfolio_risk_result.get('indicators'),     # Portfolio-level RSI/MACD
                "volatility": portfolio_risk_result.get('volatility', {}), # GARCH representative path + cone
                "performance_metrics": portfolio_risk_result.get('performance_metrics'),
                "forecast_horizon_days": horizon_days,
                "regime": {
                    "current": regime,
                    "vol_ratio": float(vol_ratio),
                    "recent_vol": float(recent_vol) if recent_vol is not None else 0.0,
                    "long_vol": float(long_vol) if long_vol is not None else 0.0
                },
                "sector_exposure": {k: float(v) for k, v in sector_exposure.items()},
                "scenarios": scenarios_fan,           # fan shape: {name: {central, lower_1s, upper_1s, lower_2s, upper_2s}}
                "scenarios_legacy": scenarios_legacy, # flat deterministic paths for legacy callers
            },
            "stress_tests": stress_tests,
            "rebalancing": {
                "target": target_label,
                "estimated_turnover": float(turnover * 0.5),
                "suggestions": rebalancing
            },
            "holdings": []
        }
        
        # Add individual breakdown
        for ticker, res in individual_forecasts.items():
            forecast_return = float(sum(res['forecast_returns']))
            holding = {
                "ticker": ticker,
                "weight": self.weights[ticker],
                "current_price": data_map[ticker]['price'].iloc[-1],
                "forecast_return": forecast_return,
                "forecast_horizon_days": horizon_days,
                "fundamentals": fund_map.get(ticker, {}),
                "risk_metrics": res['risk_metrics']
            }
            # Backward compatibility: only include 90d key for 90-day runs
            if horizon_days == 90:
                holding["forecast_return_90d"] = forecast_return
            response['holdings'].append(holding)

        return response
