"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { agentsApi, type ClientLetterResponse } from "@/lib/api";

type Props = { portfolioId: string | number; portfolioName?: string };

// Draft a warm, client-ready quarterly letter grounded in the portfolio's real
// numbers. On-demand + cached server-side. Always a DRAFT for advisor review.
export function ClientLetterCard({ portfolioId, portfolioName }: Props) {
  const [data, setData] = useState<ClientLetterResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const m = useMutation({
    mutationFn: () => agentsApi.clientLetter(portfolioId),
    onSuccess: setData,
  });
  const err = m.error as { response?: { data?: { detail?: string } }; message?: string } | null;
  const errMsg = err ? (err.response?.data?.detail ?? err.message ?? "Draft unavailable") : null;

  const letterText = data
    ? [data.greeting, "", data.performance_paragraph,
       data.diversification_paragraph ? "\n" + data.diversification_paragraph : "",
       "\n" + data.closing_paragraph, "\n\n" + data.disclaimer].filter(Boolean).join("\n")
    : "";

  function copy() {
    navigator.clipboard?.writeText(letterText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const pf = data?.facts.portfolio;
  const reg = data?.facts.regime;

  return (
    <div className="q-card p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Draft client letter</h2>
          <p className="text-xs text-[var(--text-secondary)]">
            A warm quarterly letter on {portfolioName ?? "this portfolio"}, grounded in real numbers. A draft for you to review and edit.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {data && (
            <button onClick={copy} className="text-[11px] font-medium text-[var(--text-secondary)] hover:text-[var(--navy)]">
              {copied ? "Copied" : "Copy"}
            </button>
          )}
          <button
            onClick={() => m.mutate()}
            disabled={m.isPending}
            className="rounded-lg bg-[var(--btn-navy)] px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {m.isPending ? "Drafting…" : data ? "Redraft" : "Draft letter"}
          </button>
        </div>
      </div>

      {m.isPending && (
        <div className="space-y-2">
          <div className="h-3 w-1/2 animate-pulse rounded bg-[var(--card-border)]" />
          <div className="h-3 w-full animate-pulse rounded bg-[var(--card-border)]" />
          <div className="h-3 w-11/12 animate-pulse rounded bg-[var(--card-border)]" />
          <div className="h-3 w-5/6 animate-pulse rounded bg-[var(--card-border)]" />
        </div>
      )}

      {errMsg && !m.isPending && (
        <div className="rounded bg-[var(--coral-light)] px-3 py-2 text-xs text-[var(--coral)]">{errMsg}</div>
      )}

      {data && !m.isPending && (
        <div className="space-y-4">
          {data.is_draft && (
            <div className="rounded bg-[var(--amber-light)] px-3 py-1.5 text-[11px] font-medium text-[var(--amber)]">
              Draft for your review. You are the fiduciary; edit anything before it reaches a client.
            </div>
          )}
          <article className="space-y-3 rounded-lg border border-[var(--card-border)] bg-[var(--content-bg)] p-4 text-sm leading-relaxed text-[var(--text-primary)]">
            <p>{data.greeting}</p>
            <p>{data.performance_paragraph}</p>
            {data.diversification_paragraph && <p>{data.diversification_paragraph}</p>}
            <p>{data.closing_paragraph}</p>
            <p className="text-[10px] leading-snug text-[var(--text-muted)]">{data.disclaimer}</p>
          </article>

          {/* Source numbers, so every figure is checkable */}
          <details className="text-xs">
            <summary className="cursor-pointer text-[var(--text-secondary)] hover:text-[var(--navy)]">
              Source numbers (every figure in the letter)
            </summary>
            <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[var(--text-muted)]">
              {pf && (
                <>
                  <li>Quarter return: {pf.quarter_return_pct}%</li>
                  <li>1-year return: {pf.year_return_pct}%</li>
                  <li>Annualized volatility: {pf.ann_vol_pct}%</li>
                  <li>Deepest drop (1y): {pf.max_drawdown_pct}%</li>
                </>
              )}
              {reg && (
                <>
                  <li>Equity–bond correlation: {reg.short_corr}</li>
                  <li>Own baseline: {reg.baseline_corr}</li>
                </>
              )}
            </ul>
          </details>
          <p className="text-[10px] text-[var(--text-muted)]">{data.cached ? "Cached · " : ""}Numbers are realized, before fees and taxes.</p>
        </div>
      )}
    </div>
  );
}
