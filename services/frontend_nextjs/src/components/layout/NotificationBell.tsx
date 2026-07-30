"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { alertApi, type AlertEventResponse } from "@/lib/api";
import { apiDateMs, timeAgo } from "@/lib/datetime";

const SEEN_KEY = "qsight.alerts.lastSeen";

function humanizeType(t: string): string {
  return ({
    price_threshold: "Price threshold",
    anomaly: "Anomaly",
    forecast_divergence: "Forecast divergence",
  } as Record<string, string>)[t] ?? t.replace(/_/g, " ");
}

function detail(e: AlertEventResponse): string | null {
  const p = e.payload ?? {};
  const dir = p["direction"];
  const val = p["value"];
  const thr = p["threshold"];
  if (typeof val === "number" && typeof thr === "number" && typeof dir === "string") {
    return `${Number(val).toLocaleString(undefined, { maximumFractionDigits: 2 })} (${dir} ${Number(thr).toLocaleString(undefined, { maximumFractionDigits: 2 })})`;
  }
  if (typeof p["reason"] === "string") return p["reason"] as string;
  return null;
}

export function NotificationBell({ enabled }: { enabled: boolean }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState<number>(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const raw = typeof window !== "undefined" ? window.localStorage.getItem(SEEN_KEY) : null;
    setLastSeen(raw ? Number(raw) || 0 : 0);
  }, []);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const { data } = useQuery({
    queryKey: ["alert-events-recent"],
    queryFn: () => alertApi.events({ triggered_only: true, limit: 10 }),
    enabled,
    refetchInterval: 60_000,          // matches the ~5-min server cadence loosely
    refetchOnWindowFocus: true,
    staleTime: 30_000,
  });

  const events = useMemo(() => (data?.items ?? []).filter((e) => e.triggered), [data]);
  const unread = useMemo(
    () => events.filter((e) => (apiDateMs(e.evaluated_at) ?? 0) > lastSeen).length,
    [events, lastSeen],
  );

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && events.length > 0) {
      // Opening marks everything currently shown as seen.
      const newest = Math.max(...events.map((e) => apiDateMs(e.evaluated_at) ?? 0));
      setLastSeen(newest);
      try {
        window.localStorage.setItem(SEEN_KEY, String(newest));
      } catch {
        /* private mode / storage disabled: unread just won't persist */
      }
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={toggle}
        aria-label={unread > 0 ? `${unread} new alerts` : "Alerts"}
        className="relative rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--content-bg)] transition-colors"
      >
        <BellIcon className="h-5 w-5" />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[var(--coral)] px-1 text-[9px] font-bold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 rounded-lg border border-[var(--border)] bg-[var(--card-bg)] shadow-lg overflow-hidden z-40">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2.5">
            <span className="text-sm font-semibold text-[var(--text-primary)]">Alerts</span>
            <button
              onClick={() => { setOpen(false); router.push("/alerts"); }}
              className="text-[11px] font-medium text-[var(--teal)] hover:underline"
            >
              View all
            </button>
          </div>
          {events.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-[var(--text-muted)]">
              No recent alerts.
            </div>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {events.map((e) => {
                const d = detail(e);
                return (
                  <li key={e.id}>
                    <button
                      onClick={() => { setOpen(false); router.push(`/assets/${e.ticker}`); }}
                      className="flex w-full flex-col items-start gap-0.5 px-4 py-2.5 text-left hover:bg-[var(--content-bg)] transition-colors border-b border-[var(--border)] last:border-b-0"
                    >
                      <div className="flex w-full items-center justify-between">
                        <span className="text-sm font-semibold text-[var(--navy)]">{e.ticker}</span>
                        <span className="text-[10px] text-[var(--text-muted)]">{timeAgo(e.evaluated_at)}</span>
                      </div>
                      <span className="text-[11px] text-[var(--text-secondary)]">
                        {humanizeType(e.alert_type)}{d ? `: ${d}` : ""}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function BellIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  );
}
