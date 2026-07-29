"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useBranding } from "@/components/providers/BrandingProvider";
import {
  agentsApi,
  forecastJobApi,
  portfolioApi,
  portfolioListApi,
  reportsApi,
  scenarioSessionApi,
  type PortfolioResponse,
  type ForecastScenarioInput,
  type ScenarioFan,
} from "@/lib/api";
import { MetricCard } from "@/components/shared/MetricCard";
import {
  ADVERSARIAL_COLOR,
  DEFAULT_COLOR,
  DISPLAY_NAMES,
  ScenarioPathsChart,
} from "@/components/charts/ScenarioPathsChart";
import { ScenarioExplainerCard, buildScenarioItems } from "@/components/shared/ScenarioExplainerCard";
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

type ScenarioSpec = { name: string; shock: number; volScale: number; drift: number; color: string };

// The user's scenario set (presets they kept + customs they added) persists
// across refreshes. Scenario definitions are shock specs independent of any
// portfolio, so one global list is correct.
const SCENARIOS_KEY = "qsight.scenarios.v1";
// A run's produced results, and any in-progress job, persist locally so leaving
// and returning to the page (or a refresh) restores the charts and resumes a
// running computation.
const RUN_KEY = "qsight.scenarioRun.v1";
const JOB_KEY = "qsight.scenarioJob.v1";

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
  const [runError, setRunError] = useState<string | null>(null);
  // Non-error "still computing / come back" state, distinct from a failure.
  const [runNotice, setRunNotice] = useState<string | null>(null);
  const [runProgress, setRunProgress] = useState<{ elapsed: number; progress: number | null } | null>(null);

  // Persist the scenario set across refreshes. Hydrate from localStorage on
  // mount (server + first client render use PRESETS to avoid a hydration
  // mismatch); only start saving AFTER hydration so we never clobber a stored
  // set with the default PRESETS. An empty stored array is respected (the user
  // may have deleted every preset on purpose).
  const scenariosLoaded = useRef(false);
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(SCENARIOS_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as ScenarioSpec[];
        if (Array.isArray(parsed)) setScenarios(parsed);
      }
    } catch {
      /* corrupt/unavailable storage: fall back to PRESETS already in state */
    }
    scenariosLoaded.current = true;
  }, []);
  useEffect(() => {
    if (!scenariosLoaded.current) return;
    try {
      window.localStorage.setItem(SCENARIOS_KEY, JSON.stringify(scenarios));
    } catch {
      /* storage full / disabled: persistence just won't happen */
    }
  }, [scenarios]);

  // Restore a previous run's results (and resume any in-progress job) on mount,
  // so leaving and returning to the page shows the charts / "still computing".
  const runLoaded = useRef(false);
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(RUN_KEY);
      if (raw) {
        const s = JSON.parse(raw);
        if (s.portfolio) setSelectedPortfolio(s.portfolio);
        if (typeof s.portfolioValue === "number") setPortfolioValue(s.portfolioValue);
        if (s.results) setResults(s.results);
        if (s.fanResults) setFanResults(s.fanResults);
        if (Array.isArray(s.forecastDates)) setForecastDates(s.forecastDates);
        if (typeof s.runHadBuiltins === "boolean") setRunHadBuiltins(s.runHadBuiltins);
        if (typeof s.runId === "number") setRunId(s.runId);
      }
    } catch { /* ignore */ }
    runLoaded.current = true;
    try {
      const jraw = window.localStorage.getItem(JOB_KEY);
      if (jraw) {
        const jb = JSON.parse(jraw);
        if (jb?.jobId) {
          if (jb.portfolio) setSelectedPortfolio(jb.portfolio);
          pollJob(jb.jobId, jb.t0 ?? Date.now(), jb.builtins ?? true);
        }
      }
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Persist the produced results so a return/refresh restores them.
  useEffect(() => {
    if (!runLoaded.current) return;
    try {
      if (fanResults || results) {
        window.localStorage.setItem(RUN_KEY, JSON.stringify({
          portfolio: selectedPortfolio, portfolioValue, results, fanResults,
          forecastDates, runHadBuiltins, runId,
        }));
      } else {
        window.localStorage.removeItem(RUN_KEY);
      }
    } catch { /* ignore */ }
  }, [results, fanResults, forecastDates, runHadBuiltins, selectedPortfolio, portfolioValue, runId]);

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

  const writeJob = (v: unknown) => {
    try { window.localStorage.setItem(JOB_KEY, JSON.stringify(v)); } catch { /* ignore */ }
  };
  const clearJob = () => {
    try { window.localStorage.removeItem(JOB_KEY); } catch { /* ignore */ }
  };

  // Parse a portfolio forecast result into the chart state. Throws if empty.
  function applyForecastResult(fc: unknown, builtinsAtRun: boolean) {
    const summary = (fc as Record<string, unknown>)?.portfolio_summary as Record<string, unknown> | undefined;
    const scenarioBlob = summary?.scenarios as Record<string, unknown> | undefined;
    const scenarioLegacy = summary?.scenarios_legacy as Record<string, number[]> | undefined;
    const dates = (summary?.forecast_dates as string[] | undefined) ?? [];
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
    if (!flat && !scenarioLegacy && Object.keys(fans).length === 0) {
      throw new Error("The forecast returned no scenario data");
    }
    setForecastDates(dates);
    setResults(flat ?? scenarioLegacy ?? null);
    setFanResults(Object.keys(fans).length > 0 ? fans : null);
    setRunHadBuiltins(builtinsAtRun);
    setRunId((n) => n + 1);
  }

  // Poll an async job to completion and apply its result. Reused for a fresh
  // run and for resuming an in-progress job after navigation/refresh.
  async function pollJob(jobId: string, t0: number, builtinsAtRun: boolean) {
    setRunning(true);
    setRunError(null);
    setRunNotice(null);
    let pollFails = 0;
    try {
      for (;;) {
        await new Promise((r) => setTimeout(r, 3000));
        let j: Awaited<ReturnType<typeof forecastJobApi.get>>;
        try {
          j = await forecastJobApi.get(jobId);
          pollFails = 0;
        } catch {
          // Transient blip: tolerate a few; keep the job marker so a later
          // remount can resume rather than losing a healthy computation.
          if (++pollFails < 8) continue;
          setRunNotice("Lost the connection while your scenarios were computing. The job keeps running on the server; reopen this page shortly to pick up the result.");
          setRunning(false);
          return;
        }
        setRunProgress({
          elapsed: Math.round((Date.now() - t0) / 1000),
          progress: typeof j.job?.progress === "number" ? j.job.progress : null,
        });
        if (j.job?.status === "completed") {
          try {
            applyForecastResult(j.result ?? {}, builtinsAtRun);
          } catch (e) {
            setRunError((e as Error).message ?? "Scenario run returned no data");
          }
          clearJob();
          setRunning(false);
          setRunProgress(null);
          return;
        }
        if (j.job?.status === "failed") {
          setRunError(j.job?.error_message || j.error || "Scenario computation failed on the server");
          clearJob();
          setRunning(false);
          return;
        }
        // Long-running is NOT an error: the job keeps computing server-side and
        // caches its result. Stop watching but KEEP the job marker so returning
        // to the page resumes it.
        if (Date.now() - t0 > 45 * 60_000) {
          setRunNotice("This is taking longer than usual, so we have stopped watching here. The calculation keeps running on the server; reopen this page in a few minutes to pick up the result.");
          setRunning(false);
          setRunProgress(null);
          return;
        }
      }
    } catch (e) {
      setRunError((e as Error).message ?? "Scenario run failed");
      setRunning(false);
      setRunProgress(null);
    }
  }

  async function runScenarios() {
    if (!selectedPortfolio) return;
    const builtinsAtRun = includeBuiltins;
    setRunning(true);
    setRunError(null);
    setRunNotice(null);
    setRunProgress(null);
    const t0 = Date.now();
    try {
      const scenarioInputs: ForecastScenarioInput[] = scenarios.map((s) => ({
        name: s.name,
        initial_shock_pct: s.shock / 100,
        return_scale: s.volScale,
        drift_shift: s.drift,
      }));
      // Async job: cold computes take many minutes; the queue dedups by request
      // hash so a re-run re-attaches instead of stacking another compute.
      const res = await portfolioApi.forecast(
        selectedPortfolio,
        { horizon_days: 90, scenarios: scenarioInputs, include_builtin_scenarios: includeBuiltins },
        { async_mode: true }
      );
      if (res.mode === "job" && res.job_id) {
        writeJob({ jobId: res.job_id, t0, portfolio: selectedPortfolio, builtins: builtinsAtRun });
        await pollJob(res.job_id, t0, builtinsAtRun);
      } else {
        applyForecastResult(res.result ?? res, builtinsAtRun);
        setRunning(false);
      }
    } catch (e) {
      const err = e as { response?: { data?: { detail?: unknown } }; message?: string };
      const detail = err.response?.data?.detail;
      setRunError(typeof detail === "string" ? detail : err.message ?? "Scenario run failed");
      setRunning(false);
      setRunProgress(null);
    }
  }

  // ── Saved scenario sessions (server-side; survive logout/login) ──
  const qc = useQueryClient();
  const [showSessions, setShowSessions] = useState(false);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const { data: sessions } = useQuery({
    queryKey: ["scenario-sessions"],
    queryFn: scenarioSessionApi.list,
  });
  const saveSession = useMutation({
    mutationFn: (name: string) =>
      scenarioSessionApi.save({
        name,
        portfolio_id: selectedPortfolio || null,
        portfolio_value: portfolioValue,
        scenarios: { items: scenarios },
        results: { results, fanResults, forecastDates, runHadBuiltins },
      }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["scenario-sessions"] });
      setSavedMsg(`Saved “${s.name}”.`);
      setTimeout(() => setSavedMsg(null), 4000);
    },
  });
  const deleteSession = useMutation({
    mutationFn: (id: number) => scenarioSessionApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scenario-sessions"] }),
  });

  async function loadSession(id: number) {
    try {
      const s = await scenarioSessionApi.get(id);
      const items = ((s.scenarios as { items?: typeof scenarios })?.items) ?? [];
      if (items.length) setScenarios(items);
      if (s.portfolio_id) setSelectedPortfolio(s.portfolio_id);
      if (typeof s.portfolio_value === "number") setPortfolioValue(s.portfolio_value);
      const r = (s.results ?? {}) as {
        results?: Record<string, number[]> | null;
        fanResults?: Record<string, ScenarioFan> | null;
        forecastDates?: string[];
        runHadBuiltins?: boolean;
      };
      if (r.results || r.fanResults) {
        setResults(r.results ?? null);
        setFanResults(r.fanResults ?? null);
        setForecastDates(r.forecastDates ?? []);
        setRunHadBuiltins(r.runHadBuiltins ?? true);
        setRunId((n) => n + 1);
      }
      setShowSessions(false);
    } catch {
      setRunError("Could not load that saved session.");
    }
  }

  function onSaveSession() {
    const name = window.prompt("Name this scenario session:", `Session ${new Date().toLocaleDateString()}`);
    if (name && name.trim()) saveSession.mutate(name.trim());
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

  // Re-add a preset template to the active set (no-op if already present).
  function addPreset(p: ScenarioSpec) {
    setScenarios((prev) => {
      if (prev.some((s) => s.name === p.name)) return prev;
      const used = prev.map((s) => s.color);
      const color = used.includes(p.color) ? pickNextColor(used) : p.color;
      return [...prev, { ...p, color }];
    });
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
      // Ground the PDF's scenario section in the run on screen; without a run
      // the report omits the section instead of fabricating one.
      ...(fanResults ? { scenarios: buildScenarioItems(fanResults, scenarios) } : {}),
    });
  }

  // Build comparison chart data. After a run this is grounded in the actual
  // simulated fans — median (p50) end level per scenario vs the base
  // scenario's start — the same source as the paths chart, so it reflects the
  // selected portfolio. Before a run it falls back to a knob-based estimate.
  const specByName = new Map(scenarios.map((s) => [s.name, s]));
  const simulated = fanResults != null;
  // Which scenarios the user has hidden from the comparison chart / tiles.
  const [excludedKeys, setExcludedKeys] = useState<Set<string>>(new Set());
  function toggleExcluded(key: string) {
    setExcludedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const comparisonData = simulated
    ? Object.entries(fanResults)
        .filter(
          ([k, v]) =>
            !k.startsWith("_") &&
            v != null &&
            typeof v === "object" &&
            Array.isArray((v as ScenarioFan).central) &&
            (v as ScenarioFan).central.length > 0,
        )
        .map(([key, v]) => {
          const fan = v as ScenarioFan;
          const baseStart =
            (fanResults["base"] as ScenarioFan | undefined)?.central?.[0] ?? fan.central[0];
          const returnPct = baseStart
            ? (fan.central[fan.central.length - 1] / baseStart - 1) * 100
            : 0;
          return {
            key,
            name: DISPLAY_NAMES[key] ?? key,
            return: returnPct,
            dollarImpact: portfolioValue * (returnPct / 100),
            color:
              key === "worst_case_cvar"
                ? ADVERSARIAL_COLOR
                : specByName.get(key)?.color ?? DEFAULT_COLOR,
          };
        })
    : scenarios.map((s) => {
        const returnPct = (s.shock + s.drift * 9000) || s.shock;
        return {
          key: s.name,
          name: s.name,
          return: returnPct,
          dollarImpact: portfolioValue * (returnPct / 100),
          color: s.color,
        };
      });

  const shownComparison = comparisonData.filter((c) => !excludedKeys.has(c.key));

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[var(--navy)]">Scenario Builder</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Model custom scenarios and stress-test portfolio outcomes
          </p>
        </div>
        <div className="relative flex items-center gap-2">
          <button
            onClick={() => setShowSessions((v) => !v)}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--content-bg)] transition-colors"
          >
            Saved sessions{sessions && sessions.length > 0 ? ` (${sessions.length})` : ""}
          </button>
          <button
            onClick={onSaveSession}
            disabled={saveSession.isPending || (!results && !fanResults && scenarios.length === 0)}
            className="rounded-lg bg-[var(--teal)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
            title="Save this scenario set and its results to your account"
          >
            {saveSession.isPending ? "Saving…" : "Save session"}
          </button>
          {showSessions && (
            <div className="absolute right-0 top-full z-40 mt-2 w-80 rounded-lg border border-[var(--border)] bg-white shadow-lg overflow-hidden">
              <div className="border-b border-[var(--border)] px-4 py-2.5 text-sm font-semibold text-[var(--text-primary)]">
                Saved sessions
              </div>
              {(sessions ?? []).length === 0 ? (
                <div className="px-4 py-6 text-center text-xs text-[var(--text-muted)]">
                  No saved sessions yet. Run scenarios, then “Save session”.
                </div>
              ) : (
                <ul className="max-h-80 overflow-y-auto">
                  {(sessions ?? []).map((s) => (
                    <li key={s.id} className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-2.5 last:border-b-0 hover:bg-[var(--content-bg)]">
                      <button onClick={() => loadSession(s.id)} className="min-w-0 flex-1 text-left">
                        <span className="block truncate text-sm font-medium text-[var(--navy)]">{s.name}</span>
                        <span className="block text-[10px] text-[var(--text-muted)]">
                          {s.n_scenarios} scenarios{s.has_results ? " · results saved" : ""}
                          {s.updated_at ? ` · ${new Date(s.updated_at).toLocaleDateString()}` : ""}
                        </span>
                      </button>
                      <button
                        onClick={() => deleteSession.mutate(s.id)}
                        className="shrink-0 text-[var(--text-muted)] hover:text-[var(--coral)]"
                        title="Delete"
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>

      {savedMsg && (
        <div className="rounded-lg bg-[var(--teal-light)] px-4 py-2 text-sm text-[var(--text-primary)]">
          {savedMsg}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Controls Panel */}
        <div className="q-card p-5 space-y-5">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Configuration</h2>

          {/* Portfolio selector */}
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1.5">Portfolio</label>
            <select
              value={selectedPortfolio}
              onChange={(e) => {
                setSelectedPortfolio(e.target.value);
                // Results are per-portfolio — never show another portfolio's
                // simulation next to the new selection.
                setResults(null);
                setFanResults(null);
              }}
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
              {running
                ? runProgress
                  ? `Computing… ${Math.floor(runProgress.elapsed / 60)}:${String(runProgress.elapsed % 60).padStart(2, "0")}${
                      runProgress.progress != null ? ` · ${Math.round(runProgress.progress * 100)}%` : ""
                    }`
                  : "Running scenarios..."
                : "Run All Scenarios"}
            </button>
            {running && runProgress && (
              <p className="text-[10px] text-[var(--text-muted)]">
                First run after new market data retrains asset forecasts and can take 20-30
                minutes for larger portfolios; reruns are fast. The job keeps running
                server-side even if you leave — hitting Run later re-attaches to it.
              </p>
            )}
            {runError && !running && (
              <div className="rounded-lg bg-[var(--coral-light)] px-3 py-2 text-xs text-[var(--coral)]">
                Scenario run failed: {runError}
              </div>
            )}
            {runNotice && !running && (
              <div className="rounded-lg bg-[var(--amber-light)] px-3 py-2 text-xs text-[var(--text-secondary)]">
                {runNotice}
              </div>
            )}
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
          {/* Scenario Templates — click to add a preset back to your set */}
          <div className="q-card p-5">
            <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-1">Scenario Templates</h2>
            <p className="text-[10px] text-[var(--text-muted)] mb-3">
              Click a template to add it to your active scenarios. Your set (customs and any
              templates you keep or remove) is saved and restored on your next visit.
            </p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {PRESETS.map((p) => {
                const active = scenarios.some((s) => s.name === p.name);
                return (
                  <button
                    key={p.name}
                    onClick={() => addPreset(p)}
                    disabled={active}
                    className={`rounded-lg border px-3 py-2.5 text-left transition-colors ${
                      active
                        ? "border-[var(--border)] opacity-50 cursor-default"
                        : "border-[var(--border)] hover:border-[var(--teal)]"
                    }`}
                  >
                    <span className="flex items-center gap-1 text-xs font-semibold text-[var(--text-primary)]">
                      {p.name}
                      {active && <span className="text-[9px] font-normal text-[var(--teal)]">· added</span>}
                    </span>
                    <span className="mt-0.5 block text-[10px] text-[var(--text-muted)]">
                      Shock: {p.shock}% | Vol: {p.volScale}x
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Comparison Chart */}
          <div className="q-card p-5">
            <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-1">
              Scenario Comparison — Portfolio Impact
            </h2>
            <p className="text-[10px] text-[var(--text-muted)] mb-2">
              {simulated
                ? "Simulated: median (p50) end level per scenario vs the base scenario's start, from the MPS-copula paths for the selected portfolio."
                : "Estimated from scenario knobs only — run scenarios to get simulated results for the selected portfolio."}
            </p>
            {/* Include/exclude scenarios from the chart and tiles */}
            {comparisonData.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {comparisonData.map((c) => {
                  const on = !excludedKeys.has(c.key);
                  return (
                    <button
                      key={c.key}
                      onClick={() => toggleExcluded(c.key)}
                      className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                        on
                          ? "border-[var(--border)] text-[var(--text-primary)]"
                          : "border-transparent bg-[var(--content-bg)] text-[var(--text-muted)] line-through"
                      }`}
                      title={on ? "Click to hide from the chart" : "Click to show"}
                    >
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ backgroundColor: on ? c.color : "var(--text-muted)" }}
                      />
                      {c.name}
                    </button>
                  );
                })}
              </div>
            )}
            {shownComparison.length === 0 ? (
              <div className="py-16 text-center text-xs text-[var(--text-muted)]">
                All scenarios hidden. Click a chip above to show them.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(180, shownComparison.length * 44)}>
                <BarChart data={shownComparison} layout="vertical" margin={{ left: 100, right: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F3" />
                  <XAxis type="number" tick={{ fontSize: 10, fill: "#8B95A2" }} tickFormatter={(v) => `${v > 0 ? "+" : ""}${v}%`} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: "#5A6270" }} width={95} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
                    formatter={(value) => [`${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(1)}%`, "Return"]}
                  />
                  <Bar dataKey="return" radius={[0, 4, 4, 0]}>
                    {shownComparison.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
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
            <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-1">Dollar Impact</h2>
            <p className="text-[10px] text-[var(--text-muted)] mb-3">
              {simulated
                ? "Simulated median outcome × portfolio value."
                : "Knob-based estimate × portfolio value — run scenarios to simulate."}
            </p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {shownComparison.map((s, i) => (
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

          {/* AI Scenario Analysis — executive summary + per-scenario breakdown,
              one batched call grounded in the simulated fans */}
          {fanResults && Object.keys(fanResults).length > 0 && (
            <ScenarioExplainerCard
              key={`analysis-${runId}`}
              portfolioName={
                (portfolios ?? []).find((p: PortfolioResponse) => String(p.portfolio_id) === selectedPortfolio)?.name
                  ?? `Portfolio #${selectedPortfolio}`
              }
              portfolioValue={portfolioValue}
              fans={fanResults}
              scenarios={scenarios}
            />
          )}
        </div>
      </div>
    </div>
  );
}
