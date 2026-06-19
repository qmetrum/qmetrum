"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { agentsApi, alertApi, type AlertRuleResponse } from "@/lib/api";
import { SourceDataPanel } from "@/components/shared/SourceDataPanel";
import { Markdown } from "@/components/shared/Markdown";
import { AGENT_DISCLAIMER, stripDisclaimer } from "@/components/shared/AgentCard";

type Props = {
  // Filter rules to this set of tickers. If omitted, shows all user rules.
  tickers?: string[];
  title?: string;
};

type ExplanationState = {
  text: string;
  cached: boolean;
  sourceData: Record<string, unknown>;
};

export function AlertRulesList({ tickers, title = "Your Alerts" }: Props) {
  const queryClient = useQueryClient();
  const [explanations, setExplanations] = useState<Record<number, ExplanationState>>({});
  const [pendingExplainId, setPendingExplainId] = useState<number | null>(null);
  const [explainError, setExplainError] = useState<Record<number, string>>({});

  const { data, isLoading } = useQuery({
    queryKey: ["alert-rules"],
    queryFn: () => alertApi.list(),
  });

  const tickerSet = useMemo(
    () => (tickers ? new Set(tickers.map((t) => t.toUpperCase())) : null),
    [tickers],
  );

  const rules: AlertRuleResponse[] = useMemo(() => {
    const all = data?.items ?? [];
    if (!tickerSet) return all;
    return all.filter((r) => tickerSet.has(r.ticker.toUpperCase()));
  }, [data, tickerSet]);

  const removeMutation = useMutation({
    mutationFn: (alertId: number) => alertApi.remove(alertId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
      queryClient.invalidateQueries({ queryKey: ["alert-events"] });
    },
  });

  const explain = async (alertId: number) => {
    setExplainError((e) => ({ ...e, [alertId]: "" }));
    setPendingExplainId(alertId);
    try {
      const res = await agentsApi.explainAlert(alertId);
      setExplanations((prev) => ({
        ...prev,
        [alertId]: { text: res.explanation, cached: res.cached, sourceData: res.source_data },
      }));
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } }; message?: string })
          ?.response?.data?.detail ??
        (err as { message?: string })?.message ??
        "Failed to explain alert";
      setExplainError((e) => ({ ...e, [alertId]: msg }));
    } finally {
      setPendingExplainId(null);
    }
  };

  if (isLoading) {
    return (
      <div className="q-card p-4">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">{title}</h3>
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-10 rounded-lg bg-[var(--content-bg)] animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="q-card p-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
        {title}{" "}
        {rules.length > 0 && (
          <span className="text-xs font-normal text-[var(--text-muted)]">({rules.length})</span>
        )}
      </h3>
      {rules.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)] py-4 text-center">No alerts yet</p>
      ) : (
        <div className="space-y-1.5 max-h-[420px] overflow-y-auto">
          {rules.map((rule) => {
            const explanation = explanations[rule.id];
            const err = explainError[rule.id];
            return (
              <div
                key={rule.id}
                className="rounded-lg bg-[var(--content-bg)] hover:bg-[var(--border)] transition-colors"
              >
                <div className="flex items-center gap-3 px-3 py-2">
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${
                      rule.is_active ? "bg-[var(--teal)]" : "bg-[var(--text-muted)]"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-[var(--navy)]">
                        {rule.ticker}
                      </span>
                      <span className="text-xs text-[var(--text-muted)]">
                        {rule.direction} ${rule.threshold_value}
                      </span>
                    </div>
                    <p className="text-[11px] text-[var(--text-muted)] truncate">{rule.name}</p>
                  </div>
                  <button
                    onClick={() => explain(rule.id)}
                    disabled={pendingExplainId === rule.id}
                    className="text-xs text-[var(--text-muted)] hover:text-[var(--navy)] transition-colors disabled:opacity-50"
                    title="AI explanation of why this alert matters"
                  >
                    {pendingExplainId === rule.id ? "..." : "Explain"}
                  </button>
                  <button
                    onClick={() => {
                      if (confirm(`Delete alert "${rule.name}"?`)) {
                        removeMutation.mutate(rule.id);
                      }
                    }}
                    disabled={removeMutation.isPending}
                    className="text-xs text-[var(--text-muted)] hover:text-[var(--coral)] transition-colors disabled:opacity-50"
                    title="Delete alert"
                  >
                    Remove
                  </button>
                </div>
                {(explanation || err) && (
                  <div className="border-t border-[var(--card-border)] px-3 py-2">
                    {err && <p className="text-xs text-[var(--coral)]">{err}</p>}
                    {explanation && (
                      <div className="space-y-1">
                        <Markdown>{stripDisclaimer(explanation.text)}</Markdown>
                        {explanation.cached && (
                          <span className="text-[10px] text-[var(--text-muted)]">cached</span>
                        )}
                        <SourceDataPanel data={explanation.sourceData} />
                        <p className="text-[10px] text-[var(--text-muted)]">{AGENT_DISCLAIMER}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
