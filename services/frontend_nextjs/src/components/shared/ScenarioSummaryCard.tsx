"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { agentsApi } from "@/lib/api";
import { AgentCard } from "@/components/shared/AgentCard";

type ScenarioRow = {
  name: string;
  shock_pct?: number;
  vol_scale?: number;
  drift_shift?: number;
  return_pct: number;
  dollar_impact: number;
};

type Props = {
  portfolioName: string;
  portfolioValue: number;
  scenarios: ScenarioRow[];
};

export function ScenarioSummaryCard({ portfolioName, portfolioValue, scenarios }: Props) {
  const [summary, setSummary] = useState<string | null>(null);
  const [cached, setCached] = useState<boolean | null>(null);
  const [sourceData, setSourceData] = useState<Record<string, unknown> | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      agentsApi.summarizeScenarios({
        portfolio_name: portfolioName,
        portfolio_value: portfolioValue,
        scenarios,
      }),
    onSuccess: (res) => {
      setSummary(res.summary);
      setCached(res.cached);
      setSourceData(res.source_data);
    },
  });

  const apiError = mutation.error as { response?: { data?: { detail?: string } }; message?: string } | null;
  const errorMessage = apiError
    ? apiError.response?.data?.detail ?? apiError.message ?? "Failed to summarize"
    : null;

  const disabled = scenarios.length === 0;

  return (
    <AgentCard
      title="AI Executive Summary"
      subtitle={
        disabled
          ? "Run a scenario first, then summarize the results."
          : "Short narrative comparing the scenarios you just ran."
      }
      onRun={() => mutation.mutate()}
      isPending={mutation.isPending}
      runLabel="Summarize"
      disabled={disabled}
      markdown={summary}
      error={errorMessage}
      sourceData={sourceData}
      cached={cached}
    />
  );
}
