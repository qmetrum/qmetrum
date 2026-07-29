"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { agentsApi, type NewsSynthesisResponse } from "@/lib/api";
import { AgentCard } from "@/components/shared/AgentCard";

type NewsItem = {
  title: string;
  publisher?: string;
  timestamp?: string;
  type?: string;
  link?: string;
};

type Props = {
  ticker: string;
  items: NewsItem[];
};

const SENTIMENT_STYLE: Record<string, { bg: string; dot: string; label: string }> = {
  bullish: { bg: "bg-[var(--teal-light)] text-[var(--teal)]", dot: "bg-[var(--teal)]", label: "Bullish" },
  bearish: { bg: "bg-[var(--coral-light)] text-[var(--coral)]", dot: "bg-[var(--coral)]", label: "Bearish" },
  mixed: { bg: "bg-[var(--amber-light)] text-[var(--amber)]", dot: "bg-[var(--amber)]", label: "Mixed" },
  neutral: { bg: "bg-[var(--content-bg)] text-[var(--text-muted)]", dot: "bg-[var(--text-muted)]", label: "Neutral" },
};

export function NewsSynthesisCard({ ticker, items }: Props) {
  const [synthesis, setSynthesis] = useState<NewsSynthesisResponse | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      agentsApi.synthesizeNews(
        ticker,
        items.map(({ title, publisher, timestamp, type }) => ({ title, publisher, timestamp, type })),
      ),
    onSuccess: (res) => setSynthesis(res),
  });

  const apiError = mutation.error as { response?: { data?: { detail?: string } }; message?: string } | null;
  const errorMessage = apiError
    ? apiError.response?.data?.detail ?? apiError.message ?? "Failed to synthesize news"
    : null;

  const disabled = items.length === 0;
  const sentimentStyle = synthesis ? SENTIMENT_STYLE[synthesis.sentiment] ?? SENTIMENT_STYLE.neutral : null;

  return (
    <AgentCard
      title="AI News Summary"
      subtitle={disabled ? "No recent news to summarize." : "Themes, sentiment, and the items that matter most."}
      onRun={() => mutation.mutate()}
      isPending={mutation.isPending}
      runLabel="Summarize"
      disabled={disabled}
      markdown={synthesis?.summary ?? null}
      error={errorMessage}
      sourceData={synthesis?.source_data}
      cached={synthesis?.cached ?? null}
    >
      {synthesis && (
        <>
          {sentimentStyle && (
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${sentimentStyle.bg}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${sentimentStyle.dot}`} />
              {sentimentStyle.label}
            </span>
          )}
          {synthesis.highlights.length > 0 && (
            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Highlights
              </p>
              <ul className="space-y-1.5">
                {synthesis.highlights.map((h) => {
                  const item = items[h.index];
                  if (!item) return null;
                  return (
                    <li key={h.index} className="text-xs">
                      <a
                        href={item.link ? String(item.link) : "#"}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-medium text-[var(--navy)] hover:underline"
                      >
                        {item.title}
                      </a>
                      <span className="text-[var(--text-muted)]"> — {h.note}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </>
      )}
    </AgentCard>
  );
}
