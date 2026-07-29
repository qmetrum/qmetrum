# services/forecasting_service_py/app/logic/forecasting_logic.py

import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error
from statsmodels.tsa.arima.model import ARIMA
from prophet import Prophet
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Input
from tensorflow.keras.optimizers import Adam
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf
from scipy.signal import butter, filtfilt
from tensorflow.keras.callbacks import EarlyStopping
from sentence_transformers import SentenceTransformer
from sklearn.decomposition import PCA
import logging
import shap
from dotenv import load_dotenv 
from sklearn.svm import SVR
from math import sqrt

# --- BSTS IMPORTS ---
import tensorflow_probability as tfp
from tensorflow_probability import sts
from app.services.risk_client import calculate_risk
from app.logic.quantum_reservoir import QuantumReservoirForecaster, QRCConfig
from app.logic.qrc_cache import load_cached_config as load_qrc_cached_config
from app.logic.forecast_extensions import build_drawdown_series, build_monthly_returns
from app.logic.vqmc_scenarios import generate_vqmc_scenario_fans

# Load the .env file explicitly
load_dotenv() 

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------
# 1. PARAMETRISED FEATURE MAP (numpy port of former cirq circuit)
#
# Preserves the Z-expectation of the Ry(xπ)^⊗n → CNOT-ring ansatz measured on
# the first qubit. Numerically equivalent to the original cirq implementation
# to ~1e-7 (float precision); runs in microseconds with zero quantum deps.
# Ablation shows the specific shape of this feature is load-bearing for the
# ARIMAX exog matrix — a naive cos(2πx) substitute destroys RMSE.
# ------------------------------------------------------------------------

def _apply_cnot(amps, control, target, n_qubits):
    out = amps.copy()
    c_pos = n_qubits - 1 - control
    t_pos = n_qubits - 1 - target
    for i in range(1 << n_qubits):
        if (i >> c_pos) & 1:
            j = i ^ (1 << t_pos)
            if j > i:
                out[i], out[j] = amps[j], amps[i]
    return out


def create_parametrized_quantum_circuit(x_value, n_qubits=4):
    theta = float(x_value) * np.pi
    c, s = np.cos(theta / 2.0), np.sin(theta / 2.0)
    dim = 1 << n_qubits
    amps = np.empty(dim, dtype=float)
    for i in range(dim):
        a = 1.0
        for q in range(n_qubits):
            bit = (i >> (n_qubits - 1 - q)) & 1
            a *= (c if bit == 0 else s)
        amps[i] = a
    for i in range(n_qubits - 1):
        amps = _apply_cnot(amps, i, i + 1, n_qubits)
    if n_qubits > 2:
        amps = _apply_cnot(amps, n_qubits - 1, 0, n_qubits)
    probs = amps * amps
    z = 0.0
    for i, p in enumerate(probs):
        if (i >> (n_qubits - 1)) & 1:
            z -= p
        else:
            z += p
    return float(z)


def generate_optimized_quantum_features(X, n_qubits=4):
    if np.max(X) == np.min(X):
        X_norm = np.zeros_like(X)
    else:
        X_norm = (X - np.min(X)) / (np.max(X) - np.min(X))
    return np.array([[create_parametrized_quantum_circuit(x, n_qubits)] for x in X_norm])

# ------------------------------------------------------------------------
# 2. LLM & SEMANTIC HELPER FUNCTIONS
# ------------------------------------------------------------------------

_embed_model = SentenceTransformer('all-MiniLM-L6-v2')

