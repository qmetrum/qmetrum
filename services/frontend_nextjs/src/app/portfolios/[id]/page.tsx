"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import {
  portfolioApi,
  type PortfolioResponse,
  type PortfolioForecastResponse,
  type PortfolioHolding,
} from "@/lib/api";
import { MetricCard } from "@/components/shared/MetricCard";
import { RegimeBadge } from "@/components/shared/RegimeBadge";
import { CreateAlertDialog } from "@/components/shared/CreateAlertDialog";
import { AlertRulesList } from "@/components/shared/AlertRulesList";
import { PortfolioCommentaryCard } from "@/components/shared/PortfolioCommentaryCard";
import { VarBacktestCard } from "@/components/shared/VarBacktestCard";
import { DrawdownAllocationCard } from "@/components/shared/DrawdownAllocationCard";
import { ClientQADrawer } from "@/components/shared/ClientQADrawer";
import { DownloadCsvButton } from "@/components/shared/DownloadCsvButton";
import type { CsvCell } from "@/lib/csv";
import { ForecastChart } from "@/components/charts/ForecastChart";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
import { VolatilityChart } from "@/components/charts/VolatilityChart";
import { ReturnsChart } from "@/components/charts/ReturnsChart";
import { DrawdownChart } from "@/components/charts/DrawdownChart";
import { MovingAverageChart } from "@/components/charts/MovingAverageChart";

