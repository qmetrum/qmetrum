"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useBranding } from "@/components/providers/BrandingProvider";
import {
  agentsApi,
  portfolioApi,
  portfolioListApi,
  reportsApi,
  type PortfolioResponse,
  type ForecastScenarioInput,
  type ScenarioFan,
} from "@/lib/api";
import { MetricCard } from "@/components/shared/MetricCard";
import { ScenarioPathsChart } from "@/components/charts/ScenarioPathsChart";
import { ScenarioSummaryCard } from "@/components/shared/ScenarioSummaryCard";
import { ScenarioExplainerCard } from "@/components/shared/ScenarioExplainerCard";
import { DownloadCsvButton } from "@/components/shared/DownloadCsvButton";
import type { CsvCell } from "@/lib/csv";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  Cell,
} from "recharts";

const PRESETS: { name: string; shock: number; volScale: number; drift: number; color: string }[] = [
  { name: "Base Case", shock: 0, volScale: 1, drift: 0, color: "#0F8B6E" },
  { name: "Mild Recession", shock: -5, volScale: 1.3, drift: -0.001, color: "#D4920B" },
  { name: "Severe Downturn", shock: -15, volScale: 2, drift: -0.003, color: "#D85A30" },
  { name: "Rate Spike", shock: -3, volScale: 1.5, drift: -0.0005, color: "#2B7ACC" },
  { name: "Strong Recovery", shock: 5, volScale: 0.8, drift: 0.002, color: "#0F8B6E" },
];

const CUSTOM_COLORS = [
  "#7C5CBF", // purple
  "#059669", // emerald
  "#DB2777", // pink
  "#EA580C", // orange
  "#0891B2", // cyan
  "#9333EA", // violet
  "#65A30D", // lime
  "#E11D48", // rose
];

function pickNextColor(used: string[]): string {
  for (const c of CUSTOM_COLORS) {
    if (!used.includes(c)) return c;
  }
  // All used once → wrap around by count
  return CUSTOM_COLORS[used.length % CUSTOM_COLORS.length];
}

