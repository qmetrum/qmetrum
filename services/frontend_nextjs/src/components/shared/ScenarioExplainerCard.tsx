"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { agentsApi, type ScenarioExplanation, type ScenarioFan } from "@/lib/api";
import { AgentCard } from "@/components/shared/AgentCard";
import { Markdown } from "@/components/shared/Markdown";
import {
  ADVERSARIAL_COLOR,
  DEFAULT_COLOR,
  DISPLAY_NAMES,
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
  const [explanations, setExplanations] = useState<ScenarioExplanation[] | null>(null);
  const [cached, setCached] = useState<boolean | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [sourceData, setSourceData] = useState<Record<string, unknown> | null>(null);

  const specByName = new Map(scenarios.map((s) => [s.name, s]));
  const colourFor = (name: string) =>
    name === "worst_case_cvar" ? ADVERSARIAL_COLOR : specByName.get(name)?.color ?? DEFAULT_COLOR;

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
      title="AI Scenario Explainer"
      subtitle={
        disabled
          ? "Run scenarios first, then generate a description of each one."
          : eligible.length > MAX_SCENARIOS
            ? `What each scenario models and shows — explaining ${batch.length} of ${eligible.length} scenarios (limit ${MAX_SCENARIOS}).`
            : "What each scenario models and what its simulated paths show."
      }
      onRun={() => mutation.mutate()}
      isPending={mutation.isPending}
      runLabel="Explain each"
      disabled={disabled}
      error={errorMessage}
      sourceData={sourceData}
      cached={cached}
      model={model}
    >
      {explanations && (
        <div className="space-y-4">
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
