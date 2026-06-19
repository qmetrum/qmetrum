"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { agentsApi } from "@/lib/api";
import { AgentCard } from "@/components/shared/AgentCard";

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
  const [model, setModel] = useState<string | null>(null);
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
      setModel(res.model);
      setSourceData(res.source_data);
    },
  });

  const apiError = mutation.error as { response?: { data?: { detail?: string } }; message?: string } | null;
  const errorMessage = apiError
    ? apiError.response?.data?.detail ?? apiError.message ?? "Failed to generate commentary"
    : null;

  return (
    <AgentCard
      title="AI Commentary"
      subtitle="Plain-English summary of current composition, performance, and risk."
      onRun={() => mutation.mutate()}
      isPending={mutation.isPending}
      runLabel="Generate"
      disabled={disabled}
      markdown={commentary}
      error={errorMessage}
      sourceData={sourceData}
      cached={cached}
      model={model}
    />
  );
}
