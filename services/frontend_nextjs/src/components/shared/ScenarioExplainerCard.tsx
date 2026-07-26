"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { agentsApi, type ScenarioExplanation, type ScenarioFan } from "@/lib/api";
import { AgentCard } from "@/components/shared/AgentCard";
import { Markdown } from "@/components/shared/Markdown";
import {
  ADVERSARIAL_COLOR,
  AUTO_SCENARIO_INFO,
  BUILTIN_SCENARIO_INFO,
  DEFAULT_COLOR,
  DISPLAY_NAMES,
  scenarioOrigin,
} from "@/components/charts/ScenarioPathsChart";

type ScenarioSpec = { name: string; shock: number; volScale: number; drift: number; color: string };

type Props = {
  portfolioName: string;
  portfolioValue: number;
  /** Per-scenario fans from the last run, keyed by name ("_"-prefixed audit keys skipped). */
  fans: Record<string, ScenarioFan | unknown>;
  /** Client-side scenario specs — supply knobs + colours for user-defined scenarios. */
  scenarios: ScenarioSpec[];
};

// Backend caps the batch at 12 scenarios per request.
const MAX_SCENARIOS = 12;

type FanWithExtras = ScenarioFan & {
  p5?: number[];
  p95?: number[];
  _discovery?: Record<string, unknown>;
};

export function ScenarioExplainerCard({ portfolioName, portfolioValue, fans, scenarios }: Props) {
  const [summary, setSummary] = useState<string | null>(null);
  const [explanations, setExplanations] = useState<ScenarioExplanation[] | null>(null);
  const [cached, setCached] = useState<boolean | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [sourceData, setSourceData] = useState<Record<string, unknown> | null>(null);

  const specByName = new Map(scenarios.map((s) => [s.name, s]));
  const colourFor = (name: string) =>
    name === "worst_case_cvar" ? ADVERSARIAL_COLOR : specByName.get(name)?.color ?? DEFAULT_COLOR;
  // A name the user configured is THEIR scenario even if it collides with a
  // reserved server name (customs override builtins by name server-side).
  const originFor = (name: string) => (specByName.has(name) ? null : scenarioOrigin(name));

  const eligible = Object.entries(fans).filter(
    ([k, v]) =>
      !k.startsWith("_") &&
      v != null &&
      typeof v === "object" &&
      Array.isArray((v as ScenarioFan).central) &&
      (v as ScenarioFan).central.length >= 2,
  );

  // When capping, always keep the server-discovered adversarial scenario —
  // it is the one with per-asset attribution, and the server appends it LAST
  // so a plain slice would drop exactly that one first.
  const batch =
    eligible.length <= MAX_SCENARIOS
      ? eligible
      : [
          ...eligible
            .filter(([k]) => k !== "worst_case_cvar")
            .slice(0, MAX_SCENARIOS - (eligible.some(([k]) => k === "worst_case_cvar") ? 1 : 0)),
          ...eligible.filter(([k]) => k === "worst_case_cvar"),
        ];

  const buildPayload = () => ({
    portfolio_name: portfolioName.slice(0, 200),
    portfolio_value: portfolioValue,
    scenarios: batch.map(([name, v]) => {
      const fan = v as FanWithExtras;
      const spec = specByName.get(name);
      return {
        name: name.slice(0, 200),
        ...(spec
          ? { shock_pct: spec.shock, vol_scale: spec.volScale, drift_shift: spec.drift }
          : {}),
        fan: {
          central: fan.central,
          lower_1s: fan.lower_1s,
          upper_1s: fan.upper_1s,
          lower_2s: fan.lower_2s,
          upper_2s: fan.upper_2s,
          p5: fan.p5,
          p95: fan.p95,
        },
        ...(fan._discovery ? { discovery: fan._discovery } : {}),
      };
    }),
  });

  const mutation = useMutation({
    mutationFn: () => agentsApi.explainScenarios(buildPayload()),
    onSuccess: (res) => {
      setSummary(res.summary || null);
      setExplanations(res.explanations);
      setCached(res.cached);
      setModel(res.model);
      setSourceData(res.source_data);
    },
  });

  // FastAPI 422s carry a LIST in `detail` — never render a non-string in JSX.
  const apiError = mutation.error as { response?: { data?: { detail?: unknown } }; message?: string } | null;
  const detail = apiError?.response?.data?.detail;
  const errorMessage = apiError
    ? typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? String((detail[0] as { msg?: string } | undefined)?.msg ?? "Invalid request")
        : apiError.message ?? "Failed to explain scenarios"
    : null;

  const disabled = eligible.length === 0;

  return (
    <AgentCard
      title="AI Scenario Analysis"
      subtitle={
        disabled
          ? "Run scenarios first, then generate the analysis."
          : eligible.length > MAX_SCENARIOS
            ? `Executive summary plus what each scenario shows — analysing ${batch.length} of ${eligible.length} scenarios (limit ${MAX_SCENARIOS}).`
            : "Executive summary plus what each scenario models and shows, grounded in the simulated paths."
      }
      onRun={() => mutation.mutate()}
      isPending={mutation.isPending}
      runLabel="Analyse"
      disabled={disabled}
      markdown={summary}
      error={errorMessage}
      sourceData={sourceData}
      cached={cached}
      model={model}
    >
      {explanations && (
        <div className="space-y-4">
          <p className="border-t border-[var(--card-border)] pt-3 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Per-scenario breakdown
          </p>
          {explanations.map((e, i) => (
            <div key={`${e.name}-${i}`} className="border-l-2 pl-3" style={{ borderColor: colourFor(e.name) }}>
              <div className="flex items-center gap-2">
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: colourFor(e.name) }}
                />
                <span className="text-xs font-semibold text-[var(--text-primary)]">
                  {DISPLAY_NAMES[e.name] ?? e.name}
                </span>
                {originFor(e.name) && (
                  <span
                    className="rounded-full bg-[var(--content-bg)] px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-[var(--text-muted)]"
                    title={BUILTIN_SCENARIO_INFO[e.name] ?? AUTO_SCENARIO_INFO[e.name]}
                  >
                    {originFor(e.name)}
                  </span>
                )}
              </div>
              <p className="mt-1 text-xs font-medium text-[var(--text-secondary)]">{e.headline}</p>
              <div className="mt-1">
                <Markdown>{e.narrative}</Markdown>
              </div>
            </div>
          ))}
        </div>
      )}
    </AgentCard>
  );
}
