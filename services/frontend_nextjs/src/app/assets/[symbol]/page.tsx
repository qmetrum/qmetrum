"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import {
  assetApi,
  portfolioApi,
  type AssetProfileResponse,
  type AssetForecastResponse,
  type AssetRiskResponse,
  type AssetNewsResponse,
  type AssetPriceResponse,
  type PortfolioResponse,
} from "@/lib/api";
import { portfolioListApi } from "@/lib/api";
import { useSavedAssets } from "@/lib/savedAssets";
import { MetricCard } from "@/components/shared/MetricCard";
import { RegimeBadge } from "@/components/shared/RegimeBadge";
import { CreateAlertDialog } from "@/components/shared/CreateAlertDialog";
import { AlertRulesList } from "@/components/shared/AlertRulesList";
import { NewsSynthesisCard } from "@/components/shared/NewsSynthesisCard";
import { DownloadCsvButton } from "@/components/shared/DownloadCsvButton";
import type { CsvCell } from "@/lib/csv";
import { ForecastChart } from "@/components/charts/ForecastChart";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
import { VolatilityChart } from "@/components/charts/VolatilityChart";
import { ReturnsChart } from "@/components/charts/ReturnsChart";
import { DrawdownChart } from "@/components/charts/DrawdownChart";
import { MovingAverageChart } from "@/components/charts/MovingAverageChart";
import { ScenarioPathsChart } from "@/components/charts/ScenarioPathsChart";
import type { ScenarioFan } from "@/lib/api";

const TABS = ["Overview", "Forecast & Risk", "Fundamentals", "News"] as const;
type Tab = (typeof TABS)[number];

function fmt(n: number | string | undefined | null, opts?: { prefix?: string; suffix?: string; decimals?: number }) {
  if (n == null) return "\u2014";
  const v = Number(n);
  if (isNaN(v)) return "\u2014";
  const d = opts?.decimals ?? 2;
  const s = v.toFixed(d);
  return `${opts?.prefix ?? ""}${s}${opts?.suffix ?? ""}`;
}

function fmtLarge(n: number | string | undefined | null) {
  if (n == null) return "\u2014";
  const n2 = Number(n);
  if (isNaN(n2)) return "\u2014";
  if (Math.abs(n2) >= 1e12) return `$${(n2 / 1e12).toFixed(2)}T`;
  if (Math.abs(n2) >= 1e9) return `$${(n2 / 1e9).toFixed(2)}B`;
  if (Math.abs(n2) >= 1e6) return `$${(n2 / 1e6).toFixed(1)}M`;
  return `$${n2.toLocaleString()}`;
}

function pct(n: number | string | undefined | null, decimals = 1) {
  if (n == null) return "\u2014";
  const v = Number(n);
  if (isNaN(v)) return "\u2014";
  return `${(v * 100).toFixed(decimals)}%`;
}

