"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { agentsApi } from "@/lib/api";
import { SourceDataPanel } from "@/components/shared/SourceDataPanel";

type Metrics = Record<string, number | null | undefined>;

type Props = {
  portfolioId: number | string;
  metrics: Metrics;
  regime: string;
  horizonDays: number;
  snapshotHash?: string;
  disabled?: boolean;
};

export function PortfolioCommentaryCard({
  portfolioId,
  metrics,
  regime,
  horizonDays,
  snapshotHash,
  disabled,
}: Props) {
  const [commentary, setCommentary] = useState<string | null>(null);
  const [cached, setCached] = useState<boolean | null>(null);
  const [sourceData, setSourceData] = useState<Record<string, unknown> | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      agentsApi.portfolioCommentary(portfolioId, {
        metrics,
        regime,
        horizon_days: horizonDays,
        snapshot_hash: snapshotHash,
      }),
    onSuccess: (res) => {
      setCommentary(res.commentary);
      setCached(res.cached);
      setSourceData(res.source_data);
    },
  });

  const apiError = mutation.error as { response?: { data?: { detail?: string } }; message?: string } | null;
  const errorMessage = apiError
    ? apiError.response?.data?.detail ?? apiError.message ?? "Failed to generate commentary"
    : null;

  return (
    <div className="q-card p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">AI Commentary</h2>
          <p className="text-xs text-[var(--text-muted)]">
            Plain-English summary of current composition, performance, and risk.
          </p>
        </div>
        <button
          onClick={() => mutation.mutate()}
          disabled={disabled || mutation.isPending}
          className="text-xs font-medium bg-[var(--navy)] text-white px-3 py-1.5 rounded-lg hover:opacity-90 disabled:opacity-50"
        >
          {mutation.isPending
            ? "Generating..."
            : commentary
              ? "Regenerate"
              : "Generate"}
        </button>
      </div>

      {errorMessage && (
        <p className="text-xs text-[var(--coral)] mb-2">{errorMessage}</p>
      )}

      {commentary ? (
        <div>
          <p className="text-sm text-[var(--text-primary)] leading-relaxed whitespace-pre-line">
            {commentary}
          </p>
          {cached && (
            <p className="text-[11px] text-[var(--text-muted)] mt-2">Served from cache</p>
          )}
          {sourceData && <SourceDataPanel data={sourceData} />}
        </div>
      ) : !mutation.isPending && !errorMessage ? (
        <p className="text-sm text-[var(--text-muted)]">
          Click <span className="font-medium">Generate</span> to write an AI summary for this portfolio.
        </p>
      ) : null}
    </div>
  );
}