export default function PortfolioDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [horizon] = useState(90);
  const queryClient = useQueryClient();

  const [showAlertModal, setShowAlertModal] = useState(false);
  const [showQADrawer, setShowQADrawer] = useState(false);

  // --- Holdings edit state ---
  const [editing, setEditing] = useState(false);
  const [editAssets, setEditAssets] = useState<PortfolioHolding[]>([]);
  const [saving, setSaving] = useState(false);
  const [newTicker, setNewTicker] = useState("");
  const [newWeight, setNewWeight] = useState("");
  const [newQuantity, setNewQuantity] = useState("");
  const [newCostBasis, setNewCostBasis] = useState("");
  const [newPurchaseDate, setNewPurchaseDate] = useState("");
  const [newType, setNewType] = useState("EQUITY");

  const startEditing = (assets: PortfolioHolding[]) => {
    setEditAssets(assets.map((a) => ({ ...a })));
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
    setEditAssets([]);
    setNewTicker("");
    setNewWeight("");
    setNewQuantity("");
    setNewCostBasis("");
    setNewPurchaseDate("");
    setNewType("EQUITY");
  };

  const removeAsset = (idx: number) => {
    setEditAssets((prev) => prev.filter((_, i) => i !== idx));
  };

  const updateAsset = (idx: number, field: keyof PortfolioHolding, value: string) => {
    setEditAssets((prev) =>
      prev.map((a, i) => {
        if (i !== idx) return a;
        if (field === "ticker" || field === "asset_type" || field === "purchase_date") {
          return { ...a, [field]: value || (field === "purchase_date" ? null : value) };
        }
        return { ...a, [field]: value === "" ? undefined : parseFloat(value) };
      })
    );
  };

  const addAsset = () => {
    const ticker = newTicker.trim().toUpperCase();
    if (!ticker) return;
    if (editAssets.some((a) => a.ticker.toUpperCase() === ticker)) return;
    setEditAssets((prev) => [
      ...prev,
      {
        ticker,
        weight: newWeight ? parseFloat(newWeight) / 100 : undefined,
        quantity: newQuantity ? parseFloat(newQuantity) : undefined,
        cost_basis: newCostBasis ? parseFloat(newCostBasis) : undefined,
        purchase_date: newPurchaseDate || null,
        asset_type: newType,
      },
    ]);
    setNewTicker("");
    setNewWeight("");
    setNewQuantity("");
    setNewCostBasis("");
    setNewPurchaseDate("");
    setNewType("EQUITY");
  };

  const saveChanges = async () => {
    if (!portfolio || editAssets.length === 0) return;
    setSaving(true);
    try {
      await portfolioApi.update(id, {
        name: portfolio.name,
        assets: editAssets,
      });
      cancelEditing();
      queryClient.invalidateQueries({ queryKey: ["portfolio", id] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-forecast", id] });
    } catch (err) {
      console.error("Failed to update portfolio:", err);
    } finally {
      setSaving(false);
    }
  };

  const { data: portfolio, isLoading: pLoading } = useQuery({
    queryKey: ["portfolio", id],
    queryFn: () => portfolioApi.get(id),
  });

  const { data: forecastRaw, isLoading: fLoading } = useQuery({
    queryKey: ["portfolio-forecast", id, horizon],
    queryFn: () =>
      portfolioApi.forecast(id, { horizon_days: horizon }, { async_mode: false }),
    enabled: !!portfolio,
  });

  const forecast: PortfolioForecastResponse | null | undefined =
    forecastRaw?.result ?? forecastRaw as unknown as PortfolioForecastResponse;
  const summary = forecast?.portfolio_summary;
  const perf = summary?.performance_metrics ?? {};
  const risk = summary?.risk_metrics ?? {};
  const regime = String(summary?.regime ?? risk?.regime_latest ?? "Normal");

  const forecastPrices = summary?.forecast_prices ?? [];
  const forecastDates = summary?.forecast_dates ?? [];
  const mc = summary?.monte_carlo_cone;

  // Extract history prices from holdings or cache blob
  const holdings = forecast?.holdings ?? [];
  // Build synthetic portfolio history from forecast data if available
  // The cache blob may contain history_prices/history_dates at the top level
  const rawResult = forecastRaw?.result as Record<string, unknown> | undefined;
  const historyPrices: number[] = (rawResult?.portfolio_prices as number[]) ?? (rawResult?.history_prices as number[]) ?? [];
  const historyDates: string[] = (rawResult?.dates as string[]) ?? (rawResult?.history_dates as string[]) ?? [];

  // GARCH forecast volatility + cone live at the top-level "volatility"
  // section (representative path with realistic variation). The
  // indicators.volatility.forecast is a rolling realized-vol series on
  // forecast prices and is flat — use it only as a last-resort fallback.
  const summaryIndicators = summary?.indicators as Record<string, Record<string, number[]>> | undefined;
  const volSection = (forecast as Record<string, unknown>)?.volatility as Record<string, number[]> | undefined
    ?? (summary as Record<string, unknown>)?.volatility as Record<string, number[]> | undefined;
  const sigmaFcMean = volSection?.forecast ?? summaryIndicators?.volatility?.forecast ?? [];
  const sigmaFcLower = volSection?.forecast_lower ?? summaryIndicators?.volatility?.forecast_lower;
  const sigmaFcUpper = volSection?.forecast_upper ?? summaryIndicators?.volatility?.forecast_upper;

  const n = (v: unknown, fallback = 0): number => {
    if (typeof v === "number") return v;
    if (typeof v === "string") { const p = parseFloat(v); return isNaN(p) ? fallback : p; }
    return fallback;
  };

  const loading = pLoading || fLoading;

  return (
    <div className="space-y-6">
      {/* ── Back link ── */}
      <button
        onClick={() => router.push("/portfolios")}
        className="inline-flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--navy)] transition-colors"
      >
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <line x1="19" y1="12" x2="5" y2="12" />
          <polyline points="12 19 5 12 12 5" />
        </svg>
        Back to Portfolios
      </button>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--navy)]">
            {portfolio?.name ?? `Portfolio #${id}`}
          </h1>
          <p className="text-sm text-[var(--text-secondary)]">
            {(portfolio?.assets ?? []).length} holdings
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowQADrawer(true)}
            className="text-sm font-medium bg-[var(--teal)] text-white px-4 py-2 rounded-lg hover:opacity-90"
          >
            Ask Advisor
          </button>
          <button
            onClick={() => setShowAlertModal(true)}
            disabled={(portfolio?.assets ?? []).length === 0}
            className="text-sm font-medium bg-white text-[var(--navy)] border border-[var(--card-border)] px-4 py-2 rounded-lg hover:bg-[var(--content-bg)] disabled:opacity-50"
          >
            Create Alert
          </button>
          <RegimeBadge regime={regime} />
        </div>
      </div>

      <CreateAlertDialog
        open={showAlertModal}
        onClose={() => setShowAlertModal(false)}
        tickers={(portfolio?.assets ?? []).map((a) => a.ticker.toUpperCase())}
      />

      <ClientQADrawer
        open={showQADrawer}
        onClose={() => setShowQADrawer(false)}
        portfolioId={id}
        portfolioName={portfolio?.name ?? `Portfolio #${id}`}
        metrics={{
          sharpe_ratio: n(perf.sharpe_ratio ?? risk.sharpe_ratio),
          sortino_ratio: n(perf.sortino_ratio ?? risk.sortino_ratio),
          annualized_volatility: n(perf.annualized_volatility ?? risk.annualized_volatility),
          var_95: n(risk.var_95 ?? risk.var_95_latest),
          max_drawdown: n(perf.max_drawdown ?? risk.max_drawdown),
        }}
        regime={regime}
        snapshotHash={forecastDates[forecastDates.length - 1] ?? undefined}
      />


      {/* Metric cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <MetricCard
          label="Sharpe Ratio"
          value={loading ? "..." : n(perf.sharpe_ratio ?? risk.sharpe_ratio).toFixed(2)}
          color="teal"
        />
        <MetricCard
          label="VaR (95%)"
          value={loading ? "..." : `${(n(risk.var_95 ?? risk.var_95_latest) * 100).toFixed(2)}%`}
          color="coral"
        />
        <MetricCard
          label="Ann. Volatility"
          value={loading ? "..." : `${(n(perf.annualized_volatility ?? risk.annualized_volatility) * 100).toFixed(1)}%`}
          color="amber"
        />
        <MetricCard
          label="Max Drawdown"
          value={loading ? "..." : `${(n(perf.max_drawdown ?? risk.max_drawdown) * 100).toFixed(1)}%`}
          color="coral"
        />
        <MetricCard
          label="CDaR (95%)"
          value={loading ? "..." : `${(n(perf.cdar_95 ?? risk.cdar_95) * 100).toFixed(1)}%`}
          sub="Avg drawdown, worst 5% of days"
          color="coral"
        />
        <MetricCard
          label="Sortino"
          value={loading ? "..." : n(perf.sortino_ratio ?? risk.sortino_ratio).toFixed(2)}
          color="blue"
        />
      </div>

      <PortfolioCommentaryCard
        portfolioId={id}
        metrics={{
          sharpe_ratio: n(perf.sharpe_ratio ?? risk.sharpe_ratio),
          sortino_ratio: n(perf.sortino_ratio ?? risk.sortino_ratio),
          annualized_volatility: n(perf.annualized_volatility ?? risk.annualized_volatility),
          var_95: n(risk.var_95 ?? risk.var_95_latest),
          max_drawdown: n(perf.max_drawdown ?? risk.max_drawdown),
        }}
        regime={regime}
        horizonDays={horizon}
        snapshotHash={forecastDates[forecastDates.length - 1] ?? undefined}
        disabled={loading}
      />

      {/* Main Forecast Chart — history + forecast + confidence bands */}
      <div className="q-card p-5">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            Portfolio Forecast — {horizon}-day horizon
          </h2>
          <DownloadCsvButton
            filename={`portfolio-${id}-forecast`}
            disabled={loading || (historyDates.length === 0 && forecastDates.length === 0)}
            build={() => {
              const headers = ["date", "history", "forecast", "lower_95", "upper_95"];
              const rows: CsvCell[][] = [];
              for (let i = 0; i < historyDates.length; i++) {
                rows.push([historyDates[i], historyPrices[i] ?? null, null, null, null]);
              }
              for (let i = 0; i < forecastDates.length; i++) {
                rows.push([
                  forecastDates[i],
                  null,
                  forecastPrices[i] ?? null,
                  mc?.lower_bound?.[i] ?? null,
                  mc?.upper_bound?.[i] ?? null,
                ]);
              }
              return { headers, rows };
            }}
          />
        </div>
        <p className="text-xs text-[var(--text-muted)] mb-4">
          Historical prices (dark) with {horizon}-day forecast (teal) and 95% confidence interval
        </p>
        {loading ? (
          <div className="flex h-80 items-center justify-center text-sm text-[var(--text-muted)]">
            Loading forecast data...
          </div>
        ) : (
          <ForecastChart
            historyPrices={historyPrices}
            historyDates={historyDates}
            forecastPrices={forecastPrices}
            forecastDates={forecastDates}
            lowerBound={mc?.lower_bound}
            upperBound={mc?.upper_bound}
            height={340}
          />
        )}
      </div>

      {/* Candlestick (weekly OHLC derived from history + forecast) */}
      {(historyDates.length > 0 || forecastDates.length > 0) && (
        <div className="q-card p-5">
          <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-1">
            Weekly Candles
          </h2>
          <p className="text-xs text-[var(--text-muted)] mb-3">
            Portfolio price aggregated into weekly OHLC bars; muted bars are forecast.
          </p>
          <CandlestickChart
            historyPrices={historyPrices}
            historyDates={historyDates}
            forecastPrices={forecastPrices}
            forecastDates={forecastDates}
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Volatility Over Time */}
        <div className="q-card p-5">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              Volatility Over Time
            </h2>
            <DownloadCsvButton
              filename={`portfolio-${id}-volatility`}
              disabled={loading || historyDates.length === 0}
              build={() => {
                const headers = ["date", "price", "forecast_vol", "forecast_vol_lower", "forecast_vol_upper"];
                const rows: CsvCell[][] = [];
                for (let i = 0; i < historyDates.length; i++) {
                  rows.push([historyDates[i], historyPrices[i] ?? null, null, null, null]);
                }
                const fcDates = sigmaFcMean.length > 0 ? forecastDates.slice(0, sigmaFcMean.length) : [];
                for (let i = 0; i < fcDates.length; i++) {
                  rows.push([
                    fcDates[i],
                    null,
                    sigmaFcMean[i] ?? null,
                    sigmaFcLower?.[i] ?? null,
                    sigmaFcUpper?.[i] ?? null,
                  ]);
                }
                return { headers, rows };
              }}
            />
          </div>
          <p className="text-xs text-[var(--text-muted)] mb-4">
            21-day rolling realized vol (dark) with GARCH forecast (amber dashed)
          </p>
          {loading ? (
            <div className="flex h-64 items-center justify-center text-sm text-[var(--text-muted)]">
              Loading...
            </div>
          ) : (
            <VolatilityChart
              historyPrices={historyPrices}
              historyDates={historyDates}
              forecastVol={sigmaFcMean.length > 0 ? sigmaFcMean : undefined}
              forecastVolLower={sigmaFcLower}
              forecastVolUpper={sigmaFcUpper}
              forecastDates={sigmaFcMean.length > 0 ? forecastDates.slice(0, sigmaFcMean.length) : undefined}
              height={260}
            />
          )}
        </div>

        {/* Monthly Returns */}
        <div className="q-card p-5">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              Monthly Returns
            </h2>
            <DownloadCsvButton
              filename={`portfolio-${id}-monthly-returns`}
              disabled={loading}
              build={() => {
                const headers = ["month", "return_pct", "segment", "lower", "upper"];
                const rows: CsvCell[][] = [];
                const hist = summary?.monthly_returns?.historical ?? [];
                const fc = summary?.monthly_returns?.forecast ?? [];
                for (const r of hist) {
                  rows.push([r.month, r.return, "historical", r.lower ?? null, r.upper ?? null]);
                }
                for (const r of fc) {
                  rows.push([r.month, r.return, "forecast", r.lower ?? null, r.upper ?? null]);
                }
                return { headers, rows };
              }}
            />
          </div>
          <p className="text-xs text-[var(--text-muted)] mb-4">
            Trailing 12-month returns (green = positive, red = negative)
          </p>
          {loading ? (
            <div className="flex h-64 items-center justify-center text-sm text-[var(--text-muted)]">
              Loading...
            </div>
          ) : (
            <ReturnsChart
              historyPrices={historyPrices}
              historyDates={historyDates}
              backendSeries={summary?.monthly_returns}
              height={260}
            />
          )}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Drawdown */}
        <div className="q-card p-5">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              Drawdown Profile
            </h2>
            <DownloadCsvButton
              filename={`portfolio-${id}-drawdown`}
              disabled={loading}
              build={() => {
                const headers = ["date", "drawdown_pct", "segment", "lower", "upper"];
                const rows: CsvCell[][] = [];
                const hist = summary?.drawdown_series?.historical;
                const fc = summary?.drawdown_series?.forecast;
                const histDates = hist?.dates ?? [];
                const histVals = hist?.values ?? [];
                for (let i = 0; i < histDates.length; i++) {
                  rows.push([histDates[i], histVals[i] ?? null, "historical", null, null]);
                }
                const fcDates = fc?.dates ?? [];
                const fcVals = fc?.values ?? [];
                for (let i = 0; i < fcDates.length; i++) {
                  rows.push([
                    fcDates[i],
                    fcVals[i] ?? null,
                    "forecast",
                    fc?.lower?.[i] ?? null,
                    fc?.upper?.[i] ?? null,
                  ]);
                }
                return { headers, rows };
              }}
            />
          </div>
          <p className="text-xs text-[var(--text-muted)] mb-4">
            Peak-to-trough decline over the trailing year
          </p>
          {loading ? (
            <div className="flex h-52 items-center justify-center text-sm text-[var(--text-muted)]">
              Loading...
            </div>
          ) : (
            <DrawdownChart
              historyPrices={historyPrices}
              historyDates={historyDates}
              backendSeries={summary?.drawdown_series}
              height={220}
            />
          )}
        </div>

        {/* Moving Averages */}
        <div className="q-card p-5">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              Price with Moving Averages
            </h2>
            <DownloadCsvButton
              filename={`portfolio-${id}-moving-averages`}
              disabled={loading || (historyDates.length === 0 && forecastDates.length === 0)}
              build={() => {
                const headers = ["date", "price", "segment"];
                const rows: CsvCell[][] = [];
                for (let i = 0; i < historyDates.length; i++) {
                  rows.push([historyDates[i], historyPrices[i] ?? null, "historical"]);
                }
                for (let i = 0; i < forecastDates.length; i++) {
                  rows.push([forecastDates[i], forecastPrices[i] ?? null, "forecast"]);
                }
                return { headers, rows };
              }}
            />
          </div>
          <p className="text-xs text-[var(--text-muted)] mb-4">
            <span className="inline-block w-3 h-0.5 bg-[#D4920B] mr-1 align-middle" /> MA(50)
            <span className="inline-block w-3 h-0.5 bg-[#8B5CF6] ml-3 mr-1 align-middle" /> MA(200)
            — extended through forecast period
          </p>
          {loading ? (
            <div className="flex h-72 items-center justify-center text-sm text-[var(--text-muted)]">
              Loading...
            </div>
          ) : (
            <MovingAverageChart
              historyPrices={historyPrices}
              historyDates={historyDates}
              forecastPrices={forecastPrices}
              forecastDates={forecastDates}
              height={280}
            />
          )}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Risk Panel */}
        <div className="q-card p-5 space-y-4">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Risk Metrics</h2>
          <div className="space-y-3">
            {[
              { label: "Fragility Score", value: n(risk.fragility_score ?? risk.fragility_score_latest, 1).toFixed(2), warn: n(risk.fragility_score ?? risk.fragility_score_latest, 1) > 1.5 },
              { label: "Beta", value: n(risk.beta, 1.0).toFixed(2), warn: false },
              { label: "Sharpe Ratio", value: n(perf.sharpe_ratio ?? risk.sharpe_ratio).toFixed(2), warn: n(perf.sharpe_ratio ?? risk.sharpe_ratio) < 0.5 },
              { label: "CVaR (95%)", value: `${(n(risk.cvar_95) * 100).toFixed(2)}%`, warn: true },
              { label: "VaR (95% daily)", value: `${(n(risk.var_95 ?? risk.var_95_latest) * 100).toFixed(2)}%`, warn: false },
            ].map(({ label, value, warn }) => (
              <div key={label} className="flex items-center justify-between rounded-lg bg-[var(--content-bg)] px-3 py-2.5">
                <span className="text-xs text-[var(--text-secondary)]">{label}</span>
                <span className={`text-sm font-semibold ${warn ? "text-[var(--coral)]" : "text-[var(--navy)]"}`}>
                  {loading ? "..." : value}
                </span>
              </div>
            ))}
          </div>

          {/* Sector Exposure */}
          {summary?.sector_exposure && Object.keys(summary.sector_exposure).length > 0 && (
            <>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] pt-2">
                Sector Exposure
              </h3>
              <div className="space-y-1.5">
                {Object.entries(summary.sector_exposure).map(([sector, weight]) => (
                  <div key={sector} className="flex items-center gap-2">
                    <div className="flex-1 h-2 rounded-full bg-[var(--content-bg)] overflow-hidden">
                      <div
                        className="h-full rounded-full bg-[var(--teal)]"
                        style={{ width: `${(weight as number) * 100}%` }}
                      />
                    </div>
                    <span className="text-xs text-[var(--text-secondary)] w-24 text-right">
                      {sector} {((weight as number) * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Holdings Table */}
        <div className="lg:col-span-2 q-card overflow-hidden">
          <div className="border-b border-[var(--card-border)] px-5 py-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">Holdings</h2>
            {!editing ? (
              <button
                onClick={() => startEditing(portfolio?.assets ?? [])}
                className="text-xs font-medium text-[var(--teal)] hover:underline"
              >
                Edit Holdings
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <button
                  onClick={cancelEditing}
                  className="text-xs font-medium text-[var(--text-muted)] hover:underline"
                >
                  Cancel
                </button>
                <button
                  onClick={saveChanges}
                  disabled={saving || editAssets.length === 0}
                  className="text-xs font-medium bg-[var(--teal)] text-white px-3 py-1 rounded hover:opacity-90 disabled:opacity-50"
                >
                  {saving ? "Saving..." : "Save"}
                </button>
              </div>
            )}
          </div>

          {!editing ? (
            /* --- Read-only view --- */
            <div>
              {portfolio?.totals && (
                <div className="grid grid-cols-2 gap-4 border-b border-[var(--card-border)] bg-[var(--content-bg)] px-5 py-4 md:grid-cols-4">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Cost Basis</div>
                    <div className="text-lg font-semibold text-[var(--navy)]">
                      ${portfolio.totals.cost_basis.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Current Value</div>
                    <div className="text-lg font-semibold text-[var(--navy)]">
                      ${portfolio.totals.current_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Unrealized P&amp;L</div>
                    <div className={`text-lg font-semibold ${portfolio.totals.unrealized_pnl >= 0 ? "text-[var(--teal)]" : "text-[var(--coral)]"}`}>
                      {portfolio.totals.unrealized_pnl >= 0 ? "+" : ""}${portfolio.totals.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}{" "}
                      <span className="text-sm font-normal">
                        ({portfolio.totals.unrealized_pnl_pct >= 0 ? "+" : ""}{(portfolio.totals.unrealized_pnl_pct * 100).toFixed(2)}%)
                      </span>
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Today&apos;s P&amp;L</div>
                    <div className={`text-lg font-semibold ${portfolio.totals.daily_pnl >= 0 ? "text-[var(--teal)]" : "text-[var(--coral)]"}`}>
                      {portfolio.totals.daily_pnl >= 0 ? "+" : ""}${portfolio.totals.daily_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>
                  </div>
                </div>
              )}
              <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="border-b border-[var(--card-border)] bg-[var(--content-bg)]">
                    <th className="px-5 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Ticker</th>
                    <th className="px-5 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Weight</th>
                    <th className="px-5 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Price</th>
                    {portfolio?.has_cost_basis_data && (
                      <>
                        <th className="px-5 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Value</th>
                        <th className="px-5 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">P&amp;L</th>
                      </>
                    )}
                    <th className="px-5 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Forecast Return</th>
                    <th className="px-5 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Type</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--card-border)]">
                  {(portfolio?.assets ?? []).map((a, i) => {
                    const h = holdings.find((x: Record<string, unknown>) => x.ticker === a.ticker);
                    const fcRet = h?.forecast_return as number | undefined;
                    const displayPrice = a.current_price ?? (h?.current_price as number | undefined);
                    return (
                      <tr key={i} className="hover:bg-[var(--content-bg)] transition-colors">
                        <td className="px-5 py-2.5 font-semibold text-[var(--navy)]">{a.ticker}</td>
                        <td className="px-5 py-2.5 text-right text-[var(--text-secondary)]">
                          {a.weight != null ? `${(a.weight * 100).toFixed(1)}%` : "\u2014"}
                        </td>
                        <td className="px-5 py-2.5 text-right text-[var(--text-secondary)]">
                          {displayPrice != null ? `$${displayPrice.toFixed(2)}` : "\u2014"}
                        </td>
                        {portfolio?.has_cost_basis_data && (
                          <>
                            <td className="px-5 py-2.5 text-right text-[var(--text-secondary)]">
                              {a.current_value != null
                                ? `$${a.current_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                                : "\u2014"}
                            </td>
                            <td className={`px-5 py-2.5 text-right font-medium ${a.unrealized_pnl != null && a.unrealized_pnl >= 0 ? "text-[var(--teal)]" : a.unrealized_pnl != null ? "text-[var(--coral)]" : "text-[var(--text-muted)]"}`}>
                              {a.unrealized_pnl != null
                                ? `${a.unrealized_pnl >= 0 ? "+" : ""}$${a.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                                : "\u2014"}
                            </td>
                          </>
                        )}
                        <td className={`px-5 py-2.5 text-right font-medium ${fcRet != null && fcRet >= 0 ? "text-[var(--teal)]" : "text-[var(--coral)]"}`}>
                          {fcRet != null ? `${fcRet >= 0 ? "+" : ""}${(fcRet * 100).toFixed(1)}%` : "\u2014"}
                        </td>
                        <td className="px-5 py-2.5 text-[var(--text-muted)] capitalize">
                          {a.asset_type ?? "equity"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table></div>
            </div>
          ) : (
            /* --- Edit view --- */
            <div>
              <div className="border-b border-[var(--card-border)] bg-[var(--content-bg)] px-5 py-2 text-xs text-[var(--text-muted)]">
                Tip: Cost basis and shares are optional. Fill them in to track $ P&amp;L; leave blank for weight-only tracking.
              </div>
              <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="border-b border-[var(--card-border)] bg-[var(--content-bg)]">
                    <th className="px-5 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Ticker</th>
                    <th className="px-5 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Weight %</th>
                    <th className="px-5 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Shares</th>
                    <th className="px-5 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Cost Basis $</th>
                    <th className="px-5 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Purchase Date</th>
                    <th className="px-5 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Type</th>
                    <th className="px-5 py-2.5 text-center text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--card-border)]">
                  {editAssets.map((a, i) => (
                    <tr key={i} className="hover:bg-[var(--content-bg)] transition-colors">
                      <td className="px-5 py-2 font-semibold text-[var(--navy)]">{a.ticker}</td>
                      <td className="px-5 py-2 text-right">
                        <input
                          type="number"
                          step="0.1"
                          value={a.weight != null ? (a.weight * 100).toFixed(1) : ""}
                          onChange={(e) => updateAsset(i, "weight", e.target.value ? String(parseFloat(e.target.value) / 100) : "")}
                          className="w-20 rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-2 py-1 text-right text-sm text-[var(--text-primary)]"
                        />
                      </td>
                      <td className="px-5 py-2 text-right">
                        <input
                          type="number"
                          step="0.0001"
                          value={a.quantity ?? ""}
                          onChange={(e) => updateAsset(i, "quantity", e.target.value)}
                          className="w-24 rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-2 py-1 text-right text-sm text-[var(--text-primary)]"
                        />
                      </td>
                      <td className="px-5 py-2 text-right">
                        <input
                          type="number"
                          step="0.01"
                          value={a.cost_basis ?? ""}
                          onChange={(e) => updateAsset(i, "cost_basis", e.target.value)}
                          className="w-28 rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-2 py-1 text-right text-sm text-[var(--text-primary)]"
                        />
                      </td>
                      <td className="px-5 py-2">
                        <input
                          type="date"
                          value={a.purchase_date ? a.purchase_date.slice(0, 10) : ""}
                          onChange={(e) => updateAsset(i, "purchase_date", e.target.value)}
                          className="rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-2 py-1 text-sm text-[var(--text-primary)]"
                        />
                      </td>
                      <td className="px-5 py-2">
                        <select
                          value={a.asset_type ?? "EQUITY"}
                          onChange={(e) => updateAsset(i, "asset_type", e.target.value)}
                          className="rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-2 py-1 text-sm text-[var(--text-primary)]"
                        >
                          <option value="EQUITY">Equity</option>
                          <option value="ETF">ETF</option>
                          <option value="BOND">Bond</option>
                          <option value="CRYPTO">Crypto</option>
                        </select>
                      </td>
                      <td className="px-5 py-2 text-center">
                        <button
                          onClick={() => removeAsset(i)}
                          className="text-xs text-[var(--coral)] hover:underline"
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table></div>

              {/* Add new asset row */}
              <div className="flex flex-wrap items-center gap-2 border-t border-[var(--card-border)] px-5 py-3 bg-[var(--content-bg)]">
                <input
                  type="text"
                  placeholder="Ticker"
                  value={newTicker}
                  onChange={(e) => setNewTicker(e.target.value.toUpperCase())}
                  onKeyDown={(e) => e.key === "Enter" && addAsset()}
                  className="w-24 rounded border border-[var(--card-border)] bg-white px-2 py-1 text-sm text-[var(--text-primary)]"
                />
                <input
                  type="number"
                  placeholder="Weight %"
                  step="0.1"
                  value={newWeight}
                  onChange={(e) => setNewWeight(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addAsset()}
                  className="w-20 rounded border border-[var(--card-border)] bg-white px-2 py-1 text-sm text-[var(--text-primary)]"
                />
                <input
                  type="number"
                  placeholder="Shares"
                  step="0.0001"
                  value={newQuantity}
                  onChange={(e) => setNewQuantity(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addAsset()}
                  className="w-24 rounded border border-[var(--card-border)] bg-white px-2 py-1 text-sm text-[var(--text-primary)]"
                />
                <input
                  type="number"
                  placeholder="Cost basis $"
                  step="0.01"
                  value={newCostBasis}
                  onChange={(e) => setNewCostBasis(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addAsset()}
                  className="w-28 rounded border border-[var(--card-border)] bg-white px-2 py-1 text-sm text-[var(--text-primary)]"
                />
                <input
                  type="date"
                  value={newPurchaseDate}
                  onChange={(e) => setNewPurchaseDate(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addAsset()}
                  className="rounded border border-[var(--card-border)] bg-white px-2 py-1 text-sm text-[var(--text-primary)]"
                />
                <select
                  value={newType}
                  onChange={(e) => setNewType(e.target.value)}
                  className="rounded border border-[var(--card-border)] bg-white px-2 py-1 text-sm text-[var(--text-primary)]"
                >
                  <option value="EQUITY">Equity</option>
                  <option value="ETF">ETF</option>
                  <option value="BOND">Bond</option>
                  <option value="CRYPTO">Crypto</option>
                </select>
                <button
                  onClick={addAsset}
                  disabled={!newTicker.trim()}
                  className="text-xs font-medium bg-[var(--btn-navy)] text-white px-3 py-1 rounded hover:opacity-90 disabled:opacity-50"
                >
                  + Add
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* VaR 95 backtest (Kupiec / Christoffersen coverage) */}
      <VarBacktestCard portfolioId={id} />

      {/* Drawdown-managed allocation: method comparison + apply weights */}
      <DrawdownAllocationCard
        portfolioId={id}
        onApply={async (weights) => {
          const base = portfolio?.assets ?? [];
          if (base.length === 0) return;
          const merged = base.map((a) => ({
            ...a,
            weight: weights[a.ticker] ?? a.weight ?? 0,
          }));
          await portfolioApi.update(id, { name: portfolio!.name, assets: merged });
          queryClient.invalidateQueries({ queryKey: ["portfolio", id] });
          queryClient.invalidateQueries({ queryKey: ["portfolio-forecast", id] });
        }}
      />

      <AlertRulesList
        tickers={(portfolio?.assets ?? []).map((a) => a.ticker.toUpperCase())}
        title="Portfolio Alerts"
      />
    </div>
  );
}