def describe_time_series(ts):
    n = len(ts)
    # Split into 3 segments
    p1, p2, p3 = ts[:n//3], ts[n//3:2*n//3], ts[2*n//3:]
    
    # helper to get slope description
    def get_slope(segment):
        if len(segment) < 2: return "flat"
        # Calculate percentage change instead of absolute difference
        pct_change = (segment[-1] - segment[0]) / (segment[0] + 1e-9) # avoid div/0
        
        if pct_change > 0.01: return "rallying"   # > 1% change
        if pct_change < -0.01: return "crashing"  # < -1% change
        return "holding steady"

    def get_vol(segment):
        # Calculate Coefficient of Variation (Std Dev / Mean)
        # This creates a "unitless" measure of volatility
        mean_val = np.mean(segment)
        if mean_val == 0: return "calm"
        
        cv = np.std(segment) / mean_val
        return "unstable" if cv > 0.02 else "calm" # e.g. > 2% variability

    # Construct the Semantic Narrative
    # Note how we emphasize the CHANGE between phases
    summary = (
        f"The series started by {get_slope(p1)} in a {get_vol(p1)} manner. "
        f"It then shifted to {get_slope(p2)}, becoming {get_vol(p2)}. "
        f"Crucially, it is currently {get_slope(p3)} with {get_vol(p3)} conditions."
    )
    
    return summary

def build_pointwise_descriptions(series, window=12):
    series = np.asarray(series, dtype=float)
    descs = []
    for t in range(len(series)):
        t_start = max(0, t - window + 1)
        segment = series[t_start : t+1]
        descs.append(describe_time_series(segment))
    return descs

def generate_llm_embeddings(text_list):
    if not text_list: return np.zeros((0, 384), dtype=np.float32)
    return _embed_model.encode(text_list, convert_to_numpy=True, normalize_embeddings=False)

# ------------------------------------------------------------------------
# 3. EXPLAINER & HELPERS
# ------------------------------------------------------------------------

class MarketExplainer:
    def __init__(self, model_wrapper, background_data, feature_names):
        self.feature_names = feature_names
        self.explainer = shap.KernelExplainer(model_wrapper, background_data)

    def explain_latest(self, latest_feature_row):
        try:
            shap_values = self.explainer.shap_values(latest_feature_row, silent=True)
            if isinstance(shap_values, list): vals = shap_values[0]
            else: vals = shap_values
            vals = np.array(vals)
            vals = np.nan_to_num(vals, nan=0.0)
            contribs = dict(zip(self.feature_names, vals.flatten()))
            sorted_drivers = sorted(contribs.items(), key=lambda x: abs(x[1]), reverse=True)
            narrative = f"Primary driver is {sorted_drivers[0][0]} ({sorted_drivers[0][1]:.4f})." if sorted_drivers else "No significant drivers."
            return {"narrative": narrative, "detailed_contributions": contribs}
        except Exception:
            return {"narrative": "Explanation unavailable.", "detailed_contributions": {}}

# ------------------------------------------------------------------------
# 5. MAIN FORECASTING ENGINE
# ------------------------------------------------------------------------

class HybridForecaster:
    """
    Standardized Quant Pipeline:
    - LSTM: Train on Log-Returns (Stationarity). Forecast returns, reconstruct prices.
    - ARIMA/Prophet/BSTS: Train on Log-Prices (Structural). Forecast levels, exponentiate.
      ARIMA can also be fit on returns if that backtests better.
    - QRC: Quantum Reservoir Computing on raw prices. Per-ticker tuned config
      loaded from cache (app/logic/qrc_cache.py) so nightly fit stays at ~3s/asset.
      Falls back to a default config if cache is missing/stale.
    """
    def __init__(self):
        self.winner_model = None
        self.winner_model_name = None
        self.arima_target = "levels"
        self.exogenous_data_for_training = None
        self.last_exogenous_row = None
        self.lstm_lookback = 60
        self.trained_history_df = None
        self.last_actual_price = None
        self.ticker = None  # set by train() if provided; used for QRC config cache lookup

        # Risk Cache
        self.volatility_cache = []
        self.fragility_cache = []
        self.validation_scores = {}

    def _calculate_rmse(self, y_true, y_pred):
        try:
            return sqrt(mean_squared_error(y_true, y_pred))
        except: return float('inf')

    def _sanitize_for_json(self, obj):
        if isinstance(obj, (float, np.floating)):
            if np.isnan(obj) or np.isinf(obj): return 0.0
            return float(obj)
        elif isinstance(obj, dict):
            return {k: self._sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_for_json(v) for v in obj]
        elif isinstance(obj, (np.integer, int)):
            return int(obj)
        elif isinstance(obj, np.ndarray):
            return self._sanitize_for_json(obj.tolist())
        return obj

    def _fetch_risk_metrics(self, prices, horizon=90):
        """
        Call R risk service using HISTORICAL prices ONLY.
        Returns sigma history aligned to prices length.
        Caches forward sigma + cones and forward price cones.
        """
        try:
            data = calculate_risk(
                prices=prices.tolist(),
                horizon=int(horizon),
                n_paths=1000,
                require_success=False,
            )
            if not data:
                raise RuntimeError("Risk service returned no payload")

            # --- HELPER: Safe Unbox (Handle R returning [value] vs value) ---
            def safe_float(key, default=0.0):
                val = data.get(key, default)
                if isinstance(val, list):
                    return float(val[0]) if val else default
                return float(val)

            def safe_str(key, default="Unknown"):
                val = data.get(key, default)
                if isinstance(val, list):
                    return str(val[0]) if val else default
                return str(val)

            # --- SNAPSHOT METRICS ---
            self.latest_var = safe_float("var_95_latest", -0.05)
            self.latest_regime = safe_str("regime_latest", "Unknown")
            
            # Note: R returns "fragility_score", Python was looking for "fragility_score_latest"
            # We check both to be safe.
            fs = data.get("fragility_score") or data.get("fragility_score_latest")
            # Manually handle FS since we grabbed it from two potential keys
            if isinstance(fs, list): fs = fs[0] if fs else 0.0
            self.latest_fragility_score = float(fs) if fs is not None else 0.0

            # --- FORWARD DATA ---
            self.mc_lower = data.get("mc_lower", [])
            self.mc_median = data.get("mc_median", [])
            self.mc_upper = data.get("mc_upper", [])

            # Historical volatility (sigma_hist)
            # R returns daily conditional vol — annualize for the rest of the pipeline
            _ANN = np.sqrt(252.0)
            sigma_hist = np.array(data.get("sigma_hist", []), dtype=float) * _ANN

            # Forward VOL (mean + cone) — also annualize
            self.sigma_fc_mean = (np.array(data.get("sigma_fc_mean", []), dtype=float) * _ANN).tolist()
            self.sigma_mc_lower = (np.array(data.get("sigma_mc_lower", []), dtype=float) * _ANN).tolist()
            self.sigma_mc_median = (np.array(data.get("sigma_mc_median", []), dtype=float) * _ANN).tolist()
            self.sigma_mc_upper = (np.array(data.get("sigma_mc_upper", []), dtype=float) * _ANN).tolist()

            # Align sigma_hist to prices length
            N = len(prices)
            if len(sigma_hist) > 0:
                # Often R returns diff(log(price)) length (N-1). Prepend to match N.
                if len(sigma_hist) == N - 1:
                    sigma_aligned = np.concatenate([[sigma_hist[0]], sigma_hist])
                elif len(sigma_hist) == N:
                    sigma_aligned = sigma_hist
                else:
                    # Fallback padding if mismatch is weird
                    sigma_aligned = np.resize(sigma_hist, N)
            else:
                sigma_aligned = np.zeros(N)

            self.volatility_cache = sigma_aligned.tolist()
            
            # Handle fragility history if present
            frag_hist = np.array(data.get("fragility_hist", []), dtype=float)
            if len(frag_hist) > 0:
                frag_aligned = np.resize(frag_hist, N) # Simple resize to ensure shape
                self.fragility_cache = frag_aligned.tolist()
            else:
                self.fragility_cache = np.zeros(N).tolist()

            return sigma_aligned, np.array(self.fragility_cache)

        except Exception as e:
            logger.warning(f"Risk service failed: {e}")
            N = len(prices)
            # Default fallbacks
            self.latest_var = -0.05
            self.latest_regime = "Unknown"
            self.latest_fragility_score = 0.0
            self.mc_lower, self.mc_median, self.mc_upper = [], [], []
            self.sigma_fc_mean = []
            self.sigma_mc_lower, self.sigma_mc_median, self.sigma_mc_upper = [], [], []
            
            return np.zeros(N), np.zeros(N)



    def _calculate_performance_metrics(self, prices):
        try:
            default = {
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "calmar_ratio": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "hit_rate": 0.0,
                "annualized_return": 0.0,
                "annualized_volatility": 0.0,
                "cvar_95": 0.0,
                "cvar_99": 0.0,
                "cdar_95": 0.0,
            }
            ret = (
                pd.Series(prices, dtype=float)
                .pct_change()
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
            )
            if len(ret) == 0:
                return default

            ann = 252.0
            rf_annual = 0.03
            rf_daily = rf_annual / ann

            mean_ret = float(ret.mean())
            vol = float(ret.std())
            annualized_return = float(((1 + mean_ret) ** ann) - 1) if mean_ret > -1 else -1.0
            annualized_volatility = float(vol * np.sqrt(ann))

            downside = ret[ret < 0]
            downside_dev = float(downside.std()) if len(downside) > 0 else 0.0

            excess_daily = mean_ret - rf_daily
            sharpe = float((excess_daily / vol) * np.sqrt(ann)) if vol > 0 else 0.0
            sortino = float((excess_daily / downside_dev) * np.sqrt(ann)) if downside_dev > 0 else 0.0

            gross_win = float(ret[ret > 0].sum())
            gross_loss = float(abs(ret[ret < 0].sum()))
            if gross_loss > 0:
                profit_factor = float(gross_win / gross_loss)
            else:
                profit_factor = 10.0 if gross_win > 0 else 0.0

            hit_rate = float((ret > 0).mean())

            cum = (1 + ret).cumprod()
            drawdown = (cum / cum.cummax()) - 1
            max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
            calmar = float(annualized_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0

            # Conditional Drawdown at Risk (95%): the AVERAGE drawdown across the
            # worst 5% of days -- a tail-risk companion to Max Drawdown (a single
            # worst point) and to CVaR (a return, not a drawdown). Negative, like
            # max_drawdown. Descriptive risk metric only; not a forecast.
            if len(drawdown):
                dd_q05 = float(np.percentile(drawdown, 5))
                dd_tail = drawdown[drawdown <= dd_q05]
                cdar_95 = float(dd_tail.mean()) if len(dd_tail) else max_drawdown
            else:
                cdar_95 = 0.0

            var_95 = float(np.percentile(ret, 5))
            var_99 = float(np.percentile(ret, 1))
            tail_95 = ret[ret <= var_95]
            tail_99 = ret[ret <= var_99]
            cvar_95 = float(tail_95.mean()) if len(tail_95) > 0 else var_95
            cvar_99 = float(tail_99.mean()) if len(tail_99) > 0 else var_99

            return {
                "sharpe_ratio": sharpe,
                "sortino_ratio": sortino,
                "calmar_ratio": calmar,
                "max_drawdown": max_drawdown,
                "profit_factor": profit_factor,
                "hit_rate": hit_rate,
                "annualized_return": annualized_return,
                "annualized_volatility": annualized_volatility,
                "cvar_95": cvar_95,
                "cvar_99": cvar_99,
                "cdar_95": cdar_95,
            }
        except Exception:
            return {
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "calmar_ratio": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "hit_rate": 0.0,
                "annualized_return": 0.0,
                "annualized_volatility": 0.0,
                "cvar_95": 0.0,
                "cvar_99": 0.0,
                "cdar_95": 0.0,
            }

    # --- NEW: TECHNICAL INDICATOR CALCULATOR ---
    def _calculate_indicators(self, prices, dates, volatility_vector=None):
        """
        Calculates RSI, MACD, BBands, and a GARCH-enhanced ATR.
        Uses volatility_vector (from R) to synthesize High/Low prices.
        """
        df = pd.DataFrame({'price': prices}, index=pd.to_datetime(dates))
        df['returns'] = df['price'].pct_change().fillna(0)
        
        # Inject GARCH Volatility if available (Default to rolling std if not)
        if volatility_vector is not None and len(volatility_vector) == len(df):
            df['volatility'] = volatility_vector
        else:
            df['returns'] = df['price'].pct_change()
            df['volatility'] = df['returns'].rolling(window=21).std() * np.sqrt(252)
            df['volatility'] = df['volatility'].bfill() # Fill initial NaNs (pandas 2.x: fillna(method='bfill') removed)

        # --- 1. SYNTHETIC HIGH / LOW (The "Smart" Way) ---
        # Daily Volatility = Annual Vol / sqrt(252)
        # Expected Range ~ Price * Daily Vol * 1.25 (Empirical factor for High-Low vs Close-Close)
        daily_vol = df['volatility'] / 15.87  # sqrt(252) approx 15.87
        
        # We assume High is +0.625 sigma and Low is -0.625 sigma from Close
        # This keeps the Close centered but creates a realistic "True Range"
        df['high'] = df['price'] * (1 + (daily_vol * 0.625))
        df['low'] = df['price'] * (1 - (daily_vol * 0.625))
        
        # --- 2. RSI (14) ---
        delta = df['price'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        df['rsi'] = df['rsi'].fillna(50)

        # --- 3. MACD (12, 26, 9) ---
        exp1 = df['price'].ewm(span=12, adjust=False).mean()
        exp2 = df['price'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        
        # --- 4. Bollinger Bands (20, 2) ---
        df['ma20'] = df['price'].rolling(window=20).mean()
        df['std20'] = df['price'].rolling(window=20).std()
        df['upper_band'] = df['ma20'] + (df['std20'] * 2)
        df['lower_band'] = df['ma20'] - (df['std20'] * 2)
        
        # --- 5. ATR (14) - NOW USING SYNTHETIC HIGH/LOW ---
        # True Range is max(High-Low, |High-PrevClose|, |Low-PrevClose|)
        prev_close = df['price'].shift(1)
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()
        
        df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = df['tr'].rolling(window=14).mean()

        return df.fillna(0)

    def _prepare_features(self, historical_df):
        logger.info("Generating features...")
        raw_prices = historical_df['price'].to_numpy()
        q_feats = generate_optimized_quantum_features(raw_prices, n_qubits=4)
        descs = build_pointwise_descriptions(raw_prices, window=12)
        llm_embeds = generate_llm_embeddings(descs)
        pca = PCA(n_components=min(8, llm_embeds.shape[1]))
        llm_feats = pca.fit_transform(llm_embeds)
        v_feats, f_feats = self._fetch_risk_metrics(raw_prices)
        exog_all = np.hstack((q_feats, llm_feats, v_feats.reshape(-1,1), f_feats.reshape(-1,1)))
        return raw_prices, exog_all, pd.to_datetime(historical_df['date'])

    def _fit_arima_model(self, y, exog, order, trend):
        """
        Fit ARIMA with relaxed stationarity/invertibility checks.
        Falls back to trend='n' if a trend specification is invalid.
        """
        tried = [trend]
        if trend != "n":
            tried.append("n")

        last_exc = None
        for tr in tried:
            try:
                model = ARIMA(
                    y,
                    order=order,
                    exog=exog,
                    trend=tr,
                    enforce_stationarity=False,
                    enforce_invertibility=False,
                ).fit()
                return model, tr
            except Exception as exc:
                last_exc = exc
                continue
        raise last_exc

    def _project_future_exog(self, forecast_horizon_days):
        """
        Forecast each exogenous feature with a bounded AR(1)-style recursion
        instead of a fixed scalar decay. Production forward path.
        """
        if self.exogenous_data_for_training is None or len(self.exogenous_data_for_training) == 0:
            base = self.last_exogenous_row.flatten() if self.last_exogenous_row is not None else np.array([])
            return np.tile(base, (forecast_horizon_days, 1))
        return self._project_exog_from(self.exogenous_data_for_training, forecast_horizon_days)

    @staticmethod
    def _project_exog_from(hist, forecast_horizon_days):
        """Project exogenous features forward from an EXPLICIT history prefix,
        using the identical bounded AR(1) recursion as production. This is what
        makes walk-forward validation point-in-time honest: each fold projects
        the future exog from its own train prefix, exactly as production would,
        instead of peeking at the true future exog rows (which encode the future
        price direction/level/vol and inflate the metrics)."""
        hist = np.asarray(hist, dtype=float)
        if hist.ndim == 1:
            hist = hist.reshape(-1, 1)
        n_obs, n_cols = hist.shape
        if n_obs == 0:
            return np.zeros((forecast_horizon_days, n_cols), dtype=float)
        if n_obs == 1:
            return np.repeat(hist, forecast_horizon_days, axis=0)

        future = np.zeros((forecast_horizon_days, n_cols), dtype=float)
        lookback = min(120, n_obs)

        for j in range(n_cols):
            series = hist[:, j]
            recent = series[-lookback:]
            curr = float(recent[-1])

            # Constant features are projected as constant.
            if len(recent) < 3 or float(np.nanstd(recent)) < 1e-10:
                future[:, j] = curr
                continue

            x = recent[:-1]
            y = recent[1:]
            x_mean = float(np.mean(x))
            y_mean = float(np.mean(y))
            denom = float(np.sum((x - x_mean) ** 2))
            if denom <= 1e-12:
                phi = 0.0
            else:
                phi = float(np.sum((x - x_mean) * (y - y_mean)) / denom)
            phi = float(np.clip(phi, -0.98, 0.98))
            intercept = y_mean - (phi * x_mean)

            col_min = float(np.min(recent))
            col_max = float(np.max(recent))
            pad = max(1e-6, 0.10 * (col_max - col_min))
            lo = col_min - pad
            hi = col_max + pad

            for t in range(forecast_horizon_days):
                curr = intercept + (phi * curr)
                curr = float(np.clip(curr, lo, hi))
                future[t, j] = curr

        return future

    @staticmethod
    def _label_regime_from_prices(prices: np.ndarray) -> str:
        """Tag the current volatility regime from trailing price history.

        Uses the same vol-ratio rule as quantum_kernel._label_regimes so regime
        labels are consistent between the QSVC training labels and the
        walk-forward fold tags.
        """
        if len(prices) < 63:
            return "Normal"
        rets = np.diff(np.log(prices))
        recent_vol = float(np.std(rets[-21:])) if len(rets) >= 21 else float(np.std(rets))
        long_vol = float(np.std(rets[-63:])) if len(rets) >= 63 else float(np.std(rets))
        if long_vol < 1e-12:
            return "Normal"
        ratio = recent_vol / long_vol
        if ratio > 1.5:
            return "High_Vol"
        elif ratio < 0.8:
            return "Low_Vol"
        return "Normal"

    MIN_REGIME_FOLDS = 3  # minimum folds in a regime before trusting the per-regime winner

    def _build_walk_forward_splits(self, n_obs, max_splits=3, test_window=15, min_train=120):
        """
        Build anchored walk-forward splits as (train_end, test_end) over price index space.
        """
        splits = []
        test_window = int(max(3, test_window))
        end = int(n_obs)
        while len(splits) < int(max_splits):
            train_end = end - test_window
            if train_end < int(min_train):
                break
            splits.append((train_end, end))
            end = train_end
        splits.reverse()
        return splits

    @staticmethod
    def _fold_quality(actual_prices, pred_prices):
        """Extract per-step metrics WITHIN a fold (no cross-fold boundary artifacts).

        Returns per-fold diffs and point-level errors for safe concatenation.
        """
        actual = np.asarray(actual_prices, dtype=float)
        pred = np.asarray(pred_prices, dtype=float)
        n = min(len(actual), len(pred))
        if n < 2:
            return None
        actual, pred = actual[:n], pred[:n]

        # Point-level: absolute percentage error per step (for MAPE)
        mask = np.abs(actual) > 1e-9
        ape = np.abs((actual[mask] - pred[mask]) / actual[mask])

        # Diff-level (safe within fold, no cross-fold boundary):
        actual_dir = np.sign(np.diff(actual))
        pred_dir = np.sign(np.diff(pred))
        dir_match = (actual_dir == pred_dir).astype(float)

        actual_ret = np.diff(actual) / np.maximum(actual[:-1], 1e-12)
        signal = np.sign(np.diff(pred))
        strat_ret = signal * actual_ret
        excess_ret = strat_ret - actual_ret  # vs buy-and-hold

        return {
            "ape": ape.tolist(),
            "dir_match": dir_match.tolist(),
            "excess_ret": excess_ret.tolist(),
            "n_points": int(n),
            "n_diffs": int(n - 1),
        }

    @staticmethod
    def _aggregate_quality(folds: list) -> dict:
        """Aggregate per-fold metrics by concatenating WITHIN-fold diffs.

        Avoids the two inflation bugs:
        1. Per-fold Sharpe blow-up (tiny denominators on short folds).
        2. Cross-fold boundary artifacts from pooling raw prices then diffing.
        """
        all_ape, all_dir, all_excess = [], [], []
        total_points, total_diffs = 0, 0
        for f in folds:
            if f is None:
                continue
            all_ape.extend(f["ape"])
            all_dir.extend(f["dir_match"])
            all_excess.extend(f["excess_ret"])
            total_points += f["n_points"]
            total_diffs += f["n_diffs"]

        if total_diffs < 2:
            return {"mape": float("nan"), "directional_accuracy": float("nan"),
                    "long_short_sharpe": float("nan"), "n_validation_steps": 0}

        mape = float(np.mean(all_ape)) if all_ape else float("nan")
        dir_acc = float(np.mean(all_dir)) if all_dir else float("nan")

        # Raw per-step information ratio (NOT annualised). Annualising by sqrt(252)
        # on ~42 validation steps where only ~5 have non-zero excess produces absurd
        # numbers (9+). The raw ratio is bounded, comparable across tickers, and honest
        # about the sample size. Typical range: -0.3 to +0.3 for real models.
        excess = np.asarray(all_excess, dtype=float)
        if len(excess) > 5 and float(np.std(excess)) > 1e-12:
            ls_sharpe = float(np.mean(excess) / np.std(excess))
        else:
            ls_sharpe = 0.0

        return {
            "mape": mape,
            "directional_accuracy": dir_acc,
            "long_short_sharpe": ls_sharpe,
            "n_validation_steps": total_points,
        }

    def _walk_forward_validation_scores(self, raw_prices, exog_all, dates, arima_res, lstm_res, prophet_res, bsts_res=None, qrc_res=None):
        """
        Compute walk-forward RMSEs for model families using already-selected hyperparameters.
        This is used to stabilize model-family selection versus a single holdout split.
        """
        n_obs = len(raw_prices)
        if n_obs < 120:
            return {}

        test_window = min(20, max(5, n_obs // 12))
        min_train = max(80, self.lstm_lookback + 20)
        # Scale max_splits with available data so regime-conditional selection
        # has enough folds per regime. With 500 days: 8 splits. 1000+: 10 (cap).
        adaptive_max_splits = max(3, min(10, n_obs // 60))
        splits = self._build_walk_forward_splits(
            n_obs=n_obs,
            max_splits=adaptive_max_splits,
            test_window=test_window,
            min_train=min_train,
        )
        if not splits:
            return {}

        log_prices = np.log(raw_prices)
        log_returns = np.log(raw_prices[1:] / raw_prices[:-1])
        exog_ret = exog_all[1:]

        arima_scores = []
        lstm_scores = []
        prophet_scores = []
        # Per-model quality metrics (MAPE, directional accuracy, long/short Sharpe)
        quality: Dict[str, List[Dict[str, float]]] = {
            "arima": [], "lstm": [], "prophet": [], "bsts": [], "qrc": [],
        }
        # Per-fold regime tags + per-model RMSE for regime-conditional selection
        fold_regime_tags: List[str] = []
        fold_model_rmse: List[Dict[str, float]] = []

        # Tag each fold with its volatility regime (for regime-conditional selection)
        for train_end, _ in splits:
            fold_regime_tags.append(self._label_regime_from_prices(raw_prices[:train_end]))
            fold_model_rmse.append({})

        # --- ARIMA ---
        arima_target = arima_res.get("target", "levels")
        arima_order = tuple(arima_res.get("params", {}).get("order", (1, 1, 0)))
        arima_trend = arima_res.get("params", {}).get("trend", "n")
        for fold_i, (train_end, test_end) in enumerate(splits):
            try:
                if arima_target == "returns":
                    if train_end < 3:
                        continue
                    train_y = log_returns[: train_end - 1]
                    test_y = log_returns[train_end - 1 : test_end - 1]
                    train_ex = exog_ret[: train_end - 1]
                    # Point-in-time: project the future exog from the train
                    # prefix (as production does), never slice the true future.
                    test_ex = self._project_exog_from(train_ex, len(test_y))
                    if len(test_y) == 0 or len(train_y) < 20:
                        continue
                    model, _ = self._fit_arima_model(train_y, train_ex, arima_order, arima_trend)
                    fc_ret = model.get_forecast(steps=len(test_y), exog=test_ex).predicted_mean
                    base_price = raw_prices[train_end - 1]
                    pred_prices = self._reconstruct_test_prices(fc_ret, base_price)
                    actual_prices = self._reconstruct_test_prices(test_y, base_price)
                    fold_rmse = self._calculate_rmse(actual_prices, pred_prices)
                    arima_scores.append(fold_rmse)
                    fold_model_rmse[fold_i]["arima"] = fold_rmse
                    quality["arima"].append(self._fold_quality(actual_prices, pred_prices))
                else:
                    train_y = log_prices[:train_end]
                    test_y = log_prices[train_end:test_end]
                    train_ex = exog_all[:train_end]
                    # Point-in-time: project future exog from the train prefix.
                    test_ex = self._project_exog_from(train_ex, len(test_y))
                    if len(test_y) == 0 or len(train_y) < 20:
                        continue
                    model, _ = self._fit_arima_model(train_y, train_ex, arima_order, arima_trend)
                    fc_log = model.get_forecast(steps=len(test_y), exog=test_ex).predicted_mean
                    fold_rmse = self._calculate_rmse(np.exp(test_y), np.exp(fc_log))
                    arima_scores.append(fold_rmse)
                    fold_model_rmse[fold_i]["arima"] = fold_rmse
                    quality["arima"].append(self._fold_quality(np.exp(test_y), np.exp(fc_log)))
            except Exception:
                continue

        # --- LSTM (returns-based) ---
        lstm_params = lstm_res.get("params", {"neurons": 50, "epochs": 50})
        lstm_neurons = int(lstm_params.get("neurons", 50))
        # Note: LSTM/Prophet/BSTS/QRC loops below MUST use enumerate(splits) to match fold indices
        lstm_epochs = int(lstm_params.get("epochs", 50))
        for fold_i, (train_end, test_end) in enumerate(splits):
            try:
                if train_end <= self.lstm_lookback + 5:
                    continue
                train_ret_y = log_returns[: train_end - 1]
                test_ret_y = log_returns[train_end - 1 : test_end - 1]
                train_ret_X = exog_ret[: train_end - 1]
                # Point-in-time: project future exog from the train prefix.
                test_ret_X = self._project_exog_from(train_ret_X, len(test_ret_y))
                if len(test_ret_y) == 0 or len(train_ret_y) <= self.lstm_lookback + 2:
                    continue

                # LSTM
                X_train, y_train = self._make_supervised(train_ret_y, train_ret_X, self.lstm_lookback)
                model, scaler = self._build_and_train_lstm(X_train, y_train, lstm_neurons, lstm_epochs)
                pred_rets = []
                curr_input = np.concatenate(
                    [
                        scaler.transform(train_ret_y[-self.lstm_lookback:].reshape(-1, 1)),
                        train_ret_X[-self.lstm_lookback:],
                    ],
                    axis=1,
                ).reshape(1, self.lstm_lookback, -1)
                for i in range(len(test_ret_y)):
                    pred_sc = model.predict(curr_input, verbose=0)[0][0]
                    pred_ret = float(scaler.inverse_transform([[pred_sc]])[0][0])
                    pred_rets.append(pred_ret)
                    new_row = np.concatenate([np.array([[pred_sc]]), test_ret_X[i : i + 1]], axis=1)
                    curr_input = np.concatenate([curr_input[:, 1:, :], new_row.reshape(1, 1, -1)], axis=1)
                base_price = raw_prices[train_end - 1]
                pred_prices = self._reconstruct_test_prices(pred_rets, base_price)
                actual_prices = self._reconstruct_test_prices(test_ret_y, base_price)
                fold_rmse = self._calculate_rmse(actual_prices, pred_prices)
                lstm_scores.append(fold_rmse)
                fold_model_rmse[fold_i]["lstm"] = fold_rmse
                quality["lstm"].append(self._fold_quality(actual_prices, pred_prices))
            except Exception:
                continue

        # --- Prophet ---
        prophet_params = prophet_res.get("params") or {"changepoint_prior_scale": 0.05}
        reg_names = [f'R{i}' for i in range(exog_all.shape[1])]
        for fold_i, (train_end, test_end) in enumerate(splits):
            try:
                train_y = log_prices[:train_end]
                test_y = log_prices[train_end:test_end]
                train_ex = exog_all[:train_end]
                # Point-in-time: project future exog from the train prefix.
                test_ex = self._project_exog_from(train_ex, len(test_y))
                if len(test_y) == 0 or len(train_y) < 30:
                    continue

                df_train = pd.DataFrame({'ds': pd.to_datetime(dates[:train_end]), 'y': train_y})
                for i, name in enumerate(reg_names):
                    df_train[name] = train_ex[:, i]

                m = Prophet(**prophet_params)
                for name in reg_names:
                    m.add_regressor(name)
                m.fit(df_train)

                fut = m.make_future_dataframe(periods=len(test_y))
                full_ex = np.vstack([train_ex, test_ex])
                for i, name in enumerate(reg_names):
                    fut[name] = full_ex[:len(fut), i]
                fc_log = m.predict(fut).tail(len(test_y))['yhat'].values
                fold_rmse = self._calculate_rmse(np.exp(test_y), np.exp(fc_log))
                prophet_scores.append(fold_rmse)
                fold_model_rmse[fold_i]["prophet"] = fold_rmse
                quality["prophet"].append(self._fold_quality(np.exp(test_y), np.exp(fc_log)))
            except Exception:
                continue

        # --- BSTS ---
        bsts_scores = []
        if bsts_res and bsts_res.get("params", {}).get("config"):
            bsts_config = bsts_res["params"]["config"]
            for fold_i, (train_end, test_end) in enumerate(splits):
                try:
                    train_y = log_prices[:train_end]
                    test_y = log_prices[train_end:test_end]
                    train_ex = exog_all[:train_end]
                    if len(test_y) == 0 or len(train_y) < 30:
                        continue
                    y_mean, y_std = np.mean(train_y), np.std(train_y)
                    train_y_std = (train_y - y_mean) / (y_std + 1e-6)
                    ex_mean, ex_std = np.mean(train_ex, axis=0), np.std(train_ex, axis=0)
                    train_ex_std = (train_ex - ex_mean) / (ex_std + 1e-6)

                    comps = []
                    if bsts_config.get('trend') == 'semilocal':
                        comps.append(sts.SemiLocalLinearTrend(observed_time_series=train_y_std))
                    else:
                        comps.append(sts.LocalLinearTrend(observed_time_series=train_y_std))
                    if bsts_config.get('seasonal'):
                        comps.append(sts.Seasonal(num_seasons=5, num_steps_per_season=1, observed_time_series=train_y_std))
                    comps.append(sts.LinearRegression(design_matrix=train_ex_std, weights_prior=tfp.distributions.Horseshoe(scale=1.0)))
                    model = sts.Sum(comps, observed_time_series=train_y_std)
                    posteriors = tfp.sts.build_factored_surrogate_posterior(model=model)
                    optimizer = tf.optimizers.Adam(learning_rate=0.1)
                    @tf.function(jit_compile=True)
                    def train_vi_wf():
                        return tfp.vi.fit_surrogate_posterior(
                            target_log_prob_fn=model.joint_log_prob(observed_time_series=train_y_std),
                            surrogate_posterior=posteriors, optimizer=optimizer, num_steps=80)
                    train_vi_wf()
                    samples = posteriors.sample(30)
                    fc_dist = tfp.sts.forecast(model=model, observed_time_series=train_y_std,
                                               parameter_samples=samples, num_steps_forecast=len(test_y))
                    fc_mean_std = np.mean(fc_dist.mean().numpy()[:, :, 0], axis=0)
                    fc_log_prices = (fc_mean_std * y_std) + y_mean
                    fold_rmse = self._calculate_rmse(np.exp(test_y), np.exp(fc_log_prices))
                    bsts_scores.append(fold_rmse)
                    fold_model_rmse[fold_i]["bsts"] = fold_rmse
                    quality["bsts"].append(self._fold_quality(np.exp(test_y), np.exp(fc_log_prices)))
                except Exception:
                    continue

        # --- QRC walk-forward ---
        qrc_wf_scores = []
        if qrc_res is not None:
            qrc_cfg = qrc_res.get("config")
            for fold_i, (train_end, test_end) in enumerate(splits):
                try:
                    if train_end <= (qrc_cfg.washout_steps + 30):
                        continue
                    actual_prices = raw_prices[train_end:test_end]
                    if len(actual_prices) == 0:
                        continue
                    model = QuantumReservoirForecaster(qrc_cfg).fit(raw_prices[:train_end])
                    preds = model.forecast(len(actual_prices))
                    fold_rmse = self._calculate_rmse(actual_prices, preds)
                    qrc_wf_scores.append(fold_rmse)
                    fold_model_rmse[fold_i]["qrc"] = fold_rmse
                    quality["qrc"].append(self._fold_quality(actual_prices, preds))
                except Exception:
                    continue

        out = {}
        if arima_scores:
            out["arima"] = float(np.mean(arima_scores))
        if lstm_scores:
            out["lstm"] = float(np.mean(lstm_scores))
        if prophet_scores:
            out["prophet"] = float(np.mean(prophet_scores))
        if bsts_scores:
            out["bsts"] = float(np.mean(bsts_scores))
        if qrc_wf_scores:
            out["qrc"] = float(np.mean(qrc_wf_scores))

        # Pool raw (actual, pred) pairs across folds per model, then compute metrics once.
        quality_agg: Dict[str, Dict[str, float]] = {}
        for model_name, folds in quality.items():
            valid_folds = [f for f in folds if f is not None]
            if not valid_folds:
                continue
            quality_agg[model_name] = self._aggregate_quality(valid_folds)
        out["_quality"] = quality_agg

        # Regime-conditional scores: group per-fold RMSE by regime tag.
        # Output: {"Normal": {"arima": mean_rmse, ...}, "High_Vol": {...}, ...}
        from collections import defaultdict
        regime_rmse_accum: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for fold_i, regime in enumerate(fold_regime_tags):
            for model_name, rmse_val in fold_model_rmse[fold_i].items():
                if np.isfinite(rmse_val):
                    regime_rmse_accum[regime][model_name].append(rmse_val)
        regime_scores: Dict[str, Dict[str, Any]] = {}
        for regime, models in regime_rmse_accum.items():
            regime_scores[regime] = {}
            for model_name, rmse_list in models.items():
                regime_scores[regime][model_name] = {
                    "mean_rmse": float(np.mean(rmse_list)),
                    "n_folds": len(rmse_list),
                }
            # Determine best model for this regime
            candidates = {m: v["mean_rmse"] for m, v in regime_scores[regime].items() if v["n_folds"] >= 1}
            if candidates:
                regime_scores[regime]["_best"] = min(candidates, key=candidates.get)
        out["_regime_scores"] = regime_scores
        out["_fold_regimes"] = fold_regime_tags
        return out

    def _default_stochastic_seed(self, forecast_horizon_days):
        if self.trained_history_df is None or len(self.trained_history_df) == 0:
            return 42
        last_date = pd.to_datetime(self.trained_history_df['date'].iloc[-1])
        date_part = int((last_date.value // 10**9) & 0xFFFFFFFF)
        price_part = int(abs(float(self.last_actual_price or 0.0)) * 1000.0) & 0xFFFFFFFF
        len_part = int(len(self.trained_history_df)) & 0xFFFFFFFF
        seed = (date_part ^ (price_part * 2654435761) ^ (len_part * 2246822519) ^ int(forecast_horizon_days * 97)) & 0xFFFFFFFF
        return seed or 42

    def _build_stochastic_representative_path(self, deterministic_prices, n_paths=250, seed=42):
        """
        Build a deterministic-by-seed stochastic representative path around the
        model mean forecast using bootstrapped historical return residuals.
        """
        if self.trained_history_df is None or len(deterministic_prices) == 0:
            return deterministic_prices, [], []

        hist_prices = np.asarray(self.trained_history_df['price'].values, dtype=float)
        if len(hist_prices) < 3:
            return deterministic_prices, [], []

        base = np.asarray(deterministic_prices, dtype=float)
        n_h = len(base)
        base_prev = np.concatenate([[hist_prices[-1]], base[:-1]])
        base_log_ret = np.log(np.maximum(base, 1e-12) / np.maximum(base_prev, 1e-12))

        hist_log_ret = np.diff(np.log(np.maximum(hist_prices, 1e-12)))
        if len(hist_log_ret) < 5:
            return deterministic_prices, [], []

        residual_pool = hist_log_ret - float(np.mean(hist_log_ret))
        residual_pool = residual_pool[np.isfinite(residual_pool)]
        if len(residual_pool) == 0:
            return deterministic_prices, [], []

        daily_ref_sigma = float(np.std(hist_log_ret[-min(252, len(hist_log_ret)):]))
        daily_ref_sigma = max(daily_ref_sigma, 1e-6)
        sigma_fc = np.asarray(getattr(self, "sigma_fc_mean", []) or [], dtype=float)

        n_paths = int(max(50, min(1000, n_paths)))
        rng = np.random.default_rng(int(seed))
        sims = np.zeros((n_paths, n_h), dtype=float)
        for p in range(n_paths):
            curr = float(hist_prices[-1])
            for t in range(n_h):
                shock = float(rng.choice(residual_pool))
                vol_scale = 1.0
                if t < len(sigma_fc):
                    daily_target = float(sigma_fc[t]) / np.sqrt(252.0)
                    if np.isfinite(daily_target) and daily_target > 0:
                        vol_scale = float(np.clip(daily_target / daily_ref_sigma, 0.5, 2.5))
                step_ret = float(base_log_ret[t]) + (shock * vol_scale * 0.70)
                curr = curr * np.exp(step_ret)
                sims[p, t] = curr

        # Select the path with median realized volatility (typical choppiness)
        # rather than median terminal price (which biases toward smooth paths).
        sim_log_ret = np.diff(np.log(np.maximum(sims, 1e-12)), axis=1)
        realized_vol = np.std(sim_log_ret, axis=1)
        med_vol = float(np.median(realized_vol))
        rep_idx = int(np.argmin(np.abs(realized_vol - med_vol)))
        representative = sims[rep_idx, :]
        lo = np.percentile(sims, 2.5, axis=0)
        hi = np.percentile(sims, 97.5, axis=0)
        return representative.tolist(), lo.tolist(), hi.tolist()

    # ----------------------------------------------------------------
    # TRAIN
    # ----------------------------------------------------------------
    def train(self, historical_df, ticker=None):
        logger.info("Starting training process...")
        self.trained_history_df = historical_df.copy()
        self.last_actual_price = historical_df['price'].iloc[-1]
        self.ticker = ticker

        raw_prices, exog_all, dates = self._prepare_features(historical_df)
        self.exogenous_data_for_training = exog_all
        self.last_exogenous_row = exog_all[-1:, :].copy()
        self._raw_prices = raw_prices

        log_returns = np.log(raw_prices[1:] / raw_prices[:-1])
        exog_ret = exog_all[1:]
        
        log_prices = np.log(raw_prices)
        exog_lev = exog_all
        df_prophet = pd.DataFrame({'ds': dates, 'y': log_prices}) 
        
        test_size = 30 if len(raw_prices) > 50 else 5
        
        # Point-in-time: the single-split validators must NOT see the true
        # future exog either (same leak as the walk-forward path). Project the
        # test-window exog from the train prefix, exactly as production does.
        train_ret_y, test_ret_y = log_returns[:-test_size], log_returns[-test_size:]
        train_ret_X = exog_ret[:-test_size]
        test_ret_X = self._project_exog_from(train_ret_X, test_size)

        train_lev_y, test_lev_y = log_prices[:-test_size], log_prices[-test_size:]
        train_lev_X = exog_lev[:-test_size]
        test_lev_X = self._project_exog_from(train_lev_X, test_size)
        
        train_df_pro = df_prophet.iloc[:-test_size]

        # --- GRID SEARCH ---
        arima_res = self._arima_grid_search(
            train_lev_y,
            train_lev_X,
            test_lev_y,
            test_lev_X,
            train_ret_y,
            train_ret_X,
            test_ret_y,
            test_ret_X,
            base_price=raw_prices[-(test_size + 1)],
        )
        lstm_res = self._lstm_grid_search(train_ret_y, train_ret_X, test_ret_y, test_ret_X, base_price=raw_prices[-(test_size+1)])
        prophet_res = self._prophet_grid_search(train_df_pro, train_lev_X, test_lev_y, test_lev_X)
        bsts_res = self._bsts_grid_search(train_lev_y, train_lev_X, test_lev_y, test_lev_X)
        qrc_res = self._qrc_single_split(raw_prices, test_size)

        split_scores = {
            'arima': arima_res['rmse'],
            'lstm': lstm_res['rmse'],
            'prophet': prophet_res['rmse'],
            'bsts': bsts_res['rmse'],
            'qrc': qrc_res['rmse'],
        }

        wf_scores = self._walk_forward_validation_scores(
            raw_prices=raw_prices,
            exog_all=exog_all,
            dates=dates,
            arima_res=arima_res,
            lstm_res=lstm_res,
            prophet_res=prophet_res,
            bsts_res=bsts_res,
            qrc_res=qrc_res,
        )

        scores = {}
        wf_weight = 0.50
        for model_name, split_rmse in split_scores.items():
            wf_rmse = wf_scores.get(model_name)
            if wf_rmse is not None and np.isfinite(wf_rmse):
                scores[model_name] = ((1.0 - wf_weight) * split_rmse) + (wf_weight * float(wf_rmse))
            else:
                scores[model_name] = split_rmse

        # Extract per-model quality metrics and regime scores from walk-forward folds
        wf_quality = wf_scores.get("_quality", {})
        wf_regime_scores = wf_scores.get("_regime_scores", {})
        wf_scores_clean = {k: v for k, v in wf_scores.items() if not k.startswith("_")}

        self.validation_scores = {
            "single_split_rmse": split_scores,
            "walk_forward_rmse": wf_scores_clean,
            "combined_rmse": scores,
            "walk_forward_weight": wf_weight,
            "quality_per_model": wf_quality,
            "regime_scores": wf_regime_scores,
        }

        # --- Regime-conditional winner selection ---
        # 1. Determine current regime from the full training data.
        current_regime = self._label_regime_from_prices(raw_prices)
        global_winner = min(scores, key=scores.get)

        # 2. Check if the current regime has enough validation folds
        #    and a different best model than the global winner.
        regime_data = wf_regime_scores.get(current_regime, {})
        regime_best = regime_data.get("_best")
        regime_n_folds = regime_data.get(regime_best, {}).get("n_folds", 0) if regime_best else 0

        if (
            regime_best
            and regime_best != global_winner
            and regime_n_folds >= self.MIN_REGIME_FOLDS
            and regime_best in scores  # must be a valid candidate
        ):
            self.winner_model_name = regime_best
            logger.info(
                "Regime-conditional selection: regime=%s winner=%s "
                "(regime RMSE=%.4f, n_folds=%d) overrides global winner=%s (RMSE=%.4f)",
                current_regime, regime_best,
                regime_data[regime_best]["mean_rmse"], regime_n_folds,
                global_winner, scores[global_winner],
            )
        else:
            self.winner_model_name = global_winner
            logger.info(
                "Winner: %s (combined RMSE: %.4f, split RMSE: %.4f, regime: %s%s)",
                self.winner_model_name,
                scores[self.winner_model_name],
                split_scores[self.winner_model_name],
                current_regime,
                f", regime_best={regime_best} but n_folds={regime_n_folds}<{self.MIN_REGIME_FOLDS}"
                if regime_best and regime_best != global_winner else "",
            )

        # Store regime metadata for the response and audit trail
        self.current_regime = current_regime
        self.selection_mode = "regime_conditional" if self.winner_model_name != global_winner else "global"
        self.global_winner = global_winner

        self._fit_winner(log_returns, exog_ret, log_prices, exog_lev, df_prophet,
                         arima_res, lstm_res, prophet_res, bsts_res, qrc_res, raw_prices)

    def _fit_winner(self, ret_y, ret_X, lev_y, lev_X, df_pro, ar_res, lst_res, pro_res, bsts_res, qrc_res=None, raw_prices=None):
        if self.winner_model_name == 'arima':
            p = ar_res['params']
            self.arima_target = ar_res.get('target', 'levels')
            if self.arima_target == 'returns':
                self.winner_model, _ = self._fit_arima_model(ret_y, ret_X, p['order'], p['trend'])
            else:
                self.winner_model, _ = self._fit_arima_model(lev_y, lev_X, p['order'], p['trend'])
        elif self.winner_model_name == 'prophet':
            m = Prophet(**pro_res['params'])
            # We properly indent both actions inside the loop
            for i in range(lev_X.shape[1]):
                col_name = f'R{i}'
                m.add_regressor(col_name)
                df_pro[col_name] = lev_X[:, i]
            
            m.fit(df_pro)
            self.winner_model = m
        elif self.winner_model_name == 'bsts':
            config = bsts_res['params']['config']
            y_mean, y_std = np.mean(lev_y), np.std(lev_y)
            y_std_data = (lev_y - y_mean) / (y_std + 1e-6)
            ex_mean, ex_std = np.mean(lev_X, axis=0), np.std(lev_X, axis=0)
            ex_std_data = (lev_X - ex_mean) / (ex_std + 1e-6)
            
            components = []
            if config['trend'] == 'semilocal': components.append(sts.SemiLocalLinearTrend(observed_time_series=y_std_data))
            else: components.append(sts.LocalLinearTrend(observed_time_series=y_std_data))
            if config['seasonal']: components.append(sts.Seasonal(num_seasons=5, num_steps_per_season=1, observed_time_series=y_std_data))
            components.append(sts.LinearRegression(design_matrix=ex_std_data, weights_prior=tfp.distributions.Horseshoe(scale=1.0)))
            
            model = sts.Sum(components, observed_time_series=y_std_data)
            @tf.function(jit_compile=True)
            def run_hmc(): return tfp.sts.fit_with_hmc(model=model, observed_time_series=y_std_data, num_results=100, num_warmup_steps=50, num_leapfrog_steps=15, step_size=0.1, seed=42)
            samples, _ = run_hmc()
            self.winner_model = {'model': model, 'samples': samples, 'stats': (y_mean, y_std, ex_mean, ex_std)}

        elif self.winner_model_name == 'lstm':
            X_all, y_all = self._make_supervised(ret_y, ret_X, self.lstm_lookback)
            model, _ = self._build_and_train_lstm(X_all, y_all, lst_res['params']['neurons'], lst_res['params']['epochs'])
            self.winner_model = model

        elif self.winner_model_name == 'qrc':
            cfg = (qrc_res or {}).get("config") or QRCConfig()
            prices_series = raw_prices if raw_prices is not None else self._raw_prices
            self.winner_model = QuantumReservoirForecaster(cfg).fit(prices_series)

    def _reconstruct_test_prices(self, pred_log_returns, base_price):
        prices = []
        curr = base_price
        for r in pred_log_returns:
            nxt = curr * np.exp(r)
            prices.append(nxt)
            curr = nxt
        return prices

    def _lstm_grid_search(self, train_y, train_ex, test_y, test_ex, base_price):
        X_train, y_train = self._make_supervised(train_y, train_ex, self.lstm_lookback)
        best_score = float('inf')
        best_params = None
        for n in [50, 100]:
            for e in [50, 100]:
                try:
                    model, scaler = self._build_and_train_lstm(X_train, y_train, n, e)
                    pred_rets = []
                    curr_input = np.concatenate([scaler.transform(train_y[-self.lstm_lookback:].reshape(-1,1)), train_ex[-self.lstm_lookback:]], axis=1).reshape(1, self.lstm_lookback, -1)
                    for i in range(len(test_y)):
                        pred_sc = model.predict(curr_input, verbose=0)[0][0]
                        pred_ret = float(scaler.inverse_transform([[pred_sc]])[0][0])
                        pred_rets.append(pred_ret)
                        new_row = np.concatenate([np.array([[pred_sc]]), test_ex[i:i+1]], axis=1)
                        curr_input = np.concatenate([curr_input[:, 1:, :], new_row.reshape(1, 1, -1)], axis=1)
                    pred_prices = self._reconstruct_test_prices(pred_rets, base_price)
                    actual_prices = self._reconstruct_test_prices(test_y, base_price)
                    score = self._calculate_rmse(actual_prices, pred_prices)
                    if score < best_score:
                        best_score = score
                        best_params = {'neurons': n, 'epochs': e}
                except: continue
        return {'rmse': best_score, 'params': best_params or {'neurons':50,'epochs':50}}

    def _qrc_single_split(self, raw_prices, test_size):
        """Fit QRC on the train prefix of raw prices, score on the held-out test tail.

        Config is loaded from per-ticker cache (tuned weekly offline). Never auto-tunes
        inside training; falls back to default config if no cache is present.
        """
        try:
            train_prices = raw_prices[:-test_size]
            actual = raw_prices[-test_size:]
            cache_result = load_qrc_cached_config(
                self.ticker or "", current_n_points=len(raw_prices)
            )
            cfg = cache_result["config"]
            if len(train_prices) < (cfg.washout_steps + 30):
                return {"rmse": float("inf"), "config": cfg, "cache_source": cache_result["source"],
                        "stale_triggers": cache_result["stale_triggers"]}
            model = QuantumReservoirForecaster(cfg).fit(train_prices)
            preds = model.forecast(test_size)
            rmse = self._calculate_rmse(actual, preds)
            return {
                "rmse": rmse,
                "config": cfg,
                "cache_source": cache_result["source"],
                "stale_triggers": cache_result["stale_triggers"],
            }
        except Exception as e:
            logger.debug("QRC single-split failed: %s", e)
            return {"rmse": float("inf"), "config": None, "cache_source": "error", "stale_triggers": []}

    def _bsts_grid_search(self, train_y, train_ex, test_y, test_ex):
        y_mean, y_std = np.mean(train_y), np.std(train_y)
        train_y_std = (train_y - y_mean) / (y_std + 1e-6)
        ex_mean, ex_std = np.mean(train_ex, axis=0), np.std(train_ex, axis=0)
        train_ex_std = (train_ex - ex_mean) / (ex_std + 1e-6)
        best_rmse = float('inf')
        best_config = None
        configs = [{'trend': 'linear', 'seasonal': False}, {'trend': 'semilocal', 'seasonal': True}]
        for config in configs:
            try:
                comps = []
                if config['trend'] == 'semilocal': comps.append(sts.SemiLocalLinearTrend(observed_time_series=train_y_std))
                else: comps.append(sts.LocalLinearTrend(observed_time_series=train_y_std))
                if config['seasonal']: comps.append(sts.Seasonal(num_seasons=5, num_steps_per_season=1, observed_time_series=train_y_std))
                comps.append(sts.LinearRegression(design_matrix=train_ex_std, weights_prior=tfp.distributions.Horseshoe(scale=1.0)))
                model = sts.Sum(comps, observed_time_series=train_y_std)
                posteriors = tfp.sts.build_factored_surrogate_posterior(model=model)
                optimizer = tf.optimizers.Adam(learning_rate=0.1)
                @tf.function(jit_compile=True)
                def train_vi(): return tfp.vi.fit_surrogate_posterior(target_log_prob_fn=model.joint_log_prob(observed_time_series=train_y_std), surrogate_posterior=posteriors, optimizer=optimizer, num_steps=100)
                train_vi() 
                samples = posteriors.sample(30)
                fc_dist = tfp.sts.forecast(model=model, observed_time_series=train_y_std, parameter_samples=samples, num_steps_forecast=len(test_y))
                fc_mean_std = np.mean(fc_dist.mean().numpy()[:, :, 0], axis=0)
                fc_log_prices = (fc_mean_std * y_std) + y_mean
                fc_real_prices = np.exp(fc_log_prices)
                actual_real_prices = np.exp(test_y)
                rmse = self._calculate_rmse(actual_real_prices, fc_real_prices)
                if rmse < best_rmse:
                    best_rmse = rmse
                    best_config = config
            except Exception: continue
        return {'rmse': best_rmse, 'params': {'config': best_config}}

    def _arima_grid_search(
        self,
        train_lev_y,
        train_lev_ex,
        test_lev_y,
        test_lev_ex,
        train_ret_y,
        train_ret_ex,
        test_ret_y,
        test_ret_ex,
        base_price,
    ):
        best_score = float('inf')
        best_params = {'order': (1, 1, 0), 'trend': 'n'}
        best_target = 'levels'

        # Evaluate level-based ARIMA on log-prices.
        for p in [0, 1, 2]:
            for d in [0, 1]:
                for q in [0, 1, 2]:
                    for trend in (['n', 'c'] if d == 0 else ['n']):
                        try:
                            model, used_trend = self._fit_arima_model(
                                train_lev_y, train_lev_ex, (p, d, q), trend
                            )
                            fc_log = model.get_forecast(
                                steps=len(test_lev_y), exog=test_lev_ex
                            ).predicted_mean
                            fc_price = np.exp(fc_log)
                            act_price = np.exp(test_lev_y)
                            score = self._calculate_rmse(act_price, fc_price)
                            if score < best_score:
                                best_score = score
                                best_params = {'order': (p, d, q), 'trend': used_trend}
                                best_target = 'levels'
                        except Exception:
                            continue

        # Evaluate returns-based ARIMA on log-returns and reconstruct prices.
        for p in [0, 1, 2]:
            for d in [0, 1]:
                for q in [0, 1, 2]:
                    for trend in (['n', 'c'] if d == 0 else ['n']):
                        try:
                            model, used_trend = self._fit_arima_model(
                                train_ret_y, train_ret_ex, (p, d, q), trend
                            )
                            fc_ret = model.get_forecast(
                                steps=len(test_ret_y), exog=test_ret_ex
                            ).predicted_mean
                            pred_prices = self._reconstruct_test_prices(fc_ret, base_price)
                            actual_prices = self._reconstruct_test_prices(test_ret_y, base_price)
                            score = self._calculate_rmse(actual_prices, pred_prices)
                            if score < best_score:
                                best_score = score
                                best_params = {'order': (p, d, q), 'trend': used_trend}
                                best_target = 'returns'
                        except Exception:
                            continue

        return {
            'rmse': best_score,
            'params': best_params,
            'target': best_target,
        }

    def _prophet_grid_search(self, train_df, train_ex, test_y, test_ex):
        best_score = float('inf')
        best_params = None
        reg_names = [f'R{i}' for i in range(train_ex.shape[1])]
        df_t = train_df.copy()
        for i, name in enumerate(reg_names): df_t[name] = train_ex[:, i]
        for cps in [0.05, 0.5]:
            try:
                m = Prophet(changepoint_prior_scale=cps)
                for name in reg_names: m.add_regressor(name)
                m.fit(df_t)
                fut = m.make_future_dataframe(periods=len(test_y))
                full_ex = np.vstack([train_ex, test_ex])
                for i, name in enumerate(reg_names): fut[name] = full_ex[:len(fut), i]
                fc_log = m.predict(fut).tail(len(test_y))['yhat'].values
                fc_price = np.exp(fc_log)
                act_price = np.exp(test_y)
                score = self._calculate_rmse(act_price, fc_price)
                if score < best_score:
                    best_score = score
                    best_params = {'changepoint_prior_scale': cps}
            except: continue
        return {'rmse': best_score, 'params': best_params}

    def _build_and_train_lstm(self, X, y, neurons, epochs):
        scaler = MinMaxScaler(feature_range=(0, 1))
        y_scaled = scaler.fit_transform(y.reshape(-1, 1))
        model = Sequential([
            Input(shape=(X.shape[1], X.shape[2])),
            LSTM(neurons, activation='tanh'),
            Dense(1)
        ])
        model.compile(optimizer='adam', loss='mse')
        es = EarlyStopping(monitor='loss', patience=5, restore_best_weights=True)
        model.fit(X, y_scaled, epochs=epochs, batch_size=16, verbose=0, callbacks=[es])
        model.scaler = scaler
        return model, scaler

    def _make_supervised(self, endog, exog, lookback):
        X, y = [], []
        for t in range(lookback, len(endog)):
            X.append(np.concatenate([endog[t-lookback:t].reshape(-1,1), exog[t-lookback:t]], axis=1))
            y.append(endog[t])
        return np.stack(X), np.array(y)

    def _apply_explosion_sanity_gate(self, forecast_prices, upper_ci, lower_ci, horizon_days, sigma_mult=10.0):
        """Detect numerically explosive forecasts and substitute a geometric fallback.

        Any model in the ensemble can produce divergent output on certain return-series
        shapes — Portfolio 3 (ETF Core) hit ARIMA non-stationary divergence with
        max forecast = 1.19e189, which the UI rendered as flat zero and all derived
        metrics collapsed to 0. The same can happen at the per-asset level. If the
        forecast leaves a `sigma_mult`-σ envelope around the last historical price,
        replace it with a geometric extrapolation at historical drift so downstream
        consumers always receive finite, plot-able values.

        Returns: (forecast_prices, upper_ci, lower_ci, meta_or_None). meta carries
        model_used / forecast_quality / forecast_quality_reason overrides for the
        response dict; None means no explosion was detected and inputs are unchanged.
        """
        fp = list(forecast_prices or [])
        if not fp:
            return forecast_prices, upper_ci, lower_ci, None

        try:
            hist_prices = self.trained_history_df["price"].astype(float).values
        except Exception:
            return forecast_prices, upper_ci, lower_ci, None
        if len(hist_prices) <= 1:
            return forecast_prices, upper_ci, lower_ci, None

        last_hist = float(hist_prices[-1])
        hist_std = float(pd.Series(hist_prices).std()) or 1.0
        upper_bound = last_hist + sigma_mult * hist_std
        lower_bound = max(0.01, last_hist - sigma_mult * hist_std)
        fp_finite = [p for p in fp if isinstance(p, (int, float)) and np.isfinite(p)]
        exploded = (
            len(fp_finite) != len(fp)
            or any(p > upper_bound or p < lower_bound for p in fp_finite)
        )
        if not exploded:
            return forecast_prices, upper_ci, lower_ci, None

        fp_max = max(fp_finite) if fp_finite else float("nan")
        prev_model = self.winner_model_name or "unknown"
        logger.warning(
            f"HybridForecaster sanity gate: '{prev_model}' forecast exploded "
            f"(max={fp_max:.3e}, last_hist={last_hist:.2f}, "
            f"{sigma_mult:.0f}sigma_upper={upper_bound:.2f}); substituting geometric extrapolation"
        )
        first_hist = float(hist_prices[0])
        n_hist = len(hist_prices)
        daily_drift = (
            (last_hist / first_hist) ** (1.0 / max(1, n_hist - 1)) - 1.0
            if first_hist > 0 else 0.0
        )
        h = int(horizon_days)
        fallback_prices = [last_hist * (1.0 + daily_drift) ** i for i in range(1, h + 1)]
        fallback_upper = [p * 1.1 for p in fallback_prices]
        fallback_lower = [p * 0.9 for p in fallback_prices]
        meta = {
            "model_used": f"{prev_model}_fallback_geom",
            "forecast_quality": "fallback_post_explosion",
            "forecast_quality_reason": (
                f"original {prev_model} forecast exceeded {sigma_mult:.0f}sigma envelope "
                f"(max={fp_max:.3e}, bound={upper_bound:.2f}); replaced with geometric "
                f"extrapolation at historical drift {daily_drift:.6f}/day"
            ),
        }
        return fallback_prices, fallback_upper, fallback_lower, meta

    # ----------------------------------------------------------------
    # PREDICT (With KPI Calculation)
    # ----------------------------------------------------------------
    def predict(self, forecast_horizon_days=90, realism_mode=True, stochastic_seed=None, n_sim_paths=250):
        if self.winner_model is None: raise RuntimeError("Train first.")
        
        # 1. Standard Date & Exogenous Prep
        last_date = pd.to_datetime(self.trained_history_df['date'].iloc[-1])
        future_dates = pd.date_range(start=last_date + pd.Timedelta(days=1), periods=forecast_horizon_days)
        str_dates = [d.strftime('%Y-%m-%d') for d in future_dates]
        
        # Save "Today's" Risk Metrics before we overwrite them with Future projections
        today_var = getattr(self, 'latest_var', -0.05)
        today_fragility = float(self.last_exogenous_row[0, -1]) if hasattr(self, 'last_exogenous_row') else 0.0

        forecast_prices = []
        upper_ci = []
        lower_ci = []
        deterministic_forecast_prices = []
        stochastic_lower = []
        stochastic_upper = []

        # Prepare Future Exogenous (AR(1)-style projection)
        future_exog = self._project_future_exog(forecast_horizon_days)

        # 2. Generate Price Forecast (The "Winner" Logic)
        if self.winner_model_name == 'qrc':
            # Quantum Reservoir Computing — forecasts raw prices directly, no exog.
            qrc_preds = self.winner_model.forecast(int(forecast_horizon_days))
            for p in qrc_preds:
                p = float(p)
                forecast_prices.append(p)
                upper_ci.append(p * 1.05)
                lower_ci.append(p * 0.95)
        elif self.winner_model_name == 'lstm':
            pred_log_returns = []
            scaler = self.winner_model.scaler
            raw = self.trained_history_df['price'].values
            log_ret_hist = np.log(raw[1:] / raw[:-1])
            last_rets_scaled = scaler.transform(log_ret_hist[-self.lstm_lookback:].reshape(-1,1))
            last_exog_hist = self.exogenous_data_for_training[-self.lstm_lookback:]
            curr_input = np.concatenate([last_rets_scaled, last_exog_hist], axis=1).reshape(1, self.lstm_lookback, -1)

            for i in range(forecast_horizon_days):
                pred_sc = self.winner_model.predict(curr_input, verbose=0)[0][0]
                pred_ret = float(scaler.inverse_transform([[pred_sc]])[0][0])
                pred_log_returns.append(pred_ret)
                new_row = np.concatenate([np.array([[pred_sc]]), future_exog[i:i+1]], axis=1)
                curr_input = np.concatenate([curr_input[:, 1:, :], new_row.reshape(1, 1, -1)], axis=1)

            curr_price = self.last_actual_price
            for r in pred_log_returns:
                next_price = curr_price * np.exp(r)
                forecast_prices.append(next_price)
                upper_ci.append(next_price * 1.05)
                lower_ci.append(next_price * 0.95)
                curr_price = next_price

        else:
            # Structural Models (ARIMA/Prophet/BSTS)
            pred_log_levels = []
            if self.winner_model_name == 'arima':
                res = self.winner_model.get_forecast(steps=forecast_horizon_days, exog=future_exog)
                if self.arima_target == 'returns':
                    pred_log_returns = res.predicted_mean
                    conf = np.asarray(res.conf_int(alpha=0.05))
                    curr_price = self.last_actual_price
                    upper_curr = self.last_actual_price
                    lower_curr = self.last_actual_price
                    for i, r in enumerate(pred_log_returns):
                        curr_price = curr_price * np.exp(float(r))
                        forecast_prices.append(curr_price)

                        lo_ret = float(conf[i, 0]) if conf.ndim == 2 else float(r)
                        hi_ret = float(conf[i, 1]) if conf.ndim == 2 else float(r)
                        lower_curr = lower_curr * np.exp(lo_ret)
                        upper_curr = upper_curr * np.exp(hi_ret)
                        lower_ci.append(lower_curr)
                        upper_ci.append(upper_curr)
                else:
                    pred_log_levels = res.predicted_mean
                    conf = np.asarray(res.conf_int(alpha=0.05))
                    upper_ci = np.exp(conf[:, 1]).tolist()
                    lower_ci = np.exp(conf[:, 0]).tolist()
            elif self.winner_model_name == 'prophet':
                fut = self.winner_model.make_future_dataframe(periods=forecast_horizon_days)
                full_ex = np.vstack([self.exogenous_data_for_training, future_exog])
                for i in range(full_ex.shape[1]): fut[f'R{i}'] = full_ex[:len(fut), i]
                fc = self.winner_model.predict(fut).tail(forecast_horizon_days)
                pred_log_levels = fc['yhat'].values
                upper_ci = np.exp(fc['yhat_upper'].values).tolist()
                lower_ci = np.exp(fc['yhat_lower'].values).tolist()
            elif self.winner_model_name == 'bsts':
                model = self.winner_model['model']
                samples = self.winner_model['samples']
                y_mean, y_std, ex_mean, ex_std = self.winner_model['stats']
                raw_prices = self.trained_history_df['price'].values
                log_prices = np.log(raw_prices)
                obs_std = (log_prices - y_mean) / (y_std + 1e-6)
                dist = tfp.sts.forecast(model=model, observed_time_series=obs_std, parameter_samples=samples, num_steps_forecast=forecast_horizon_days)
                mean_std = np.mean(dist.mean().numpy()[:, :, 0], axis=0)
                pred_log_levels = (mean_std * y_std) + y_mean
                up_std = np.percentile(dist.mean().numpy()[:, :, 0], 97.5, axis=0)
                lo_std = np.percentile(dist.mean().numpy()[:, :, 0], 2.5, axis=0)
                upper_ci = np.exp((up_std * y_std) + y_mean).tolist()
                lower_ci = np.exp((lo_std * y_std) + y_mean).tolist()

            if len(forecast_prices) == 0:
                forecast_prices = np.exp(pred_log_levels).tolist()
                if not upper_ci:
                    upper_ci = [p*1.05 for p in forecast_prices]
                    lower_ci = [p*0.95 for p in forecast_prices]

        deterministic_forecast_prices = list(forecast_prices)

        # Sanity-gate the model output before any downstream layers consume it.
        # If the gate fires, we replace forecast/upper/lower with a geometric
        # fallback and skip realism (which would just compound the bad path).
        forecast_prices, upper_ci, lower_ci, _fallback_meta = self._apply_explosion_sanity_gate(
            forecast_prices, upper_ci, lower_ci, forecast_horizon_days
        )
        if _fallback_meta is not None:
            deterministic_forecast_prices = list(forecast_prices)

        # Optional realism layer: stochastic representative path around model mean.
        effective_seed = None
        if realism_mode and len(forecast_prices) > 0 and _fallback_meta is None:
            effective_seed = self._default_stochastic_seed(forecast_horizon_days) if stochastic_seed is None else int(stochastic_seed)
            rep_prices, rep_lo, rep_hi = self._build_stochastic_representative_path(
                deterministic_prices=forecast_prices,
                n_paths=n_sim_paths,
                seed=effective_seed,
            )
            if rep_prices:
                forecast_prices = rep_prices
                stochastic_lower = rep_lo
                stochastic_upper = rep_hi

        # 3. CONSTRUCT FULL PATH (History + Forecast)
        hist_prices = self.trained_history_df['price'].tolist()
        hist_dates = pd.to_datetime(self.trained_history_df['date']).tolist()
        full_prices = hist_prices + forecast_prices
        full_dates = hist_dates + [pd.Timestamp(d) for d in str_dates]

        # --- R-RISK (HISTORY ONLY, FORWARD FORECAST) ---
        logger.info("Calling R-Risk Engine on HISTORY to get forward GARCH volatility + price cone...")
        hist_prices_arr = np.array(self.trained_history_df['price'].values, dtype=float)

        sigma_hist_aligned, _ = self._fetch_risk_metrics(hist_prices_arr, horizon=forecast_horizon_days)

        # Build full volatility vector = history sigma + forward sigma forecast
        sigma_fc = getattr(self, "sigma_fc_mean", []) or []
        sigma_fc = sigma_fc[:forecast_horizon_days]

        full_vol_vec = np.concatenate([sigma_hist_aligned, np.array(sigma_fc, dtype=float)]) \
            if len(sigma_fc) > 0 else sigma_hist_aligned
        
        h = forecast_horizon_days
        # CI priority order so bounds actually straddle the forecast line:
        #   1) Stochastic realism bounds (already centred on the representative path).
        #   2) Whatever the winner model produced (ARIMA conf_int, Prophet yhat_*, BSTS quantiles).
        #   3) R-cone width re-centred on our forecast (preserves R vol signal; anchored to our line).
        #   4) Last-resort +/-5% band.
        # Previously the R cone was unconditionally written into upper_ci/lower_ci even though it is
        # computed from historical statistics alone and is not centred on the winner forecast, which
        # is what made the UI bands look asymmetric ("only upper visible") when the forecast trended.
        mc_lower_arr = getattr(self, "mc_lower", []) or []
        mc_upper_arr = getattr(self, "mc_upper", []) or []
        mc_median_arr = getattr(self, "mc_median", []) or []
        have_r_cone = len(mc_lower_arr) >= h and len(mc_upper_arr) >= h
        if stochastic_lower and stochastic_upper and len(stochastic_lower) >= h and len(stochastic_upper) >= h:
            lower_ci = stochastic_lower[:h]
            upper_ci = stochastic_upper[:h]
        elif lower_ci and upper_ci and len(lower_ci) >= h and len(upper_ci) >= h:
            lower_ci = lower_ci[:h]
            upper_ci = upper_ci[:h]
        elif have_r_cone:
            fp = np.asarray(forecast_prices[:h], dtype=float)
            lo = np.asarray(mc_lower_arr[:h], dtype=float)
            hi = np.asarray(mc_upper_arr[:h], dtype=float)
            md = np.asarray(mc_median_arr[:h], dtype=float) if len(mc_median_arr) >= h else 0.5 * (lo + hi)
            lower_ci = (fp - np.maximum(md - lo, 0.0)).tolist()
            upper_ci = (fp + np.maximum(hi - md, 0.0)).tolist()
        else:
            upper_ci = [p * 1.05 for p in forecast_prices]
            lower_ci = [p * 0.95 for p in forecast_prices]
        # 4. Calculate Technical Indicators (KPIs)
        # We pass the R-calculated volatility to override the simple rolling std
        #kpi_df = self._calculate_indicators(full_prices, full_dates)
        kpi_df = self._calculate_indicators(full_prices, full_dates, volatility_vector=full_vol_vec)

        valuation_forecast = {
            "pe_ratio_path": [],
            "dividend_yield_path": [],
            "bond_yield_path": []
        }
        
        try:
            # 1. Get Base Fundamentals from 'self.trained_history_df' or passed args
            # We assume 'fundamentals' was stored in self during train()
            # If not, we fail gracefully.
            fund = getattr(self, 'fundamentals', {})
            
            # 2. Extract Key Ratios (Current Snapshot)
            # P/E = Price / EPS -> EPS = Price / P/E
            current_pe = fund.get('valuation', {}).get('pe_ratio', 0.0)
            
            # Dividend Yield = Div / Price -> Div = Price * Yield
            current_yield = fund.get('fund_metrics', {}).get('yield', 0.0)
            if current_yield == 0: 
                 # Check Bond Yield
                 current_yield = fund.get('bond_metrics', {}).get('yield', 0.0)

            # 3. Forecast Implied Metrics
            fc_prices_arr = np.array(forecast_prices)
            
            # A. Implied P/E (Stocks)
            if current_pe > 0:
                # Assume EPS is constant over the forecast window (safe for short horizons)
                implied_eps = self.last_actual_price / current_pe
                # P/E_t = Price_t / EPS
                valuation_forecast["pe_ratio_path"] = (fc_prices_arr / implied_eps).tolist()
            
            # B. Implied Yield (ETFs / Bonds / Div Stocks)
            if current_yield > 0:
                # Assume Payout $ is constant
                implied_payout = self.last_actual_price * current_yield
                # Yield_t = Payout / Price_t
                valuation_forecast["dividend_yield_path"] = (implied_payout / fc_prices_arr).tolist()
                
                # If it's a Bond, we also call this "bond_yield_path" for UI clarity
                if 'bond_metrics' in fund:
                    valuation_forecast["bond_yield_path"] = valuation_forecast["dividend_yield_path"]

        except Exception as e:
            logger.warning(f"Valuation forecast logic skipped: {e}")

        # OVERRIDE: Inject the GARCH volatility from R into the KPI dataframe
        # Ensure lengths match (R might return slight diff, so we clip/pad)
        #if len(full_vol_vec) == len(kpi_df):
        #    kpi_df['volatility'] = full_vol_vec
        #else:
            # Fallback alignment if R drops early data points
        #    logger.warning(f"Vol len mismatch (DF: {len(kpi_df)}, R: {len(full_vol_vec)}). Using partial R data.")
        #    kpi_df['volatility'] = pd.Series(full_vol_vec).reindex(kpi_df.index, method='ffill')

        # 5. Split Data for Response
        split_idx = len(hist_prices)
        hist_kpis = kpi_df.iloc[:split_idx]
        fc_kpis = kpi_df.iloc[split_idx:]
        
        def get_series(df, col): return df[col].tolist()

        indicators = {
            "rsi": {
                "history": get_series(hist_kpis, 'rsi'),
                "forecast": get_series(fc_kpis, 'rsi'),
                "forecast_upper": [x * 1.05 for x in get_series(fc_kpis, 'rsi')], 
                "forecast_lower": [x * 0.95 for x in get_series(fc_kpis, 'rsi')]
            },
            "macd": {
                "macd_line": get_series(hist_kpis, 'macd') + get_series(fc_kpis, 'macd'),
                "signal_line": get_series(hist_kpis, 'signal') + get_series(fc_kpis, 'signal'),
                "history_macd": get_series(hist_kpis, 'macd'),
                "forecast_macd": get_series(fc_kpis, 'macd'),
                "history_signal": get_series(hist_kpis, 'signal'),
                "forecast_signal": get_series(fc_kpis, 'signal')
            },
            "bbands": {
                "upper": get_series(hist_kpis, 'upper_band') + get_series(fc_kpis, 'upper_band'),
                "middle": get_series(hist_kpis, 'ma20') + get_series(fc_kpis, 'ma20'),
                "lower": get_series(hist_kpis, 'lower_band') + get_series(fc_kpis, 'lower_band'),
                "forecast_upper": get_series(fc_kpis, 'upper_band'),
                "forecast_lower": get_series(fc_kpis, 'lower_band'),
                "forecast_middle": get_series(fc_kpis, 'ma20')
            },
            "atr": {
                "history": get_series(hist_kpis, 'atr'),
                "forecast": get_series(fc_kpis, 'atr')
            },
            "volatility": {
                "history": get_series(hist_kpis, 'volatility'), # Now GARCH
                "forecast": get_series(fc_kpis, 'volatility')   # Now GARCH
            },
            "returns": {
                "history": get_series(hist_kpis, 'returns'),
                "forecast": get_series(fc_kpis, 'returns')
            }
        }

        # 6. Construct Response
        perf = self._calculate_performance_metrics(full_prices)

        response = {
            "forecast_prices": forecast_prices,
            "forecast_returns": get_series(fc_kpis, 'returns'),
            "upper_ci": upper_ci,
            "lower_ci": lower_ci,
            "forecast_dates": str_dates,
            "model_used": self.winner_model_name,
            "volatility_history": full_vol_vec.tolist(),  # history + forward mean
            "indicators": indicators
        }

        if deterministic_forecast_prices:
            response["forecast_prices_mean"] = deterministic_forecast_prices
        response["realism_mode"] = bool(realism_mode)
        if _fallback_meta is not None:
            response["model_used"] = _fallback_meta["model_used"]
            response["forecast_quality"] = _fallback_meta["forecast_quality"]
            response["forecast_quality_reason"] = _fallback_meta["forecast_quality_reason"]
        if effective_seed is not None:
            response["stochastic_seed"] = int(effective_seed)
        if self.validation_scores:
            response["model_validation"] = self.validation_scores

        # --- ADD VOLATILITY CONE (separately, cleanly) ---
        response["volatility_cone"] = {
            "lower_bound": getattr(self, "sigma_mc_lower", [])[:forecast_horizon_days],
            "median_bound": getattr(self, "sigma_mc_median", [])[:forecast_horizon_days],
            "upper_bound": getattr(self, "sigma_mc_upper", [])[:forecast_horizon_days],
        }

        
        # 7. Risk Metrics (Use stored "Today" values for consistency)
        response["risk_metrics"] = {
            "var_95": today_var,
            "regime": getattr(self, 'latest_regime', "Normal"),
            "fragility_score": today_fragility,
            "stop_loss_price": float(self.last_actual_price) * (1 + today_var),
            "cvar_95": perf.get("cvar_95", 0.0),
            "cvar_99": perf.get("cvar_99", 0.0),
            "max_drawdown": perf.get("max_drawdown", 0.0),
        }

        # Build a representative vol forecast path: the GARCH analytical mean is
        # flat after ~15 steps (mean-reversion to unconditional variance). For the
        # UI we simulate a single plausible GARCH vol path that has realistic
        # day-to-day variation while staying within the MC cone.
        sigma_fc_arr = np.asarray(getattr(self, "sigma_fc_mean", []) or [], dtype=float)[:forecast_horizon_days]
        mc_lo = np.asarray(getattr(self, "sigma_mc_lower", []) or [], dtype=float)[:forecast_horizon_days]
        mc_hi = np.asarray(getattr(self, "sigma_mc_upper", []) or [], dtype=float)[:forecast_horizon_days]
        if len(sigma_fc_arr) > 0 and len(self.volatility_cache) > 5:
            # Estimate vol-of-vol from historical conditional volatility changes
            hist_vol = np.asarray(self.volatility_cache, dtype=float)
            vol_changes = np.diff(hist_vol[hist_vol > 0])
            vol_changes = vol_changes[np.isfinite(vol_changes)]
            if len(vol_changes) > 10:
                vol_of_vol = float(np.std(vol_changes))
                seed = self._default_stochastic_seed(forecast_horizon_days)
                rng = np.random.default_rng(int(seed) ^ 0xBEEF)
                # Random walk around the GARCH mean with vol-of-vol noise
                rep_vol = np.zeros_like(sigma_fc_arr)
                rep_vol[0] = float(sigma_fc_arr[0])
                for t in range(1, len(rep_vol)):
                    shock = rng.normal(0, vol_of_vol * 0.6)
                    rep_vol[t] = rep_vol[t - 1] + shock
                    # Mean-revert gently toward the GARCH forecast
                    rep_vol[t] += 0.15 * (sigma_fc_arr[t] - rep_vol[t])
                # Clamp within the MC cone (if available) so the path is plausible
                if len(mc_lo) == len(rep_vol) and len(mc_hi) == len(rep_vol):
                    rep_vol = np.clip(rep_vol, mc_lo, mc_hi)
                rep_vol = np.maximum(rep_vol, 0.01)  # vol can't go negative
                sigma_fc_representative = rep_vol.tolist()
            else:
                sigma_fc_representative = sigma_fc_arr.tolist()
        else:
            sigma_fc_representative = sigma_fc_arr.tolist() if len(sigma_fc_arr) else []

        response["volatility"] = {
            "history": indicators["volatility"]["history"],
            "forecast": sigma_fc_representative,  # representative path (realistic, non-flat)
            "forecast_mean": sigma_fc_arr.tolist() if len(sigma_fc_arr) else [],  # analytical GARCH mean (flat, for reference)
            "forecast_lower": mc_lo.tolist() if len(mc_lo) else [],
            "forecast_median": (getattr(self, "sigma_mc_median", []) or [])[:forecast_horizon_days],
            "forecast_upper": mc_hi.tolist() if len(mc_hi) else [],
        }

        # --- Drawdown and monthly returns with forecast CI ---
        hist_prices_list = self.trained_history_df['price'].tolist()
        hist_dates_list = [str(pd.to_datetime(d).date()) for d in self.trained_history_df['date']]
        try:
            response["drawdown_series"] = build_drawdown_series(
                historical_prices=hist_prices_list,
                forecast_prices=forecast_prices,
                lower_ci=lower_ci,
                upper_ci=upper_ci,
                historical_dates=hist_dates_list,
                forecast_dates=str_dates,
            )
        except Exception as e:
            logger.warning(f"drawdown_series build failed: {e}")
        try:
            response["monthly_returns"] = build_monthly_returns(
                historical_dates=hist_dates_list,
                historical_prices=hist_prices_list,
                forecast_dates=str_dates,
                forecast_prices=forecast_prices,
                lower_ci=lower_ci,
                upper_ci=upper_ci,
            )
        except Exception as e:
            logger.warning(f"monthly_returns build failed: {e}")

        
        # Monte Carlo
        horizon = min(forecast_horizon_days, len(getattr(self, 'mc_lower', [])))
        if horizon > 0:
            response["monte_carlo_cone"] = {
                "lower_bound": self.mc_lower[:horizon], 
                "median_bound": self.mc_median[:horizon], 
                "upper_bound": self.mc_upper[:horizon]
            }

        # Explanation
        try:
            narrative = "Analysis pending"
            contribs = {}
            narrative = "Driven by recent trend and structural components."
            response["explanation"] = {"sentiment_impact": 0.0, "volatility_impact": 0.0, "narrative": narrative, "detailed_contributions": contribs}
        except: pass

        response["performance_metrics"] = perf
        response["fundamentals"] = {}

        # Forecast quality metrics for the winner model (from walk-forward validation)
        winner_quality = (self.validation_scores.get("quality_per_model") or {}).get(self.winner_model_name)
        if winner_quality:
            response["forecast_quality"] = {
                "mape": winner_quality.get("mape"),
                "directional_accuracy": winner_quality.get("directional_accuracy"),
                "long_short_sharpe": winner_quality.get("long_short_sharpe"),
                "n_validation_steps": winner_quality.get("n_validation_steps", 0),
                "model": self.winner_model_name,
                "source": "walk_forward_validation",
            }

        # VQMC single-asset scenario fans (quantum circuit-sampled shocks)
        try:
            hist_prices_for_vqmc = self.trained_history_df['price'].tolist()
            vqmc_result = generate_vqmc_scenario_fans(
                historical_prices=hist_prices_for_vqmc,
                ticker=self.ticker or "",
                horizon_days=forecast_horizon_days,
                n_simulations=500,
                random_seed=effective_seed,
            )
            response["scenarios"] = vqmc_result["scenarios"]
            response["scenarios_legacy"] = vqmc_result["scenarios_legacy"]
            response["scenario_method"] = vqmc_result["method"]
        except Exception as e:
            logger.warning(f"VQMC scenario generation failed: {e}")

        # Regime-conditional selection metadata
        response["regime_selection"] = {
            "current_regime": getattr(self, "current_regime", "Normal"),
            "selection_mode": getattr(self, "selection_mode", "global"),
            "selected_model": self.winner_model_name,
            "global_winner": getattr(self, "global_winner", self.winner_model_name),
            "regime_scores": self.validation_scores.get("regime_scores", {}),
        }

        return self._sanitize_for_json(response)

    def _get_feature_names(self):
        names = [f"Quantum_{i}" for i in range(4)]
        names += [f"Sentiment_{i}" for i in range(8)]
        names += ["Market_Volatility", "Fragility_Score"]
        return names
    
    def _model_wrapper_for_shap(self, feature_matrix):
        if self.winner_model_name == 'lstm':
            last_prices = self.trained_history_df['price'].values[-self.lstm_lookback:].reshape(self.lstm_lookback, 1)
            last_feats = self.exogenous_data_for_training[-self.lstm_lookback:]
            preds = []
            for row in feature_matrix:
                win = last_feats.copy(); win[-1] = row
                inp = np.concatenate([last_prices, win], axis=1).reshape(1, self.lstm_lookback, -1)
                preds.append(self.winner_model.predict(inp, verbose=0).flatten()[0])
            return np.array(preds)
        elif self.winner_model_name == 'prophet':
            preds = []
            for row in feature_matrix:
                fut = self.winner_model.make_future_dataframe(periods=1)
                for i, val in enumerate(row): fut[f'R{i}'] = val
                preds.append(self.winner_model.predict(fut.tail(1))['yhat'].values[0])
            return np.array(preds)
        elif self.winner_model_name == 'arima':
            preds = []
            for row in feature_matrix:
                exog_row = row.reshape(1, -1)
                fc = self.winner_model.get_forecast(steps=1, exog=exog_row)
                preds.append(fc.predicted_mean[0])
            return np.array(preds)
        elif self.winner_model_name == 'bsts':
            preds = []
            for row in feature_matrix: preds.append(0.0) 
            return np.array(preds)
        return np.zeros(len(feature_matrix))