export default function ScenariosPage() {
  const branding = useBranding();
  const [selectedPortfolio, setSelectedPortfolio] = useState<string>("");
  const [equityShock, setEquityShock] = useState(0);
  const [volScale, setVolScale] = useState(1);
  const [driftShift, setDriftShift] = useState(0);
  const [customName, setCustomName] = useState("Custom Scenario");
  const [scenarios, setScenarios] = useState(PRESETS);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<Record<string, number[]> | null>(null);
  const [fanResults, setFanResults] = useState<Record<string, ScenarioFan> | null>(null);
  const [forecastDates, setForecastDates] = useState<string[]>([]);
  const [portfolioValue, setPortfolioValue] = useState(1_000_000);
  const [nlDescription, setNlDescription] = useState("");
  // Bumped on every completed run — remounts the AI cards so explanations
  // from a previous scenario set / portfolio never linger next to new results.
  const [runId, setRunId] = useState(0);
  // Include the server's built-in calibration scenarios (bull_10, bear_10,
  // high/low vol) alongside the configured set. Base and the adversarial
  // worst-case are always computed regardless.
  const [includeBuiltins, setIncludeBuiltins] = useState(true);
  // Flag value snapshotted when the displayed run completed — the legend must
  // describe the results on screen, not the live checkbox state.
  const [runHadBuiltins, setRunHadBuiltins] = useState(true);

  const translateMutation = useMutation({
    mutationFn: (desc: string) => agentsApi.translateScenario(desc),
    onSuccess: (res) => {
      setEquityShock(res.shock_pct);
      setVolScale(res.vol_scale);
      setDriftShift(res.drift_shift);
      setCustomName(res.name);
      setScenarios((prev) => {
        // Skip if a scenario with the same name + params already exists
        const dup = prev.find(
          (s) =>
            s.name === res.name &&
            s.shock === res.shock_pct &&
            s.volScale === res.vol_scale &&
            s.drift === res.drift_shift,
        );
        if (dup) return prev;
        return [
          ...prev,
          {
            name: res.name,
            shock: res.shock_pct,
            volScale: res.vol_scale,
            drift: res.drift_shift,
            color: pickNextColor(prev.map((s) => s.color)),
          },
        ];
      });
      setNlDescription("");
    },
  });

  const { data: portfolios } = useQuery({
    queryKey: ["portfolios-list"],
    queryFn: portfolioListApi.list,
  });

  async function runScenarios() {
    if (!selectedPortfolio) return;
    setRunning(true);
    try {
      const scenarioInputs: ForecastScenarioInput[] = scenarios.map((s) => ({
        name: s.name,
        initial_shock_pct: s.shock / 100,
        return_scale: s.volScale,
        drift_shift: s.drift,
      }));
      const res = await portfolioApi.forecast(
        selectedPortfolio,
        { horizon_days: 90, scenarios: scenarioInputs, include_builtin_scenarios: includeBuiltins },
        { async_mode: false }
      );
      const fc = res?.result ?? res;
      const summary = (fc as Record<string, unknown>)?.portfolio_summary as Record<string, unknown> | undefined;
      // Prefer the new fan shape's `central` path when present; fall back to the
      // legacy flat-array emission for backward compatibility.
      const scenarioBlob = summary?.scenarios as Record<string, unknown> | undefined;
      const scenarioLegacy = summary?.scenarios_legacy as Record<string, number[]> | undefined;
      const dates = (summary?.forecast_dates as string[] | undefined) ?? [];
      setForecastDates(dates);
      let flat: Record<string, number[]> | null = null;
      const fans: Record<string, ScenarioFan> = {};
      if (scenarioBlob && Object.keys(scenarioBlob).length > 0) {
        flat = {};
        for (const [name, val] of Object.entries(scenarioBlob)) {
          if (name.startsWith("_")) continue; // skip audit fields like _mps
          if (Array.isArray(val)) {
            flat[name] = val as number[];
            fans[name] = { central: val as number[] };
          } else if (val && typeof val === "object" && Array.isArray((val as { central?: number[] }).central)) {
            const f = val as ScenarioFan;
            flat[name] = f.central;
            fans[name] = f;
          }
        }
      } else if (scenarioLegacy) {
        for (const [name, arr] of Object.entries(scenarioLegacy)) {
          fans[name] = { central: arr };
        }
      }
      setResults(flat ?? scenarioLegacy ?? null);
      setFanResults(Object.keys(fans).length > 0 ? fans : null);
      setRunHadBuiltins(includeBuiltins);
      setRunId((n) => n + 1);
    } catch {
      // handle error silently
    } finally {
      setRunning(false);
    }
  }

  function addCustom() {
    setScenarios((prev) => [
      ...prev,
      {
        name: customName,
        shock: equityShock,
        volScale,
        drift: driftShift,
        color: pickNextColor(prev.map((s) => s.color)),
      },
    ]);
  }

  async function exportPdf() {
    if (!selectedPortfolio) return;
    const p = (portfolios ?? []).find((x: PortfolioResponse) => String(x.portfolio_id) === selectedPortfolio);
    if (!p) return;
    await reportsApi.quarterly({
      client_name: p.name ?? `Portfolio #${p.portfolio_id}`,
      advisor_name: branding.advisorName,
      firm_name: branding.firmName,
      assets: (p.assets ?? []).map((a) => ({ ticker: a.ticker, weight: a.weight ?? 0 })),
      portfolio_value: portfolioValue,
    });
  }

  // Build comparison chart data
  const comparisonData = scenarios.map((s) => {
    const returnPct = (s.shock + s.drift * 9000) || s.shock;
    const dollarImpact = portfolioValue * (returnPct / 100);
    return {
      name: s.name,
      return: returnPct,
      dollarImpact,
      color: s.color,
    };
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--navy)]">Scenario Builder</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Model custom scenarios and stress-test portfolio outcomes
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Controls Panel */}
        <div className="q-card p-5 space-y-5">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Configuration</h2>

          {/* Portfolio selector */}
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1.5">Portfolio</label>
            <select
              value={selectedPortfolio}
              onChange={(e) => setSelectedPortfolio(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--teal)]"
            >
              <option value="">Select portfolio...</option>
              {(portfolios ?? []).map((p: PortfolioResponse) => (
                <option key={p.portfolio_id} value={String(p.portfolio_id)}>
                  {p.name ?? `Portfolio #${p.portfolio_id}`}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1.5">
              Portfolio Value ($)
            </label>
            <input
              type="number"
              value={portfolioValue}
              onChange={(e) => setPortfolioValue(Number(e.target.value))}
              className="w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--teal)]"
            />
          </div>

          {/* NL scenario translator */}
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
              Describe a scenario
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={nlDescription}
                onChange={(e) => setNlDescription(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && nlDescription.trim() && !translateMutation.isPending) {
                    translateMutation.mutate(nlDescription.trim());
                  }
                }}
                placeholder='e.g. "2008-style crash" or "tech sector selloff"'
                className="flex-1 rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--teal)]"
              />
              <button
                onClick={() => translateMutation.mutate(nlDescription.trim())}
                disabled={!nlDescription.trim() || translateMutation.isPending}
                className="rounded-lg bg-[var(--teal)] px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                {translateMutation.isPending ? "..." : "Translate"}
              </button>
            </div>
            {translateMutation.isError && (() => {
              const err = translateMutation.error as
                | { response?: { data?: { detail?: string }; status?: number }; message?: string }
                | null;
              const detail = err?.response?.data?.detail ?? err?.message ?? "";
              const busy = /UNAVAILABLE|overloaded|high demand|rate[- ]?limit|429|503/i.test(detail);
              return (
                <p className="mt-1 text-xs text-[var(--coral)]">
                  {busy
                    ? "Gemini is busy — try again in a moment."
                    : detail || "Failed to translate. Check that GOOGLE_API_KEY is set on the backend."}
                </p>
              );
            })()}
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">
              Fills the sliders below. You can still adjust before running.
            </p>
          </div>

          {/* Sliders */}
          <div>
            <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">
              Equity Shock: <span className="text-[var(--navy)] font-bold">{equityShock}%</span>
            </label>
            <input
              type="range" min={-30} max={30} step={0.5} value={equityShock}
              onChange={(e) => setEquityShock(Number(e.target.value))}
              className="w-full accent-[var(--teal)]"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">
              Volatility Scale: <span className="text-[var(--navy)] font-bold">{volScale.toFixed(1)}x</span>
            </label>
            <input
              type="range" min={0.5} max={3} step={0.1} value={volScale}
              onChange={(e) => setVolScale(Number(e.target.value))}
              className="w-full accent-[var(--amber)]"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">
              Drift Shift: <span className="text-[var(--navy)] font-bold">{(driftShift * 100).toFixed(2)}%</span>
            </label>
            <input
              type="range" min={-0.005} max={0.005} step={0.0001} value={driftShift}
              onChange={(e) => setDriftShift(Number(e.target.value))}
              className="w-full accent-[var(--blue)]"
            />
          </div>

          <div className="flex gap-2">
            <input
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              placeholder="Scenario name"
              className="flex-1 rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--teal)]"
            />
            <button onClick={addCustom} className="rounded-lg bg-[var(--navy)] px-3 py-2 text-sm font-medium text-white hover:opacity-90">
              Add
            </button>
          </div>

          {/* Active scenarios list */}
          {scenarios.length > 0 && (
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Active Scenarios ({scenarios.length})
              </label>
              {scenarios.map((s, i) => (
                <div
                  key={`${s.name}-${i}`}
                  className="flex items-center justify-between rounded-lg bg-[var(--content-bg)] px-3 py-2"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <div
                      className="h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ backgroundColor: s.color }}
                    />
                    <span className="text-xs font-medium text-[var(--text-primary)] truncate">
                      {s.name}
                    </span>
                  </div>
                  <button
                    onClick={() => setScenarios(scenarios.filter((_, j) => j !== i))}
                    className="shrink-0 ml-2 text-[var(--text-muted)] hover:text-[var(--coral)] transition-colors"
                    title="Remove scenario"
                  >
                    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Server built-in scenarios toggle */}
          <div className="rounded-lg bg-[var(--content-bg)] px-3 py-2.5">
            <label className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={includeBuiltins}
                onChange={(e) => setIncludeBuiltins(e.target.checked)}
                className="h-3.5 w-3.5 accent-[var(--teal)]"
              />
              <span className="text-xs font-medium text-[var(--text-primary)]">
                Include built-in scenarios
              </span>
            </label>
            <p className="mt-1 text-[10px] leading-relaxed text-[var(--text-muted)]">
              Fixed one-knob calibration scenarios the server runs alongside yours: Bull +10% / Bear
              −10% (pure price shocks) and High / Low vol (volatility ×1.25 / ×0.75, no shock). The
              Base reference and the machine-discovered Adversarial worst-case are always included.
            </p>
          </div>

          <div className="pt-2 space-y-2">
            <button
              onClick={runScenarios}
              disabled={!selectedPortfolio || running || scenarios.length === 0}
              className="w-full rounded-lg bg-[var(--teal)] px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {running ? "Running scenarios..." : "Run All Scenarios"}
            </button>
            <button
              onClick={exportPdf}
              disabled={!selectedPortfolio}
              className="w-full rounded-lg border border-[var(--border)] px-4 py-2.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--content-bg)] disabled:opacity-50 transition-colors"
            >
              Export to PDF
            </button>
          </div>
        </div>

        {/* Results */}
        <div className="lg:col-span-2 space-y-4">
          {/* Scenario Templates */}
          <div className="q-card p-5">
            <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Scenario Templates</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {PRESETS.map((p) => (
                <button
                  key={p.name}
                  onClick={() => {
                    setEquityShock(p.shock);
                    setVolScale(p.volScale);
                    setDriftShift(p.drift);
                    setCustomName(p.name);
                  }}
                  className="rounded-lg border border-[var(--border)] px-3 py-2.5 text-left hover:border-[var(--teal)] transition-colors"
                >
                  <span className="text-xs font-semibold text-[var(--text-primary)]">{p.name}</span>
                  <span className="mt-0.5 block text-[10px] text-[var(--text-muted)]">
                    Shock: {p.shock}% | Vol: {p.volScale}x
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* AI Executive Summary */}
          {results && comparisonData.length > 0 && (
            <ScenarioSummaryCard
              key={`summary-${runId}`}
              portfolioName={
                (portfolios ?? []).find((p: PortfolioResponse) => String(p.portfolio_id) === selectedPortfolio)?.name
                  ?? `Portfolio #${selectedPortfolio}`
              }
              portfolioValue={portfolioValue}
              scenarios={comparisonData.map((c, i) => ({
                name: c.name,
                shock_pct: scenarios[i]?.shock,
                vol_scale: scenarios[i]?.volScale,
                drift_shift: scenarios[i]?.drift,
                return_pct: c.return,
                dollar_impact: c.dollarImpact,
              }))}
            />
          )}

          {/* AI per-scenario explainer — grounded in the simulated fans */}
          {fanResults && Object.keys(fanResults).length > 0 && (
            <ScenarioExplainerCard
              key={`explainer-${runId}`}
              portfolioName={
                (portfolios ?? []).find((p: PortfolioResponse) => String(p.portfolio_id) === selectedPortfolio)?.name
                  ?? `Portfolio #${selectedPortfolio}`
              }
              portfolioValue={portfolioValue}
              fans={fanResults}
              scenarios={scenarios}
            />
          )}

          {/* Comparison Chart */}
          <div className="q-card p-5">
            <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
              Scenario Comparison — Portfolio Impact
            </h2>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={comparisonData} layout="vertical" margin={{ left: 100, right: 40 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F3" />
                <XAxis type="number" tick={{ fontSize: 10, fill: "#8B95A2" }} tickFormatter={(v) => `${v > 0 ? "+" : ""}${v}%`} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: "#5A6270" }} width={95} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
                  formatter={(value) => [`${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(1)}%`, "Return"]}
                />
                <Bar dataKey="return" radius={[0, 4, 4, 0]}>
                  {comparisonData.map((entry, i) => (
                    <Cell key={i} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* MPS-copula scenario path fans */}
          {fanResults && forecastDates.length > 0 && (
            <div className="q-card p-5">
              <div className="flex items-center justify-between mb-1">
                <h2 className="text-sm font-semibold text-[var(--text-primary)]">
                  Scenario Paths — MPS-copula fan
                </h2>
                <DownloadCsvButton
                  filename="scenario-paths"
                  disabled={forecastDates.length === 0}
                  build={() => {
                    const keys = Object.keys(fanResults).filter((k) => !k.startsWith("_"));
                    const headers = ["date"];
                    for (const k of keys) {
                      headers.push(`${k}_central`, `${k}_lower_1s`, `${k}_upper_1s`, `${k}_lower_2s`, `${k}_upper_2s`);
                    }
                    const rows: CsvCell[][] = [];
                    for (let i = 0; i < forecastDates.length; i++) {
                      const row: CsvCell[] = [forecastDates[i]];
                      for (const k of keys) {
                        const fan = fanResults[k] as ScenarioFan | undefined;
                        row.push(
                          fan?.central?.[i] ?? null,
                          fan?.lower_1s?.[i] ?? null,
                          fan?.upper_1s?.[i] ?? null,
                          fan?.lower_2s?.[i] ?? null,
                          fan?.upper_2s?.[i] ?? null,
                        );
                      }
                      rows.push(row);
                    }
                    return { headers, rows };
                  }}
                />
              </div>
              <p className="text-xs text-[var(--text-muted)] mb-1">
                All scenario centrals are drawn by default. Click a scenario to bring its ±1σ and ±2σ bands forward
                (the others fade to 30%). Bands capture non-Gaussian cross-asset dependence sampled from the MPS.
              </p>
              <p className="text-[10px] text-[var(--text-muted)] mb-4">
                Server-added: <span className="font-medium">Base</span> (neutral reference)
                {fanResults["worst_case_cvar"] ? (
                  <> · <span className="font-medium">Adversarial worst-case</span> (machine-searched shock combination)</>
                ) : null}
                {runHadBuiltins ? (
                  <> · Built-ins: <span className="font-medium">Bull +10% / Bear −10%</span> (pure price shocks),{" "}
                  <span className="font-medium">High / Low vol</span> (pure volatility regimes)</>
                ) : null}
                . Scenarios you configured keep the names you gave them.
              </p>
              <ScenarioPathsChart
                fans={fanResults}
                dates={forecastDates}
                scenarios={scenarios}
                height={360}
              />
            </div>
          )}

          {/* Dollar Impact */}
          <div className="q-card p-5">
            <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Dollar Impact</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {comparisonData.map((s, i) => (
                <div key={`${s.name}-${i}`} className="rounded-lg bg-[var(--content-bg)] px-4 py-3">
                  <span className="text-xs font-semibold text-[var(--text-muted)]">{s.name}</span>
                  <div className={`text-lg font-bold ${s.dollarImpact >= 0 ? "text-[var(--positive)]" : "text-[var(--negative)]"}`}>
                    {s.dollarImpact >= 0 ? "+" : ""}${Math.abs(s.dollarImpact).toLocaleString("en-US", { maximumFractionDigits: 0 })}
                  </div>
                  <span className="text-[10px] text-[var(--text-muted)]">
                    {s.return >= 0 ? "+" : ""}{s.return.toFixed(1)}% return
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
