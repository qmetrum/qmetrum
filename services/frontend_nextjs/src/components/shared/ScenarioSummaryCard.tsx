"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { agentsApi } from "@/lib/api";
import { SourceDataPanel } from "@/components/shared/SourceDataPanel";

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
    <div className="q-card p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">AI Executive Summary</h2>
          <p className="text-xs text-[var(--text-muted)]">
            Short narrative comparing the scenarios you just ran.
          </p>
        </div>
        <button
          onClick={() => mutation.mutate()}
          disabled={disabled || mutation.isPending}
          className="text-xs font-medium bg-[var(--navy)] text-white px-3 py-1.5 rounded-lg hover:opacity-90 disabled:opacity-50"
        >
          {mutation.isPending
            ? "Summarizing..."
            : summary
              ? "Re-summarize"
              : "Summarize"}
        </button>
      </div>

      {errorMessage && <p className="text-xs text-[var(--coral)] mb-2">{errorMessage}</p>}

      {summary ? (
        <div>
          <p className="text-sm text-[var(--text-primary)] leading-relaxed whitespace-pre-line">
            {summary}
          </p>
          {cached && (
            <p className="text-[11px] text-[var(--text-muted)] mt-2">Served from cache</p>
          )}
          {sourceData && <SourceDataPanel data={sourceData} />}
        </div>
      ) : !mutation.isPending && !errorMessage ? (
        <p className="text-sm text-[var(--text-muted)]">
          {disabled
            ? "Run a scenario first, then come back for the summary."
            : <>Click <span className="font-medium">Summarize</span> to interpret the results.</>}
        </p>
      ) : null}
    </div>
  );
}
