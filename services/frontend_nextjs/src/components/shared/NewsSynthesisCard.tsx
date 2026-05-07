"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { agentsApi, type NewsSynthesisResponse } from "@/lib/api";
import { SourceDataPanel } from "@/components/shared/SourceDataPanel";

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
  bearish: { bg: "bg-[#FDECEC] text-[var(--coral)]", dot: "bg-[var(--coral)]", label: "Bearish" },
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
    <div className="q-card p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">AI News Summary</h2>
          <p className="text-xs text-[var(--text-muted)]">
            Themes, sentiment, and the items that matter most.
          </p>
        </div>
        <button
          onClick={() => mutation.mutate()}
          disabled={disabled || mutation.isPending}
          className="text-xs font-medium bg-[var(--navy)] text-white px-3 py-1.5 rounded-lg hover:opacity-90 disabled:opacity-50"
        >
          {mutation.isPending
            ? "Summarizing..."
            : synthesis
              ? "Re-summarize"
              : "Summarize"}
        </button>
      </div>

      {errorMessage && <p className="text-xs text-[var(--coral)] mb-2">{errorMessage}</p>}

      {synthesis ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${sentimentStyle?.bg}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${sentimentStyle?.dot}`} />
              {sentimentStyle?.label}
            </span>
            {synthesis.cached && (
              <span className="text-[11px] text-[var(--text-muted)]">cached</span>
            )}
          </div>
          <p className="text-sm text-[var(--text-primary)] leading-relaxed whitespace-pre-line">
            {synthesis.summary}
          </p>
          {synthesis.highlights.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1.5">
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
          <SourceDataPanel data={synthesis.source_data} />
        </div>
      ) : !mutation.isPending && !errorMessage ? (
        <p className="text-sm text-[var(--text-muted)]">
          {disabled
            ? "No news to summarize."
            : <>Click <span className="font-medium">Summarize</span> to generate a concise take on the latest news.</>}
        </p>
      ) : null}
    </div>
  );
}
