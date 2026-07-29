"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { alertApi, type AlertEventResponse } from "@/lib/api";
import { AlertRulesList } from "@/components/shared/AlertRulesList";

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function humanizeType(t: string): string {
  return (
    { price_threshold: "Price threshold", anomaly: "Anomaly", forecast_divergence: "Forecast divergence" } as Record<
      string,
      string
    >
  )[t] ?? t.replace(/_/g, " ");
}

function detail(e: AlertEventResponse): string | null {
  const p = e.payload ?? {};
  const dir = p["direction"];
  const val = p["value"];
  const thr = p["threshold"];
  if (typeof val === "number" && typeof thr === "number" && typeof dir === "string") {
    return `${Number(val).toLocaleString(undefined, { maximumFractionDigits: 2 })} (${dir} ${Number(thr).toLocaleString(
      undefined,
      { maximumFractionDigits: 2 },
    )})`;
  }
  if (typeof p["reason"] === "string") return p["reason"] as string;
  return null;
}

export default function AlertsPage() {
  const router = useRouter();
  const { data: events, isLoading } = useQuery({
    queryKey: ["alert-events-all"],
    queryFn: () => alertApi.events({ triggered_only: true, limit: 50 }),
    refetchInterval: 60_000,
  });
  const items = events?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--navy)]">Alerts</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Your alert rules and everything they have triggered
        </p>
      </div>

      {/* Recent triggered alerts */}
      <div className="q-card p-5">
        <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Recent triggered alerts</h2>
        {isLoading ? (
          <div className="space-y-2">
            <div className="h-3 w-2/3 animate-pulse rounded bg-[var(--card-border)]" />
            <div className="h-3 w-full animate-pulse rounded bg-[var(--card-border)]" />
          </div>
        ) : items.length === 0 ? (
          <p className="py-6 text-center text-xs text-[var(--text-muted)]">
            No alerts have triggered yet. Alerts are evaluated on a schedule while the app is running.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {items.map((e) => {
              const d = detail(e);
              return (
                <li key={e.id}>
                  <button
                    onClick={() => router.push(`/assets/${e.ticker}`)}
                    className="flex w-full items-center justify-between gap-3 py-2.5 text-left hover:bg-[var(--content-bg)] transition-colors"
                  >
                    <div className="min-w-0">
                      <span className="text-sm font-semibold text-[var(--navy)]">{e.ticker}</span>
                      <span className="ml-2 text-[11px] text-[var(--text-secondary)]">
                        {humanizeType(e.alert_type)}
                        {d ? `: ${d}` : ""}
                      </span>
                    </div>
                    <span className="shrink-0 text-[10px] text-[var(--text-muted)]">{timeAgo(e.evaluated_at)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* All alert rules (create / manage / explain) */}
      <AlertRulesList title="Alert rules" />
    </div>
  );
}
