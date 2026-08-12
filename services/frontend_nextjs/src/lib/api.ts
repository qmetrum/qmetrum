import axios from "axios";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "http://127.0.0.1:8000";

export const DEFAULT_USER_ID =
  process.env.NEXT_PUBLIC_USER_ID?.trim() || "1";

const DEFAULT_TIMEOUT_MS = 60_000;
const HEAVY_TIMEOUT_MS = 180_000;

// Module-level holder for the current Cognito ID token. The AuthSync
// component (mounted high in the tree) keeps this updated whenever
// react-oidc-context's user changes; the axios interceptor below reads it
// on every request so we never send a stale token.
let _cachedIdToken: string | null = null;

export function setAuthToken(token: string | null): void {
  _cachedIdToken = token;
}

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "X-User-Id": DEFAULT_USER_ID,
  },
  timeout: DEFAULT_TIMEOUT_MS,
});

// Inject the Bearer token (when authenticated) on every outgoing request.
// We keep the X-User-Id default for unauthenticated dev use; the backend
// middleware overwrites it with the real user id when a Bearer is present.
api.interceptors.request.use((config) => {
  if (_cachedIdToken) {
    config.headers = config.headers ?? {};
    (config.headers as Record<string, string>)["Authorization"] =
      `Bearer ${_cachedIdToken}`;
  }
  return config;
});

export type PricePoint = { date: string; price: number };

export type AssetProfileResponse = {
  ticker: string;
  type?: string;
  profile?: {
    name?: string;
    sector?: string;
    industry?: string;
    description?: string;
    currency?: string;
    exchange?: string;
  };
  valuation?: {
    market_cap?: number;
    pe_ratio?: number;
    ev_to_ebitda?: number;
    forward_pe?: number;
  };
  profitability?: {
    profit_margin?: number;
    roe?: number;
    roa?: number;
  };
  analysts?: {
    target_mean?: number;
    recommendation?: string;
    num_analysts?: number;
  };
  technicals?: {
    beta?: number;
    "52_week_high"?: number;
    "52_week_low"?: number;
    fiftyTwoWeekHigh?: number;
    fiftyTwoWeekLow?: number;
  };
  fund_metrics?: Record<string, unknown>;
  bond_metrics?: Record<string, unknown>;
};

export type AssetPriceResponse = {
  ticker: string;
  period: string;
  series: PricePoint[];
};

export type ScenarioFan = {
  central: number[];
  lower_1s?: number[];
  upper_1s?: number[];
  lower_2s?: number[];
  upper_2s?: number[];
};

export type DrawdownSeries = {
  historical?: { dates?: string[] | null; values?: number[] };
  forecast?: {
    dates?: string[] | null;
    values?: number[];
    lower?: number[];
    upper?: number[];
  };
};

export type MonthlyReturnRow = {
  month: string;
  return: number;
  partial?: boolean;
  n_days?: number;
  lower?: number;
  upper?: number;
  spliced_with_history?: boolean;
};

export type MonthlyReturns = {
  historical?: MonthlyReturnRow[];
  forecast?: MonthlyReturnRow[];
};

export type AssetForecastResponse = {
  ticker?: string;
  forecast_prices?: number[];
  forecast_dates?: string[];
  lower_ci?: number[];
  upper_ci?: number[];
  history_prices?: number[];
  history_dates?: string[];
  fundamentals?: AssetProfileResponse;
  risk_metrics?: Record<string, number | string | null>;
  scenarios?: Record<string, number[]>;
  metadata?: {
    model_version?: string;
    training_window?: { start?: string | null; end?: string | null };
    last_train_date?: string;
  };
  cache?: { hit?: boolean; [key: string]: unknown };
  monte_carlo_cone?: {
    lower_bound?: number[];
    median_path?: number[];
    upper_bound?: number[];
  };
  performance_metrics?: Record<string, number | string | null>;
  drawdown_series?: DrawdownSeries;
  monthly_returns?: MonthlyReturns;
  [key: string]: unknown;
};

export type ForecastScenarioInput = {
  name: string;
  initial_shock_pct?: number;
  return_scale?: number;
  drift_shift?: number;
};

