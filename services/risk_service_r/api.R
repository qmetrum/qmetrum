# services/risk_service_r/app/api.R

library("plumber")
library("rugarch")
library("zoo")
library("jsonlite")

# --- 1. GLOBAL MODEL SPECIFICATION ---
# We define the model ONCE.
# Your code: sGARCH(1,1) with "std" (Student-t) distribution.
spec <- ugarchspec(
  variance.model = list(model = "sGARCH", garchOrder = c(1, 1)),
  mean.model = list(armaOrder = c(0, 0), include.mean = TRUE),
  distribution.model = "std" # Crucial for "Fat Tails" (Crashes)
)

# --- 2. THE API ENDPOINT ---

#* Health check
#* @get /health
function() {
  list(
    status = "ok",
    service = "risk_service_r",
    timestamp = as.character(Sys.time())
  )
}

#* Calculate Risk Metrics & Monte Carlo Cones (Price + Volatility)
#* @param prices A list/array of historical close prices
#* @param horizon Number of days to simulate (default 30)
#* @param n_paths Number of Monte Carlo paths (default 1000)
#* @post /calculate_risk
function(prices, horizon = 30, n_paths = 1000) {

  prices <- as.numeric(unlist(prices))
  returns <- diff(log(prices))

  if (length(returns) < 100) {
    return(list(error = "Insufficient data. Need at least 100 points."))
  }

  fit <- tryCatch({
    ugarchfit(spec = spec, data = returns, solver = "hybrid")
  }, error = function(e) NULL)

  if (is.null(fit)) {
    return(list(error = "GARCH Model failed to fit."))
  }

  # --- HISTORICAL VOL ---
  sigma_hist <- as.numeric(sigma(fit))

  rolling_median_vol <- rollmedian(sigma_hist, k = 126, fill = NA, align = "right")
  long_term_vol <- tail(na.omit(rolling_median_vol), 1)
  if (length(long_term_vol) == 0) long_term_vol <- mean(sigma_hist)

  current_vol <- tail(sigma_hist, 1)
  fragility_score_latest <- as.numeric(current_vol / long_term_vol)
  regime <- ifelse(fragility_score_latest > 1.5, "High_Fragility",
                   ifelse(fragility_score_latest < 0.8, "Low_Vol_Stable", "Normal"))

  # --- 1-STEP VAR (as you already do) ---
  fc1 <- ugarchforecast(fit, n.ahead = 1)
  next_mu <- fitted(fc1)[1]
  next_sigma <- sigma(fc1)[1]
  shape_param <- coef(fit)["shape"]
  z_score_95 <- qdist(distribution = "std", p = 0.05, shape = shape_param)
  var_95_latest <- as.numeric(next_mu + (next_sigma * z_score_95))

  # --- FORWARD VOL FORECAST (MEAN) ---
  fch <- ugarchforecast(fit, n.ahead = horizon)
  sigma_fc_mean <- as.numeric(sigma(fch))  # length = horizon

  # --- MONTE CARLO SIM (FOR PRICE CONE + VOL CONE) ---
  sim <- ugarchsim(fit, n.sim = horizon, m.sim = n_paths, startMethod = "sample")

  # Simulated returns: Horizon x n_paths
  sim_returns <- fitted(sim)

  last_price <- tail(prices, 1)

  # Convert simulated returns to simulated prices: Horizon x n_paths
  sim_prices <- apply(sim_returns, 2, function(x) last_price * exp(cumsum(x)))

  # Price fan chart (5/50/95)
  mc_lower  <- as.numeric(apply(sim_prices, 1, quantile, probs = 0.05))
  mc_median <- as.numeric(apply(sim_prices, 1, quantile, probs = 0.50))
  mc_upper  <- as.numeric(apply(sim_prices, 1, quantile, probs = 0.95))

  # --- VOLATILITY CONE ---
  # rugarch stores simulated sigma in the simulation object; sigma(sim) returns Horizon x n_paths
  sim_sigma <- sigma(sim)

  sigma_mc_lower  <- as.numeric(apply(sim_sigma, 1, quantile, probs = 0.05))
  sigma_mc_median <- as.numeric(apply(sim_sigma, 1, quantile, probs = 0.50))
  sigma_mc_upper  <- as.numeric(apply(sim_sigma, 1, quantile, probs = 0.95))

  return(list(
    # History features
    sigma_hist = sigma_hist,
    fragility_hist = as.numeric(sigma_hist / long_term_vol),

    # Snapshot
    var_95_latest = var_95_latest,
    regime_latest = regime,
    fragility_score_latest = fragility_score_latest,

    # Forward VOL
    sigma_fc_mean = sigma_fc_mean,
    sigma_mc_lower = sigma_mc_lower,
    sigma_mc_median = sigma_mc_median,
    sigma_mc_upper = sigma_mc_upper,

    # Forward PRICE cone
    mc_dates_idx = 1:horizon,
    mc_lower = mc_lower,
    mc_median = mc_median,
    mc_upper = mc_upper
  ))
}
