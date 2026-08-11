"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { agentsApi, type QLensBriefResponse } from "@/lib/api";

type Props = { ticker: string };

const STANCE_STYLE: Record<string, string> = {
  Buy: "bg-[var(--teal-light)] text-[var(--teal-muted)]",
  Hold: "bg-[var(--amber-light)] text-[var(--amber)]",
  Sell: "bg-[var(--coral-light)] text-[var(--coral)]",
};

// A decision-support "second opinion": an on-demand, honesty-gated bull/bear
// debate over Qmetrum's own data ending in a Buy/Hold/Sell stance. On-demand
// (advisor clicks) + cached server-side, so cost stays near zero.
export function QLensBriefCard({ ticker }: Props) {
  const [data, setData] = useState<QLensBriefResponse | null>(null);
  const m = useMutation({
    mutationFn: () => agentsApi.qlensBrief(ticker),
    onSuccess: setData,
  });
  const err = m.error as { response?: { data?: { detail?: string } }; message?: string } | null;
  const errMsg = err ? (err.response?.data?.detail ?? err.message ?? "Brief unavailable") : null;

  return (
    <div className="q-card p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">QLens — Second Opinion</h2>
          <p className="text-xs text-[var(--text-secondary)]">
            A bull-vs-bear debate on {ticker}, grounded in your data. A reasoned opinion, not advice.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {data && (
            <span className={`rounded-full px-3 py-1 text-xs font-bold ${STANCE_STYLE[data.stance] ?? ""}`}>
              {data.stance} · {data.conviction} conviction
            </span>
          )}
          <button
            onClick={() => m.mutate()}
            disabled={m.isPending}
            className="rounded-lg bg-[var(--btn-navy)] px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {m.isPending ? "Debating…" : data ? "Refresh" : "Get second opinion"}
          </button>
        </div>
      </div>

      {m.isPending && (
        <div className="space-y-2">
          <div className="h-3 w-2/3 animate-pulse rounded bg-[var(--card-border)]" />
          <div className="h-3 w-full animate-pulse rounded bg-[var(--card-border)]" />
          <div className="h-3 w-5/6 animate-pulse rounded bg-[var(--card-border)]" />
        </div>
      )}

      {errMsg && !m.isPending && (
        <div className="rounded bg-[var(--coral-light)] px-3 py-2 text-xs text-[var(--coral)]">{errMsg}</div>
      )}

      {data && !m.isPending && (
        <div className="space-y-4">
          {data.rationale && (
            <p className="text-sm leading-relaxed text-[var(--text-primary)]">{data.rationale}</p>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            <Column title="Bull case" color="var(--teal-muted)" items={data.bull} mark="+" />
            <Column title="Bear case" color="var(--coral)" items={data.bear} mark="−" />
          </div>
          {data.key_risks.length > 0 && (
            <Block title="Key risks" items={data.key_risks} tone="var(--amber)" mark="!" />
          )}
          {data.what_would_change_my_mind.length > 0 && (
            <Block title="What would change this view" items={data.what_would_change_my_mind} tone="var(--text-secondary)" mark="~" />
          )}
          <details className="text-xs">
            <summary className="cursor-pointer text-[var(--text-secondary)] hover:text-[var(--navy)]">
              Facts it reasoned from ({data.facts.length})
            </summary>
            <ul className="mt-2 space-y-1">
              {data.facts.map((f) => (
                <li key={f.idx} className="text-[var(--text-muted)]">
                  <span className="font-mono">[{f.idx}]</span> <span className="italic">({f.source})</span> {f.statement}
                </li>
              ))}
            </ul>
          </details>
          <p className="text-[10px] text-[var(--text-muted)]">
            {data.cached ? "Cached · " : ""}{data.disclaimer}
          </p>
        </div>
      )}
    </div>
  );
}

function Column({ title, color, items, mark }: { title: string; color: string; items: string[]; mark: string }) {
  return (
    <div className="rounded-lg border border-[var(--card-border)] p-3">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider" style={{ color }}>{title}</h3>
      <ul className="space-y-1.5">
        {items.map((x, i) => (
          <li key={i} className="text-sm text-[var(--text-primary)]">
            <span className="mr-1 font-semibold" style={{ color }}>{mark}</span>{x}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Block({ title, items, tone, mark }: { title: string; items: string[]; tone: string; mark: string }) {
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{title}</h3>
      <ul className="space-y-0.5">
        {items.map((x, i) => (
          <li key={i} className="text-xs" style={{ color: tone }}>{mark} {x}</li>
        ))}
      </ul>
    </div>
  );
}