export type AssetRiskResponse = {
  ticker?: string;
  var_95_latest?: number;
  regime_latest?: string;
  fragility_score_latest?: number;
  fragility_score?: number;
  sigma_hist?: number[];
  sigma_fc_mean?: number[];
  sigma_mc_lower?: number[];
  sigma_mc_median?: number[];
  sigma_mc_upper?: number[];
  mc_dates_idx?: Array<number | string>;
  mc_lower?: number[];
  mc_median?: number[];
  mc_upper?: number[];
  cache?: {
    hit?: boolean;
    cache_type?: string;
    fresh?: boolean;
    stale?: boolean;
    cache_id?: number;
    updated_at?: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
};

export type AssetNewsResponse = {
  ticker?: string;
  items?: Array<{
    title: string;
    publisher?: string;
    link?: string;
    timestamp?: string;
    type?: string;
  }>;
  cache?: {
    hit?: boolean;
    cache_type?: string;
    fresh?: boolean;
    stale?: boolean;
    cache_id?: number;
    updated_at?: string;
    [key: string]: unknown;
  };
  warnings?: string[];
};

export type AssetSearchResult = {
  symbol: string;
  name?: string;
  asset_type?: string;
  exchange?: string | null;
  currency?: string | null;
  vendor?: string;
  vendor_symbol?: string | null;
};

export type AssetSearchResponse = {
  query: string;
  count: number;
  items: AssetSearchResult[];
};

export type PortfolioHolding = {
  ticker: string;
  weight?: number;
  quantity?: number;
  cost_basis?: number;
  asset_type?: string;
  purchase_date?: string | null;
  // Derived $ metrics — present only when cost_basis > 0, quantity > 0, and MarketData exists.
  current_price?: number;
  current_value?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  daily_pnl?: number;
};

export type PortfolioUpsertPayload = {
  name?: string;
  assets: PortfolioHolding[];
};

export type PortfolioTotals = {
  cost_basis: number;
  current_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  daily_pnl: number;
};

export type PortfolioResponse = {
  portfolio_id: number;
  user_id?: number;
  name: string;
  assets: PortfolioHolding[];
  created_at?: string;
  updated_at?: string;
  // Opt-in $ tracking: true when at least one position has cost_basis > 0.
  has_cost_basis_data?: boolean;
  // Portfolio-level rollups — present only when ≥1 position has derived $ metrics.
  totals?: PortfolioTotals;
};

export type PortfolioForecastResponse = {
  portfolio_id?: number;
  error?: string | null;
  cache?: {
    hit?: boolean;
    cache_type?: string;
    cache_id?: number;
    created_at?: string | null;
    updated_at?: string | null;
    [key: string]: unknown;
  };
  portfolio_summary?: {
    forecast_prices?: number[];
    forecast_dates?: string[];
    lower_ci?: number[];
    upper_ci?: number[];
    risk_metrics?: Record<string, number | string | null>;
    monte_carlo_cone?: {
      lower_bound?: number[];
      median_path?: number[];
      upper_bound?: number[];
    };
    drawdown_series?: DrawdownSeries;
    monthly_returns?: MonthlyReturns;
    indicators?: Record<string, unknown>;
    performance_metrics?: Record<string, number | string | null>;
    forecast_horizon_days?: number;
    regime?: Record<string, unknown>;
    sector_exposure?: Record<string, number>;
    /** New fan shape: each scenario is {central, lower_1s, upper_1s, lower_2s, upper_2s}.
     *  Audit key `_mps` contains MPS bond-dim info. Legacy flat arrays live in scenarios_legacy. */
    scenarios?: Record<string, ScenarioFan | unknown>;
    scenarios_legacy?: Record<string, number[]>;
  };
  stress_tests?: Array<Record<string, unknown>>;
  rebalancing?: {
    target?: string;
    estimated_turnover?: number;
    suggestions?: Array<Record<string, unknown>>;
  };
  holdings?: Array<Record<string, unknown>>;
};

export type ForecastJobRecord = {
  job_id: string;
  job_type: string;
  entity_type: string;
  entity_id: string;
  status: "queued" | "running" | "completed" | "failed" | string;
  progress: number;
  error_message?: string | null;
  result_cache_id?: number | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
};

export type PortfolioForecastSubmitResponse = {
  mode: "cache" | "job" | "live" | string;
  async_mode?: boolean;
  cache_hit?: boolean;
  job_id?: string | null;
  job?: ForecastJobRecord | null;
  result?: PortfolioForecastResponse | null;
};

export type ForecastJobStatusResponse = {
  job: ForecastJobRecord;
  result?: PortfolioForecastResponse;
  error?: string;
};

export type PortfolioQuantumRiskResponse = {
  portfolio_id?: number;
  method?: string;
  risk_metrics?: Record<string, number | string>;
  simulation_metadata?: Record<string, number | string | null>;
  paths_preview?: number[][];
  final_distribution?: {
    bins?: number[];
    counts?: number[];
  };
  cache?: {
    hit?: boolean;
    cache_type?: string;
    input_hash?: string;
    method?: string;
    cache_id?: number;
    created_at?: string;
  };
  history_summary?: Record<string, unknown>;
};

type CoverageTest = {
  test?: string;
  statistic: number;
  p_value: number;
  df: number;
  reject: boolean;
};

export type VarBacktestResponse = {
  portfolio_id?: number;
  method: string;
  confidence: number;
  alpha: number;
  horizon_days: number;
  overlapping_windows: boolean;
  weight_mode?: "constant" | "drift";
  weight_mode_requested?: string;
  weight_mode_note?: string;
  n_observations: number;
  exceptions: number;
  expected_exceptions: number;
  breach_rate: number;
  expected_breach_rate: number;
  kupiec: CoverageTest & { observed_rate?: number; expected_rate?: number };
  christoffersen: {
    independence: CoverageTest;
    conditional_coverage: CoverageTest;
    transitions: { n00: number; n01: number; n10: number; n11: number };
  };
  basel_traffic_light: { zone: "green" | "yellow" | "red"; cumulative_probability: number };
  observed_expected_shortfall: number | null;
  model_passes: boolean;
  skipped_days?: number;
  series: {
    date: string[] | null;
    realized_return: number[];
    var_threshold: number[];
    breach: boolean[];
  };
  params?: Record<string, unknown>;
  data_window?: { start: string; end: string; n_return_obs: number };
  cache?: { hit?: boolean; cache_type?: string; method?: string };
};

export type VarBacktestMethodResult = {
  key: string;
  label: string;
  method: string;
  physical_dim: number | null;
  status: "ok" | "skipped";
  reason?: string;
  n_observations?: number;
  exceptions?: number;
  expected_exceptions?: number;
  breach_rate?: number;
  expected_breach_rate?: number;
  kupiec?: { p_value: number; reject: boolean };
  christoffersen_cc?: { p_value: number; reject: boolean };
  independence?: { p_value: number; reject: boolean };
  basel_zone?: "green" | "yellow" | "red";
  observed_expected_shortfall?: number | null;
  model_passes?: boolean;
  var_threshold?: number[];
};

export type VarBacktestCompareResponse = {
  portfolio_id?: number;
  confidence: number;
  alpha: number;
  horizon_days: number;
  overlapping_windows: boolean;
  weight_mode?: "constant" | "drift";
  weight_mode_requested?: string;
  weight_mode_note?: string;
  n_observations: number;
  shared: { dates: string[]; realized_return: number[] };
  methods: VarBacktestMethodResult[];
  recommended: { key: string; label: string; why: string } | null;
  params?: Record<string, unknown>;
  data_window?: { start: string; end: string; n_return_obs: number };
  cache?: { hit?: boolean };
};

export type WatchlistResponse = {
  watchlist_id: number;
  user_id?: number;
  name: string;
  tickers: string[];
  created_at?: string;
  updated_at?: string;
};

export type WatchlistSnapshotResponse = {
  watchlist_id: number;
  items: Array<{
    ticker: string;
    latest_price?: number | null;
    change_1d?: number | null;
    vol_30d?: number | null;
    market_cap?: number | null;
    pe_ratio?: number | null;
    sparkline?: number[];
  }>;
};

export type AlertRuleResponse = {
  id: number;
  user_id?: number;
  name: string;
  ticker: string;
  watchlist_id?: number | null;
  alert_type: string;
  direction: string;
  threshold_value: number;
  lookback_days: number;
  is_active: boolean;
  extra_config?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
};

export type AlertEventResponse = {
  id: number;
  alert_id?: number | null;
  ticker: string;
  alert_type: string;
  triggered: boolean;
  payload?: Record<string, unknown>;
  evaluated_at: string;
};

/** Payload shape written by POST /qpulse/ingest. */
export type QpulseEventPayload = {
  detector_source: "qpulse";
  /** Name of the labeled catalog this (kind, asset_class) was scored against,
   *  or null when the combination has never been gated. Never render a recall
   *  or false-positive figure next to a live alert: those were measured on
   *  historical daily bars, not on the live stream producing this event. */
  reference_gate: string | null;
  gated_on_reference_catalog: boolean;
  qpulse: {
    kind: string;
    score: number;
    severity?: string | null;
    narrative?: string | null;
    details?: Record<string, unknown>;
    ts_ns: number;
    price: number;
    symbol_raw: string;
    feed?: string | null;
    asset_class?: string | null;
  };
};

export type AlertEvaluationSummary = {
  evaluated_count: number;
  triggered_count: number;
  items: Array<Record<string, unknown>>;
};

export type ScreenerRow = {
  ticker: string;
  type?: string;
  name?: string;
  sector?: string;
  market_cap?: number | null;
  pe_ratio?: number | null;
  ev_to_ebitda?: number | null;
  profit_margin?: number | null;
  beta?: number | null;
  [key: string]: unknown;
};

export type ScreenerRunResponse = {
  count: number;
  items: ScreenerRow[];
  filters: Record<string, unknown>;
};

export type SavedScreenResponse = {
  id: number;
  user_id?: number;
  name: string;
  description?: string | null;
  filters: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
};

export const assetApi = {
  search: async (q: string, limit = 8) =>
    (await api.get<AssetSearchResponse>("/assets/search", { params: { q, limit } })).data,

  profile: async (symbol: string) =>
    (await api.get<AssetProfileResponse>(`/assets/${symbol}/profile`)).data,

  price: async (symbol: string, period = "2y") =>
    (await api.get<AssetPriceResponse>(`/assets/${symbol}/price`, { params: { period } })).data,

  forecast: async (symbol: string, horizon_days = 90, scenarios?: ForecastScenarioInput[]) =>
    (
      await api.post<AssetForecastResponse>(`/assets/${symbol}/forecast`, {
        horizon_days,
        ...(scenarios ? { scenarios } : {}),
      }, { timeout: HEAVY_TIMEOUT_MS })
    ).data,

  risk: async (symbol: string, horizon_days = 90, n_paths = 1000, refresh = false) =>
    (
      await api.get<AssetRiskResponse>(`/assets/${symbol}/risk`, {
        params: { horizon_days, n_paths, ...(refresh ? { refresh: true } : {}) },
      })
    ).data,

  news: async (symbol: string, limit = 10, refresh = false) =>
    (
      await api.get<AssetNewsResponse>(`/assets/${symbol}/news`, {
        params: { limit, ...(refresh ? { refresh: true } : {}) },
      })
    ).data,
};

export type ImportHolding = {
  ticker: string;
  quantity: number;
  cost_basis: number;
  purchase_date: string | null;
  asset_type: string;
  weight: number;
};

export type ScenarioSessionSummary = {
  id: number;
  name: string;
  portfolio_id: string | null;
  portfolio_value: number | null;
  n_scenarios: number;
  has_results: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type ScenarioSessionFull = ScenarioSessionSummary & {
  scenarios: Record<string, unknown>;
  results: Record<string, unknown>;
};

export const scenarioSessionApi = {
  list: async () =>
    (await api.get<{ items: ScenarioSessionSummary[] }>("/scenario-sessions")).data.items,
  get: async (id: number) =>
    (await api.get<ScenarioSessionFull>(`/scenario-sessions/${id}`)).data,
  save: async (payload: {
    name: string;
    portfolio_id?: string | null;
    portfolio_value?: number | null;
    scenarios: Record<string, unknown>;
    results: Record<string, unknown>;
  }) => (await api.post<ScenarioSessionSummary>("/scenario-sessions", payload)).data,
  remove: async (id: number) =>
    (await api.delete<{ deleted: boolean; id: number }>(`/scenario-sessions/${id}`)).data,
};

export const portfolioApi = {
  get: async (id: string | number) =>
    (await api.get<PortfolioResponse>(`/portfolios/${id}`)).data,

  create: async (payload: PortfolioUpsertPayload) =>
    (await api.post<PortfolioResponse>("/portfolios", payload)).data,

  importParse: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return (await api.post<{
      holdings: ImportHolding[];
      report: {
        imported: number;
        skipped: { row: number; reason: string }[];
        warnings: string[];
        weight_basis: string;
        columns_detected: Record<string, string>;
      };
    }>("/portfolios/import/parse", form, { timeout: HEAVY_TIMEOUT_MS })).data;
  },

  importCommit: async (name: string, holdings: ImportHolding[]) =>
    (await api.post<PortfolioResponse & {
      import_report: { imported: number; weight_basis: string };
    }>("/portfolios/import/commit", { name, holdings })).data,

  update: async (id: string | number, payload: PortfolioUpsertPayload) =>
    (await api.put<PortfolioResponse>(`/portfolios/${id}`, payload)).data,

  delete: async (id: string | number) =>
    (await api.delete<{ deleted: boolean; portfolio_id: number }>(`/portfolios/${id}`)).data,

  forecastDirect: async (payload: {
    assets: PortfolioHolding[];
    horizon_days?: number;
    scenarios?: ForecastScenarioInput[];
    target_weights?: Record<string, number>;
  }) => (await api.post<PortfolioForecastResponse>("/forecast_portfolio", payload, { timeout: HEAVY_TIMEOUT_MS })).data,

  forecast: async (
    id: string | number,
    payload: {
      horizon_days?: number;
      scenarios?: ForecastScenarioInput[];
      target_weights?: Record<string, number>;
      include_builtin_scenarios?: boolean;
    } = {},
    options?: {
      async_mode?: boolean;
      force_refresh?: boolean;
    },
  ) =>
    (
      await api.post<PortfolioForecastSubmitResponse>(`/portfolios/${id}/forecast`, payload, {
        params: {
          ...(options?.async_mode != null ? { async_mode: options.async_mode } : {}),
          ...(options?.force_refresh != null ? { force_refresh: options.force_refresh } : {}),
        },
        timeout: HEAVY_TIMEOUT_MS,
      })
    ).data,

  quantumRisk: async (
    id: string | number,
    payload: { horizon_days?: number; n_simulations?: number; random_seed?: number } = {},
  ) =>
    (await api.post<PortfolioQuantumRiskResponse>(`/portfolios/${id}/simulate_quantum_risk`, payload, { timeout: HEAVY_TIMEOUT_MS })).data,

  varBacktest: async (
    id: string | number,
    payload: {
      method?: "mps_fan" | "historical" | "parametric";
      confidence?: number;
      horizon_days?: number;
      est_window?: number;
      n_backtest?: number;
      n_simulations?: number;
      random_seed?: number;
      weight_mode?: "constant" | "drift";
    } = {},
  ) =>
    (await api.post<VarBacktestResponse>(`/portfolios/${id}/var_backtest`, payload, { timeout: HEAVY_TIMEOUT_MS })).data,

  varBacktestCompare: async (
    id: string | number,
    payload: {
      confidence?: number;
      horizon_days?: number;
      est_window?: number;
      n_backtest?: number;
      n_simulations?: number;
      random_seed?: number;
      weight_mode?: "constant" | "drift";
    } = {},
  ) =>
    (await api.post<VarBacktestCompareResponse>(`/portfolios/${id}/var_backtest_compare`, payload, { timeout: HEAVY_TIMEOUT_MS })).data,

  drawdownAllocation: async (
    id: string | number,
    payload: {
      period?: string;
      window?: number;
      rebalance?: number;
      cost_bps?: number;
      alpha?: number;
    } = {},
  ) =>
    (await api.post<DrawdownAllocationResponse>(`/portfolios/${id}/drawdown_allocation`, payload, { timeout: HEAVY_TIMEOUT_MS })).data,
};

export type AllocationMethodProfile = {
  cagr: number;
  ann_vol: number;
  sharpe: number;
  max_drawdown: number;
  cdar95: number;
  turnover_per_yr: number;
};

export type AllocationMethod = {
  key: string;
  label: string;
  note: string;
  weights: Record<string, number>;
  profile?: AllocationMethodProfile | null;
};

export type DrawdownAllocationResponse = {
  portfolio_id?: number;
  as_of: string;
  tickers: string[];
  n_assets: number;
  params: { window: number; rebalance: number; cost_bps: number; alpha: number };
  data_window: { start: string; end: string; n_obs: number; years: number };
  current_weights?: Record<string, number> | null;
  methods: AllocationMethod[];
  note: string;
};

export const forecastJobApi = {
  get: async (jobId: string) =>
    (await api.get<ForecastJobStatusResponse>(`/jobs/${jobId}`)).data,
};

export const savedAssetsApi = {
  list: async () =>
    (await api.get<{ tickers: string[] }>("/saved-assets")).data,
  add: async (ticker: string) =>
    (await api.post<{ tickers: string[] }>("/saved-assets", { ticker })).data,
  remove: async (ticker: string) =>
    (await api.delete<{ tickers: string[] }>(`/saved-assets/${encodeURIComponent(ticker)}`)).data,
};

export const watchlistApi = {
  list: async () => (await api.get<{ items: WatchlistResponse[] }>("/watchlists")).data,

  get: async (id: number) => (await api.get<WatchlistResponse>(`/watchlists/${id}`)).data,

  create: async (payload: { name: string; tickers: string[] }) =>
    (await api.post<WatchlistResponse>("/watchlists", payload)).data,

  snapshot: async (id: number, period = "3mo") =>
    (await api.get<WatchlistSnapshotResponse>(`/watchlists/${id}/snapshot`, { params: { period } })).data,
};

export const alertApi = {
  list: async (params?: { active_only?: boolean; watchlist_id?: number }) =>
    (await api.get<{ items: AlertRuleResponse[] }>("/alerts", { params })).data,

  create: async (payload: {
    name: string;
    ticker: string;
    alert_type?: string;
    direction?: string;
    threshold_value?: number;
    lookback_days?: number;
    watchlist_id?: number | null;
    extra_config?: Record<string, unknown>;
    is_active?: boolean;
  }) => (await api.post<AlertRuleResponse>("/alerts", payload)).data,

  evaluate: async (params?: { active_only?: boolean; persist?: boolean }) =>
    (await api.post<AlertEvaluationSummary>("/alerts/evaluate", null, { params })).data,

  events: async (params?: {
    limit?: number;
    triggered_only?: boolean;
    ticker?: string;
    detector_source?: string;
  }) => (await api.get<{ items: AlertEventResponse[] }>("/alerts/events", { params })).data,

  remove: async (alertId: number) =>
    (await api.delete<{ deleted: boolean; alert_id: number }>(`/alerts/${alertId}`)).data,

  preferences: async () =>
    (await api.get<AlertPreferences>("/alerts/preferences")).data,

  updatePreferences: async (payload: Partial<AlertPreferences>) =>
    (await api.put<AlertPreferences>("/alerts/preferences", payload)).data,

  submitFeedback: async (eventId: number, rating: AlertRating, reason?: string) =>
    (await api.post<{ ok: boolean; rating: AlertRating; auto_muted_kind: string | null }>(
      `/alerts/events/${eventId}/feedback`, { rating, reason })).data,

  feedbackSummary: async () =>
    (await api.get<AlertFeedbackSummary>("/alerts/feedback/summary")).data,

  monitorHoldings: async (payload?: { portfolio_id?: number; cooldown_seconds?: number }) =>
    (await api.post<{ created: string[]; already_monitored: string[]; total_monitored: number }>(
      "/alerts/monitor-holdings", payload ?? {})).data,
};

export type AlertRating = "useful" | "not_useful";

export type AlertSeverity = "INFO" | "ALERT" | "WARNING" | "ANOMALY";

export type AlertPreferences = {
  id: number;
  user_id: number;
  email_enabled: boolean;
  min_severity: AlertSeverity;
  /** Inclusive start, exclusive end, 0-23. Equal values disable quiet hours. */
  quiet_hours_start: number;
  quiet_hours_end: number;
  quiet_hours_tz_offset_min: number;
  muted_tickers: string[];
  muted_kinds: string[];
  /** Consecutive "not useful" marks before a kind auto-mutes. 0 disables. */
  auto_mute_after: number;
};

export type AlertFeedbackSummary = {
  total: number;
  useful: number;
  not_useful: number;
  by_kind: Record<string, { useful: number; not_useful: number }>;
};

export type CommentaryResponse = {
  commentary: string;
  cached: boolean;
  model: string;
  prompt_tokens: number;
  output_tokens: number;
  latency_ms: number;
  source_data: Record<string, unknown>;
};

export type ScenarioTranslateResponse = {
  name: string;
  shock_pct: number;
  vol_scale: number;
  drift_shift: number;
  cached: boolean;
  latency_ms: number;
};

export type ScenarioExplanation = {
  name: string;
  headline: string;
  narrative: string;
};

export type ScenarioExplainResponse = {
  summary: string;
  explanations: ScenarioExplanation[];
  disclaimer: string;
  cached: boolean;
  model: string;
  prompt_tokens: number;
  output_tokens: number;
  latency_ms: number;
  source_data: Record<string, unknown>;
};

export type NewsSynthesisResponse = {
  summary: string;
  sentiment: "bullish" | "bearish" | "mixed" | "neutral";
  highlights: Array<{ index: number; note: string }>;
  cached: boolean;
  latency_ms: number;
  source_data: Record<string, unknown>;
};

export type NewsItemInput = {
  title: string;
  publisher?: string;
  timestamp?: string;
  type?: string;
};

export const agentsApi = {
  portfolioCommentary: async (
    portfolioId: number | string,
    payload: {
      metrics?: Record<string, number | null | undefined>;
      regime?: string;
      horizon_days?: number;
      snapshot_hash?: string;
    },
  ) =>
    (await api.post<CommentaryResponse>(`/agents/commentary/${portfolioId}`, payload)).data,

  translateScenario: async (description: string) =>
    (await api.post<ScenarioTranslateResponse>(`/agents/scenario-translate`, { description })).data,

  synthesizeNews: async (ticker: string, items: NewsItemInput[]) =>
    (await api.post<NewsSynthesisResponse>(
      `/agents/news-synthesize/${encodeURIComponent(ticker)}`,
      { items },
    )).data,

  explainAlert: async (alertId: number) =>
    (await api.post<{
      explanation: string;
      cached: boolean;
      latency_ms: number;
      source_data: Record<string, unknown>;
    }>(`/agents/alert-explain/${alertId}`)).data,

  explainScenarios: async (payload: {
    portfolio_name: string;
    portfolio_value: number;
    scenarios: Array<{
      name: string;
      shock_pct?: number;
      vol_scale?: number;
      drift_shift?: number;
      fan: ScenarioFan & { p5?: number[]; p95?: number[] };
      discovery?: Record<string, unknown>;
    }>;
  }) =>
    (await api.post<ScenarioExplainResponse>(
      `/agents/scenario-explain`, payload, { timeout: HEAVY_TIMEOUT_MS },
    )).data,

  clientQA: async (
    portfolioId: number | string,
    payload: {
      question: string;
      metrics?: Record<string, number | null | undefined>;
      regime?: string;
      snapshot_hash?: string;
    },
  ) =>
    (await api.post<{
      answer: string;
      cached: boolean;
      latency_ms: number;
      source_data: Record<string, unknown>;
    }>(`/agents/qa/${portfolioId}`, payload)).data,

  varBacktestExplain: async (portfolioId: number | string) =>
    (await api.post<VarBacktestExplainResponse>(
      `/agents/var-backtest-explain/${portfolioId}`, {}, { timeout: HEAVY_TIMEOUT_MS },
    )).data,

  qlensBrief: async (ticker: string, context?: string) =>
    (await api.post<QLensBriefResponse>(
      `/agents/qlens/${encodeURIComponent(ticker)}`,
      { context: context ?? null },
      { timeout: HEAVY_TIMEOUT_MS },
    )).data,

  clientLetter: async (portfolioId: number | string) =>
    (await api.post<ClientLetterResponse>(
      `/agents/client-letter/${portfolioId}`, {}, { timeout: HEAVY_TIMEOUT_MS },
    )).data,
};

export type ClientLetterResponse = {
  portfolio_id: number;
  greeting: string;
  performance_paragraph: string;
  diversification_paragraph: string;
  closing_paragraph: string;
  facts: {
    portfolio?: { quarter_return_pct: number; year_return_pct: number; ann_vol_pct: number; max_drawdown_pct: number; n_obs: number };
    all_stock?: { quarter_return_pct: number; ann_vol_pct: number };
    regime?: { short_corr: number; baseline_corr: number; delta: number; as_of: string | null };
  };
  disclaimer: string;
  is_draft: boolean;
  cached: boolean;
  latency_ms: number;
};

export type QLensFact = { idx: number; source: string; statement: string };
export type QLensBriefResponse = {
  ticker: string;
  stance: "Buy" | "Hold" | "Sell";
  conviction: "low" | "medium" | "high";
  bull: string[];
  bear: string[];
  key_risks: string[];
  what_would_change_my_mind: string[];
  rationale: string;
  facts: QLensFact[];
  disclaimer: string;
  cached: boolean;
  latency_ms: number;
};

export type VarBacktestExplainResponse = {
  headline: string;
  assessment: string;
  method_notes: Array<{ method: string; note: string }>;
  watch: string[];
  disclaimer: string;
  cached: boolean;
  model: string;
  latency_ms: number;
  source_data: Record<string, unknown>;
};

export const screenerApi = {
  run: async (payload: {
    symbols: string[];
    filters?: Record<string, unknown>;
    limit?: number;
  }) => (await api.post<ScreenerRunResponse>("/screener/run", payload)).data,

  createScreen: async (payload: {
    name: string;
    description?: string;
    filters: Record<string, unknown>;
  }) => (await api.post<SavedScreenResponse>("/screener/screens", payload)).data,

  listScreens: async () =>
    (await api.get<{ items: SavedScreenResponse[] }>("/screener/screens")).data,

  getScreen: async (id: number) =>
    (await api.get<SavedScreenResponse>(`/screener/screens/${id}`)).data,

  updateScreen: async (
    id: number,
    payload: { name: string; description?: string; filters: Record<string, unknown> },
  ) => (await api.put<SavedScreenResponse>(`/screener/screens/${id}`, payload)).data,

  deleteScreen: async (id: number) =>
    (await api.delete<{ deleted: boolean; screen_id: number }>(`/screener/screens/${id}`)).data,
};

/* ── Report types ── */

export type ReportAsset = { ticker: string; weight: number };

export type QuarterlyReportRequest = {
  client_name: string;
  advisor_name: string;
  firm_name: string;
  assets: ReportAsset[];
  horizon_days?: number;
  // Required by the backend — reports never invent portfolio values.
  portfolio_value?: number | null;
  // Real simulated scenarios from a Scenario Builder run; omitted -> the PDF
  // omits its scenario section rather than fabricating one.
  scenarios?: Array<{
    name: string;
    shock_pct?: number;
    vol_scale?: number;
    drift_shift?: number;
    fan: ScenarioFan & { p5?: number[]; p95?: number[] };
    discovery?: Record<string, unknown>;
  }>;
};

export type OnboardingReportRequest = {
  client_name: string;
  advisor_name: string;
  firm_name: string;
  assets: ReportAsset[];
  risk_tolerance?: string;
  target_vol?: number;
  portfolio_value?: number | null;
};

export type MarketEventReportRequest = {
  client_name: string;
  advisor_name: string;
  firm_name: string;
  assets: ReportAsset[];
  event_name: string;
  event_date: string;
  event_summary: string;
  portfolio_value?: number | null;
};

export type RebalancingReportRequest = {
  client_name: string;
  advisor_name: string;
  firm_name: string;
  current_assets: ReportAsset[];
  proposed_assets: ReportAsset[];
  rationale: string;
  tax_considerations?: string | null;
  portfolio_value?: number | null;
};

export type YearEndReportRequest = {
  client_name: string;
  advisor_name: string;
  firm_name: string;
  assets: ReportAsset[];
  review_year?: number;
  portfolio_value_start?: number | null;
  portfolio_value_end?: number | null;
};

async function downloadPdf(url: string, body: unknown, filename: string) {
  const res = await api.post(url, body, {
    responseType: "blob",
    timeout: HEAVY_TIMEOUT_MS,
  });
  const blob = new Blob([res.data], { type: "application/pdf" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

export const reportsApi = {
  quarterly: (payload: QuarterlyReportRequest) =>
    downloadPdf("/reports/quarterly", payload, `quarterly_${payload.client_name.replace(/\s+/g, "_")}.pdf`),

  onboarding: (payload: OnboardingReportRequest) =>
    downloadPdf("/reports/onboarding", payload, `onboarding_${payload.client_name.replace(/\s+/g, "_")}.pdf`),

  marketEvent: (payload: MarketEventReportRequest) =>
    downloadPdf("/reports/market-event", payload, `event_${payload.client_name.replace(/\s+/g, "_")}.pdf`),

  rebalancing: (payload: RebalancingReportRequest) =>
    downloadPdf("/reports/rebalancing", payload, `rebalance_${payload.client_name.replace(/\s+/g, "_")}.pdf`),

  yearEnd: (payload: YearEndReportRequest) =>
    downloadPdf("/reports/year-end", payload, `yearend_${payload.client_name.replace(/\s+/g, "_")}.pdf`),
};

export const healthApi = {
  check: async () => (await api.get<{ status: string; risk_service?: Record<string, unknown> }>("/health")).data,
};

export const portfolioListApi = {
  list: async (): Promise<PortfolioResponse[]> => {
    const res = await api.get<{ items: PortfolioResponse[] }>("/portfolios");
    return res.data.items ?? [];
  },
};

// ── Public (no-login) Cross-Asset Correlation Monitor ──────────────────────────
// These call the unauthenticated /public/* endpoints with plain fetch (no
// X-User-Id / bearer), so the free /correlations page works logged-out.
export type CorrelationWindowStat = { pearson: number; spearman: number; n_obs: number };
export type CorrelationSeriesPoint = { date: string; corr: number };
export type CorrelationPair = {
  pair_key: string;
  symbol_a: string;
  symbol_b: string;
  label: string;
  windows: Record<string, CorrelationWindowStat>;
  series: Record<string, CorrelationSeriesPoint[]>;
};
export type CorrelationMonitorResponse = {
  as_of: string | null;
  windows: number[];
  method: string;
  data_source: string | null;
  pairs: CorrelationPair[];
  disclaimers: string[];
  note?: string;
};

export type ReplayPoint = { date: string; corr: number; dd: number };
export type ReplayEpisode = {
  name: string;
  start: string;
  end: string;
  corr: number | null;
  blend_drawdown_pct: number;
  blend_return_pct: number;
  n_obs: number;
};
export type CorrelationReplayResponse = {
  status: "ok" | "pending";
  data_source?: string | null;
  pair?: string;
  window?: number;
  as_of?: string;
  start?: string;
  points?: ReplayPoint[];
  episodes?: ReplayEpisode[];
  disclaimers: string[];
  note?: string;
};

export const correlationApi = {
  get: async (): Promise<CorrelationMonitorResponse> => {
    const r = await fetch(`${API_BASE_URL}/public/correlations`, {
      headers: { Accept: "application/json" },
    });
    if (!r.ok) throw new Error(`Failed to load correlations (${r.status})`);
    return r.json();
  },
  replay: async (): Promise<CorrelationReplayResponse> => {
    const r = await fetch(`${API_BASE_URL}/public/correlation-replay`, {
      headers: { Accept: "application/json" },
    });
    if (!r.ok) throw new Error(`Failed to load replay (${r.status})`);
    return r.json();
  },
  signup: async (email: string): Promise<{ status: string }> => {
    const r = await fetch(`${API_BASE_URL}/public/correlation-signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    if (!r.ok) {
      let detail = "Something went wrong. Please try again.";
      try {
        const j = await r.json();
        if (typeof j?.detail === "string") detail = j.detail;
      } catch {
        /* non-JSON error body */
      }
      throw new Error(detail);
    }
    return r.json();
  },
};

// ── Authenticated Regime Watch (Qpulse regime signal on a real portfolio) ──────
// Uses the authed `api` axios instance (X-User-Id / bearer), unlike the public
// correlationApi above.
export type RegimeWatchResponse = {
  portfolio_id: number;
  status: "ok" | "na" | "pending";
  pair?: string;
  short_window?: number;
  baseline_window?: number;
  short_corr?: number;
  baseline_corr?: number;
  delta?: number;
  n_obs?: number;
  as_of?: string | null;
  computed_at?: string | null;
  stale?: boolean;
  method?: string;
  data_source?: string;
  sleeve_weights?: Record<string, number>;
  series?: CorrelationSeriesPoint[];
  reason?: string | null;
  note?: string;
  disclaimers: string[];
};

export const regimeApi = {
  get: async (portfolioId: string | number): Promise<RegimeWatchResponse> =>
    (await api.get<RegimeWatchResponse>(`/portfolios/${portfolioId}/regime_watch`)).data,
  enableAlert: async (portfolioId: string | number, margin = 0.15) =>
    (await api.post(`/portfolios/${portfolioId}/regime_watch/alert`, { margin })).data,
};