export default function AssetDetailPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const ticker = (symbol ?? "").toUpperCase();

  const [tab, setTab] = useState<Tab>("Overview");
  const [showAddModal, setShowAddModal] = useState(false);
  const [showAlertModal, setShowAlertModal] = useState(false);
  const { isSaved, toggle: toggleSaved } = useSavedAssets();
  const [addWeight, setAddWeight] = useState("10");
  const [addQuantity, setAddQuantity] = useState("100");
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<number | "new">("new");
  const [newPortfolioName, setNewPortfolioName] = useState("");
  const [addSaving, setAddSaving] = useState(false);

  // ── Data fetching ──
  const { data: profile, isLoading: profileLoading } = useQuery<AssetProfileResponse>({
    queryKey: ["asset-profile", ticker],
    queryFn: () => assetApi.profile(ticker),
    enabled: !!ticker,
  });

  const { data: priceData } = useQuery<AssetPriceResponse>({
    queryKey: ["asset-price", ticker],
    queryFn: () => assetApi.price(ticker),
    enabled: !!ticker,
  });

  const { data: forecast, isLoading: fcLoading } = useQuery<AssetForecastResponse>({
    queryKey: ["asset-forecast", ticker],
    queryFn: () => assetApi.forecast(ticker),
    enabled: !!ticker,
  });

  const { data: risk } = useQuery<AssetRiskResponse>({
    queryKey: ["asset-risk", ticker],
    queryFn: () => assetApi.risk(ticker),
    enabled: !!ticker,
  });

  const { data: news } = useQuery<AssetNewsResponse>({
    queryKey: ["asset-news", ticker],
    queryFn: () => assetApi.news(ticker),
    enabled: !!ticker && tab === "News",
  });

  const { data: portfolios } = useQuery<PortfolioResponse[]>({
    queryKey: ["portfolios-list"],
    queryFn: () => portfolioListApi.list(),
    enabled: showAddModal,
  });

  // ── Derived data ──
  const companyName = profile?.profile?.name ?? ticker;
  const sector = profile?.profile?.sector;
  const industry = profile?.profile?.industry;
  const description = profile?.profile?.description;

  const hPrices = forecast?.history_prices ?? priceData?.series?.map((s) => s.price) ?? [];
  const hDates = forecast?.history_dates ?? priceData?.series?.map((s) => s.date) ?? [];
  const fPrices = forecast?.forecast_prices ?? [];
  const fDates = forecast?.forecast_dates ?? [];
  const lowerCi = forecast?.lower_ci;
  const upperCi = forecast?.upper_ci;
  const mcCone = forecast?.monte_carlo_cone;

  const riskMetrics = forecast?.risk_metrics ?? {};
  const perfMetrics = forecast?.performance_metrics ?? {};
  const fundamentals = forecast?.fundamentals;
  const indicators = (forecast as Record<string, unknown>)?.indicators as Record<string, Record<string, number[]>> | undefined;
  // GARCH forecast + cone bounds live at response.volatility (top-level),
  // NOT at response.indicators.volatility (rolling realized vol of forecast prices — flat).
  const volSection = (forecast as Record<string, unknown>)?.volatility as Record<string, number[]> | undefined;
  const forecastVol = volSection?.forecast ?? indicators?.volatility?.forecast;
  const forecastVolLower = volSection?.forecast_lower;
  const forecastVolUpper = volSection?.forecast_upper;
  const forecastVolDates = fDates;
  const assetScenarios = (forecast as Record<string, unknown>)?.scenarios as Record<string, ScenarioFan> | undefined;
  const scenarioMethod = (forecast as Record<string, unknown>)?.scenario_method as string | undefined;

  const pe = profile?.valuation?.pe_ratio ?? (fundamentals?.valuation as Record<string, number> | undefined)?.pe_ratio;
  const evEbitda = profile?.valuation?.ev_to_ebitda ?? (fundamentals?.valuation as Record<string, number> | undefined)?.ev_to_ebitda;
  const marketCap = profile?.valuation?.market_cap ?? (fundamentals?.valuation as Record<string, number> | undefined)?.market_cap;
  const beta = profile?.technicals?.beta ?? (riskMetrics?.beta as number | undefined);
  const high52 = profile?.technicals?.["52_week_high"] ?? profile?.technicals?.fiftyTwoWeekHigh;
  const low52 = profile?.technicals?.["52_week_low"] ?? profile?.technicals?.fiftyTwoWeekLow;
  const currentPrice = hPrices.length > 0 ? hPrices[hPrices.length - 1] : undefined;

  const regime = (risk?.regime_latest ?? riskMetrics?.regime ?? "Normal") as string;

  // ── Add to portfolio handler ──
  const handleAddToPortfolio = async () => {
    setAddSaving(true);
    try {
      if (selectedPortfolioId === "new") {
        const name = newPortfolioName.trim() || `Portfolio with ${ticker}`;
        await portfolioApi.create({
          name,
          assets: [
            {
              ticker,
              weight: 1.0,
              quantity: parseFloat(addQuantity) || 100,
              asset_type: profile?.type ?? "EQUITY",
            },
          ],
        });
      } else {
        const existing = portfolios?.find((p) => p.portfolio_id === selectedPortfolioId);
        if (existing) {
          const alreadyHas = existing.assets.some((a) => a.ticker.toUpperCase() === ticker);
          const updatedAssets = alreadyHas
            ? existing.assets
            : [
                ...existing.assets,
                {
                  ticker,
                  weight: parseFloat(addWeight) / 100 || 0.1,
                  quantity: parseFloat(addQuantity) || 100,
                  asset_type: profile?.type ?? "EQUITY",
                },
              ];
          await portfolioApi.update(selectedPortfolioId, {
            name: existing.name,
            assets: updatedAssets,
          });
        }
      }
      queryClient.invalidateQueries({ queryKey: ["portfolios-list"] });
      setShowAddModal(false);
    } catch (err) {
      console.error("Failed to add to portfolio:", err);
    } finally {
      setAddSaving(false);
    }
  };

  if (profileLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--text-muted)]">
        Loading {ticker}...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Back link ── */}
      <button
        onClick={() => router.push("/assets")}
        className="inline-flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--navy)] transition-colors"
      >
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <line x1="19" y1="12" x2="5" y2="12" />
          <polyline points="12 19 5 12 12 5" />
        </svg>
        Back to Assets
      </button>

      {/* ── Header ── */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-[var(--navy)]">{ticker}</h1>
            <RegimeBadge regime={regime} />
          </div>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            {companyName}
            {sector && ` \u00B7 ${sector}`}
            {industry && ` \u00B7 ${industry}`}
          </p>
          {currentPrice != null && (
            <p className="text-xl font-semibold text-[var(--text-primary)] mt-2">
              ${currentPrice.toFixed(2)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => toggleSaved(ticker)}
            className={`text-sm font-medium px-4 py-2 rounded-lg border transition-colors ${
              isSaved(ticker)
                ? "bg-[var(--navy)] text-white border-[var(--navy)]"
                : "bg-white text-[var(--navy)] border-[var(--card-border)] hover:bg-[var(--content-bg)]"
            }`}
          >
            {isSaved(ticker) ? "\u2605 Saved" : "\u2606 Save Asset"}
          </button>
          <button
            onClick={() => setShowAlertModal(true)}
            className="text-sm font-medium bg-white text-[var(--navy)] border border-[var(--card-border)] px-4 py-2 rounded-lg hover:bg-[var(--content-bg)]"
          >
            Create Alert
          </button>
          <button
            onClick={() => setShowAddModal(true)}
            className="text-sm font-medium bg-[var(--teal)] text-white px-4 py-2 rounded-lg hover:opacity-90"
          >
            Add to Portfolio
          </button>
        </div>
      </div>

      <CreateAlertDialog
        open={showAlertModal}
        onClose={() => setShowAlertModal(false)}
        tickers={[ticker]}
        defaultTicker={ticker}
        currentPrice={currentPrice}
      />


      {/* ── Tabs ── */}
      <div className="flex gap-1 border-b border-[var(--card-border)]">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === t
                ? "border-[var(--teal)] text-[var(--teal)]"
                : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* ── Tab content ── */}
      {tab === "Overview" && (
        <div className="space-y-6">
          {/* KPI row */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <MetricCard label="P/E Ratio" value={fmt(pe)} color="navy" />
            <MetricCard label="EV/EBITDA" value={fmt(evEbitda)} color="navy" />
            <MetricCard label="Market Cap" value={fmtLarge(marketCap)} color="teal" />
            <MetricCard label="Beta" value={fmt(beta)} color={beta != null && beta > 1.2 ? "coral" : "blue"} />
            <MetricCard label="52W High" value={fmt(high52, { prefix: "$" })} color="teal" />
            <MetricCard label="52W Low" value={fmt(low52, { prefix: "$" })} color="coral" />
          </div>

          {/* Price chart */}
          <div className="q-card p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-[var(--text-primary)]">Price History</h2>
              <DownloadCsvButton
                filename={`${ticker}-price-history`}
                disabled={hPrices.length === 0 && fPrices.length === 0}
                build={() => {
                  const headers = ["date", "history", "forecast", "lower_95", "upper_95"];
                  const rows: CsvCell[][] = [];
                  for (let i = 0; i < hDates.length; i++) {
                    rows.push([hDates[i], hPrices[i] ?? null, null, null, null]);
                  }
                  for (let i = 0; i < fDates.length; i++) {
                    rows.push([
                      fDates[i],
                      null,
                      fPrices[i] ?? null,
                      lowerCi?.[i] ?? null,
                      upperCi?.[i] ?? null,
                    ]);
                  }
                  return { headers, rows };
                }}
              />
            </div>
            {hPrices.length > 0 ? (
              <ForecastChart
                historyPrices={hPrices}
                historyDates={hDates}
                forecastPrices={fPrices}
                forecastDates={fDates}
                lowerBound={lowerCi}
                upperBound={upperCi}
                height={380}
              />
            ) : (
              <div className="h-[380px] flex items-center justify-center text-[var(--text-muted)]">
                {fcLoading ? "Loading chart..." : "No price data available"}
              </div>
            )}
          </div>

          {/* Candlestick (weekly OHLC derived from history + forecast) */}
          {hPrices.length > 0 && (
            <div className="q-card p-5">
              <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-1">
                Weekly Candles
              </h2>
              <p className="text-xs text-[var(--text-muted)] mb-3">
                Historical prices aggregated into weekly OHLC bars; muted bars are forecast.
              </p>
              <CandlestickChart
                historyPrices={hPrices}
                historyDates={hDates}
                forecastPrices={fPrices}
                forecastDates={fDates}
              />
            </div>
          )}

          {/* Company description */}
          {description && (
            <div className="q-card p-5">
              <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-2">About</h2>
              <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{description}</p>
            </div>
          )}

          <AlertRulesList tickers={[ticker]} title={`Alerts for ${ticker}`} />
        </div>
      )}

      {tab === "Forecast & Risk" && (
        <div className="space-y-6">
          {/* Risk KPI row */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            <MetricCard
              label="Sharpe Ratio"
              value={fmt(perfMetrics?.sharpe_ratio as number)}
              color={(perfMetrics?.sharpe_ratio as number) >= 1 ? "teal" : "coral"}
            />
            <MetricCard
              label="VaR (95%)"
              value={pct(risk?.var_95_latest ?? (riskMetrics?.var_95 as number))}
              color="coral"
            />
            <MetricCard
              label="Volatility (Ann.)"
              value={pct(perfMetrics?.annualized_volatility as number)}
              color="amber"
            />
            <MetricCard
              label="Max Drawdown"
              value={pct(perfMetrics?.max_drawdown as number)}
              color="coral"
            />
            <MetricCard
              label="Sortino Ratio"
              value={fmt(perfMetrics?.sortino_ratio as number)}
              color={(perfMetrics?.sortino_ratio as number) >= 1 ? "teal" : "amber"}
            />
          </div>

          {/* Charts grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="q-card p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Price Forecast (90d)</h3>
                <DownloadCsvButton
                  filename={`${ticker}-forecast`}
                  disabled={hPrices.length === 0 && fPrices.length === 0}
                  build={() => {
                    const headers = ["date", "history", "forecast", "lower_95", "upper_95"];
                    const rows: CsvCell[][] = [];
                    for (let i = 0; i < hDates.length; i++) {
                      rows.push([hDates[i], hPrices[i] ?? null, null, null, null]);
                    }
                    for (let i = 0; i < fDates.length; i++) {
                      rows.push([
                        fDates[i],
                        null,
                        fPrices[i] ?? null,
                        mcCone?.lower_bound?.[i] ?? lowerCi?.[i] ?? null,
                        mcCone?.upper_bound?.[i] ?? upperCi?.[i] ?? null,
                      ]);
                    }
                    return { headers, rows };
                  }}
                />
              </div>
              {hPrices.length > 0 ? (
                <ForecastChart
                  historyPrices={hPrices}
                  historyDates={hDates}
                  forecastPrices={fPrices}
                  forecastDates={fDates}
                  lowerBound={mcCone?.lower_bound ?? lowerCi}
                  upperBound={mcCone?.upper_bound ?? upperCi}
                />
              ) : (
                <div className="h-[340px] flex items-center justify-center text-[var(--text-muted)]">
                  {fcLoading ? "Computing forecast..." : "No data"}
                </div>
              )}
            </div>

            <div className="q-card p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Volatility</h3>
                <DownloadCsvButton
                  filename={`${ticker}-volatility`}
                  disabled={hPrices.length === 0}
                  build={() => {
                    const headers = ["date", "price", "forecast_vol", "forecast_vol_lower", "forecast_vol_upper"];
                    const rows: CsvCell[][] = [];
                    for (let i = 0; i < hDates.length; i++) {
                      rows.push([hDates[i], hPrices[i] ?? null, null, null, null]);
                    }
                    const fcDates = forecastVolDates ?? [];
                    for (let i = 0; i < fcDates.length; i++) {
                      rows.push([
                        fcDates[i],
                        null,
                        forecastVol?.[i] ?? null,
                        forecastVolLower?.[i] ?? null,
                        forecastVolUpper?.[i] ?? null,
                      ]);
                    }
                    return { headers, rows };
                  }}
                />
              </div>
              {hPrices.length > 0 ? (
                <VolatilityChart historyPrices={hPrices} historyDates={hDates} forecastVol={forecastVol} forecastVolLower={forecastVolLower} forecastVolUpper={forecastVolUpper} forecastDates={forecastVolDates} />
              ) : (
                <div className="h-[200px] flex items-center justify-center text-[var(--text-muted)]">No data</div>
              )}
            </div>

            <div className="q-card p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Monthly Returns</h3>
                <DownloadCsvButton
                  filename={`${ticker}-monthly-returns`}
                  disabled={hPrices.length === 0}
                  build={() => {
                    const headers = ["month", "return_pct", "segment", "lower", "upper"];
                    const rows: CsvCell[][] = [];
                    const hist = forecast?.monthly_returns?.historical ?? [];
                    const fc = forecast?.monthly_returns?.forecast ?? [];
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
              {hPrices.length > 0 ? (
                <ReturnsChart
                  historyPrices={hPrices}
                  historyDates={hDates}
                  backendSeries={forecast?.monthly_returns}
                />
              ) : (
                <div className="h-[220px] flex items-center justify-center text-[var(--text-muted)]">No data</div>
              )}
            </div>

            <div className="q-card p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Drawdown</h3>
                <DownloadCsvButton
                  filename={`${ticker}-drawdown`}
                  disabled={hPrices.length === 0}
                  build={() => {
                    const headers = ["date", "drawdown_pct", "segment", "lower", "upper"];
                    const rows: CsvCell[][] = [];
                    const hist = forecast?.drawdown_series?.historical;
                    const fc = forecast?.drawdown_series?.forecast;
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
              {hPrices.length > 0 ? (
                <DrawdownChart
                  historyPrices={hPrices}
                  historyDates={hDates}
                  backendSeries={forecast?.drawdown_series}
                />
              ) : (
                <div className="h-[200px] flex items-center justify-center text-[var(--text-muted)]">No data</div>
              )}
            </div>
          </div>

          {/* VQMC single-asset price path distribution */}
          {assetScenarios && Object.keys(assetScenarios).filter(k => !k.startsWith("_")).length > 0 && fDates.length > 0 && (
            <div className="q-card p-5">
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                  Price Path Distribution
                  {scenarioMethod && !scenarioMethod.includes("fallback") && (
                    <span className="ml-2 text-[10px] font-normal text-[var(--text-muted)]">(quantum circuit-sampled)</span>
                  )}
                </h3>
                <DownloadCsvButton
                  filename={`${ticker}-scenario-paths`}
                  disabled={fDates.length === 0}
                  build={() => {
                    const scenarioKeys = Object.keys(assetScenarios).filter((k) => !k.startsWith("_"));
                    const headers = ["date", ...scenarioKeys];
                    const rows: CsvCell[][] = [];
                    for (let i = 0; i < fDates.length; i++) {
                      const row: CsvCell[] = [fDates[i]];
                      for (const k of scenarioKeys) {
                        const fan = assetScenarios[k] as ScenarioFan | undefined;
                        row.push(fan?.central?.[i] ?? null);
                      }
                      rows.push(row);
                    }
                    return { headers, rows };
                  }}
                />
              </div>
              <p className="text-xs text-[var(--text-muted)] mb-4">
                Distributional scenarios under different market conditions. Click a scenario to view its uncertainty bands.
              </p>
              <ScenarioPathsChart
                fans={assetScenarios}
                dates={fDates}
                scenarios={[
                  { name: "base", color: "#0F8B6E" },
                  { name: "bull_10", color: "#2B7ACC" },
                  { name: "bear_10", color: "#D85A30" },
                  { name: "high_vol_regime", color: "#D4920B" },
                  { name: "low_vol_regime", color: "#7C5CBF" },
                ]}
                height={320}
              />
            </div>
          )}

          <div className="q-card p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">Moving Averages</h3>
              <DownloadCsvButton
                filename={`${ticker}-moving-averages`}
                disabled={hPrices.length === 0 && fPrices.length === 0}
                build={() => {
                  const headers = ["date", "price", "segment"];
                  const rows: CsvCell[][] = [];
                  for (let i = 0; i < hDates.length; i++) {
                    rows.push([hDates[i], hPrices[i] ?? null, "historical"]);
                  }
                  for (let i = 0; i < fDates.length; i++) {
                    rows.push([fDates[i], fPrices[i] ?? null, "forecast"]);
                  }
                  return { headers, rows };
                }}
              />
            </div>
            {hPrices.length > 0 ? (
              <MovingAverageChart
                historyPrices={hPrices}
                historyDates={hDates}
                forecastPrices={fPrices}
                forecastDates={fDates}
              />
            ) : (
              <div className="h-[280px] flex items-center justify-center text-[var(--text-muted)]">No data</div>
            )}
          </div>

          {/* Risk metrics panel */}
          <div className="q-card overflow-hidden">
            <div className="border-b border-[var(--card-border)] px-5 py-3">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">Risk Metrics</h3>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-[var(--card-border)]">
              {[
                ["Fragility Score", fmt(risk?.fragility_score_latest ?? risk?.fragility_score ?? (riskMetrics?.fragility_score as number))],
                ["Beta", fmt(beta)],
                ["VaR (95%)", pct(risk?.var_95_latest ?? (riskMetrics?.var_95 as number))],
                ["Sharpe", fmt(perfMetrics?.sharpe_ratio as number)],
                ["Sortino", fmt(perfMetrics?.sortino_ratio as number)],
                ["Ann. Volatility", pct(perfMetrics?.annualized_volatility as number)],
                ["Max Drawdown", pct(perfMetrics?.max_drawdown as number)],
                ["Regime", String(regime ?? "Normal").replace(/_/g, " ")],
              ].map(([label, value]) => (
                <div key={label} className="bg-[var(--card-bg)] px-5 py-3">
                  <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider">{label}</div>
                  <div className="text-sm font-semibold text-[var(--text-primary)] mt-1">{value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === "Fundamentals" && (
        <div className="space-y-6">
          {/* Valuation */}
          <div className="q-card overflow-hidden">
            <div className="border-b border-[var(--card-border)] px-5 py-3">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">Valuation</h3>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-[var(--card-border)]">
              {[
                ["Market Cap", fmtLarge(marketCap)],
                ["P/E Ratio", fmt(pe)],
                ["Forward P/E", fmt(profile?.valuation?.forward_pe)],
                ["EV/EBITDA", fmt(evEbitda)],
              ].map(([label, value]) => (
                <div key={label} className="bg-[var(--card-bg)] px-5 py-4">
                  <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider">{label}</div>
                  <div className="text-lg font-semibold text-[var(--text-primary)] mt-1">{value}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Profitability */}
          <div className="q-card overflow-hidden">
            <div className="border-b border-[var(--card-border)] px-5 py-3">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">Profitability</h3>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-px bg-[var(--card-border)]">
              {[
                ["Profit Margin", pct(profile?.profitability?.profit_margin)],
                ["ROE", pct(profile?.profitability?.roe)],
                ["ROA", pct(profile?.profitability?.roa)],
              ].map(([label, value]) => (
                <div key={label} className="bg-[var(--card-bg)] px-5 py-4">
                  <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider">{label}</div>
                  <div className="text-lg font-semibold text-[var(--text-primary)] mt-1">{value}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Analysts */}
          {profile?.analysts && (
            <div className="q-card overflow-hidden">
              <div className="border-b border-[var(--card-border)] px-5 py-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Analyst Consensus</h3>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-px bg-[var(--card-border)]">
                {[
                  ["Target Price", fmt(profile.analysts.target_mean, { prefix: "$" })],
                  ["Recommendation", profile.analysts.recommendation ?? "\u2014"],
                  ["# Analysts", profile.analysts.num_analysts?.toString() ?? "\u2014"],
                ].map(([label, value]) => (
                  <div key={label} className="bg-[var(--card-bg)] px-5 py-4">
                    <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider">{label}</div>
                    <div className="text-lg font-semibold text-[var(--text-primary)] mt-1">{value}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Technicals */}
          <div className="q-card overflow-hidden">
            <div className="border-b border-[var(--card-border)] px-5 py-3">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">Technicals</h3>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-[var(--card-border)]">
              {[
                ["Beta", fmt(beta)],
                ["52W High", fmt(high52, { prefix: "$" })],
                ["52W Low", fmt(low52, { prefix: "$" })],
                ["Current Price", fmt(currentPrice, { prefix: "$" })],
              ].map(([label, value]) => (
                <div key={label} className="bg-[var(--card-bg)] px-5 py-4">
                  <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider">{label}</div>
                  <div className="text-lg font-semibold text-[var(--text-primary)] mt-1">{value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === "News" && (
        <div className="space-y-3">
          {news?.items && news.items.length > 0 && (
            <NewsSynthesisCard ticker={ticker} items={news.items} />
          )}
          {!news?.items?.length ? (
            <div className="q-card p-8 text-center text-[var(--text-muted)]">
              No news available for {ticker}
            </div>
          ) : (
            news.items.map((item, i) => (
              <a
                key={i}
                href={item.link ?? "#"}
                target="_blank"
                rel="noopener noreferrer"
                className="block q-card p-4 hover:border-[var(--teal)] transition-colors"
              >
                <h3 className="text-sm font-semibold text-[var(--text-primary)] leading-snug">
                  {item.title}
                </h3>
                <div className="flex items-center gap-3 mt-2 text-xs text-[var(--text-muted)]">
                  {item.publisher && <span>{item.publisher}</span>}
                  {item.timestamp && (
                    <span>{new Date(item.timestamp).toLocaleDateString()}</span>
                  )}
                  {item.type && (
                    <span className="rounded bg-[var(--content-bg)] px-2 py-0.5">{item.type}</span>
                  )}
                </div>
              </a>
            ))
          )}
        </div>
      )}

      {/* ── Add to Portfolio Modal ── */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="q-card w-full max-w-md p-6 space-y-4">
            <h2 className="text-lg font-semibold text-[var(--text-primary)]">
              Add {ticker} to Portfolio
            </h2>

            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
                Portfolio
              </label>
              <select
                value={selectedPortfolioId}
                onChange={(e) =>
                  setSelectedPortfolioId(e.target.value === "new" ? "new" : parseInt(e.target.value))
                }
                className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm text-[var(--text-primary)]"
              >
                <option value="new">+ Create New Portfolio</option>
                {portfolios?.map((p) => (
                  <option key={p.portfolio_id} value={p.portfolio_id}>
                    {p.name} ({p.assets.length} assets)
                  </option>
                ))}
              </select>
            </div>

            {selectedPortfolioId === "new" && (
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
                  Portfolio Name
                </label>
                <input
                  type="text"
                  placeholder={`Portfolio with ${ticker}`}
                  value={newPortfolioName}
                  onChange={(e) => setNewPortfolioName(e.target.value)}
                  className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm text-[var(--text-primary)]"
                />
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
                  Weight %
                </label>
                <input
                  type="number"
                  step="0.1"
                  value={addWeight}
                  onChange={(e) => setAddWeight(e.target.value)}
                  className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm text-[var(--text-primary)]"
                />
              </div>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
                  Quantity
                </label>
                <input
                  type="number"
                  step="1"
                  value={addQuantity}
                  onChange={(e) => setAddQuantity(e.target.value)}
                  className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm text-[var(--text-primary)]"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowAddModal(false)}
                className="text-sm font-medium text-[var(--text-muted)] px-4 py-2 hover:underline"
              >
                Cancel
              </button>
              <button
                onClick={handleAddToPortfolio}
                disabled={addSaving}
                className="text-sm font-medium bg-[var(--teal)] text-white px-4 py-2 rounded-lg hover:opacity-90 disabled:opacity-50"
              >
                {addSaving ? "Adding..." : "Add"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
