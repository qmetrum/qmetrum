"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  alertApi,
  type AlertEventResponse,
  type AlertRating,
  type QpulseEventPayload,
} from "@/lib/api";

type Props = {
  limit?: number;
  title?: string;
};

// Keys are the vocabulary Qpulse actually emits (app/narrative.py severity()).
const SEVERITY_STYLES: Record<string, string> = {
  anomaly: "bg-[var(--red-light)] text-[var(--red)]",
  warning: "bg-[var(--amber-light)] text-[var(--amber)]",
  alert: "bg-[var(--blue-light)] text-[var(--blue)]",
  info: "bg-[var(--card-muted)] text-[var(--text-muted)]",
};
const SEVERITY_FALLBACK = "bg-[var(--card-muted)] text-[var(--text-muted)]";

function SeverityBadge({ severity }: { severity?: string | null }) {
  const key = (severity ?? "info").toLowerCase();
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        SEVERITY_STYLES[key] ?? SEVERITY_FALLBACK
      }`}
    >
      {key}
    </span>
  );
}

function relativeTime(iso: string): string {
  // The API serialises evaluated_at from datetime.utcnow() with no timezone
  // designator, which JS would otherwise parse as LOCAL time — making every age
  // wrong by the viewer's UTC offset.
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
  const then = new Date(hasZone ? iso : `${iso}Z`).getTime();
  if (Number.isNaN(then)) return "unknown";
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

// Feeds that do not carry real market data. An alert from one of these must not
// look like a live-market alert on the dashboard.
const NON_LIVE_FEEDS = new Set(["synthetic", "csv"]);

function isQpulse(payload: unknown): payload is QpulseEventPayload {
  return (
    typeof payload === "object" &&
    payload !== null &&
    (payload as { detector_source?: string }).detector_source === "qpulse"
  );
}

/**
 * Live anomaly alerts produced by the Qpulse detector.
 *
 * Qpulse runs on demand rather than as an always-on service, so an empty or
 * stale feed is a normal state and is labeled as such instead of looking broken.
 *
 * Deliberately absent: any recall or false-positive number. Those were measured
 * on historical daily bars against labeled catalogs; the alerts here come from a
 * live stream whose detection performance has not been measured. The most this
 * card claims is the NAME of the catalog a given alert kind was gated on.
 */
export function AnomalyFeedCard({ limit = 25, title = "Anomaly Feed" }: Props) {
  const queryClient = useQueryClient();
  const [rated, setRated] = useState<Record<number, AlertRating>>({});
  const [muteNotice, setMuteNotice] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["qpulse-events", limit],
    queryFn: () =>
      alertApi.events({ limit, triggered_only: true, detector_source: "qpulse" }),
    refetchInterval: 60_000,
  });

  const feedback = useMutation({
    mutationFn: ({ id, rating }: { id: number; rating: AlertRating }) =>
      alertApi.submitFeedback(id, rating),
    onSuccess: (res, vars) => {
      setRated((prev) => ({ ...prev, [vars.id]: vars.rating }));
      if (res.auto_muted_kind) {
        setMuteNotice(
          `Muted "${res.auto_muted_kind}" alerts after repeated unhelpful ratings. ` +
            `Undo in alert settings.`,
        );
      }
      queryClient.invalidateQueries({ queryKey: ["alert-preferences"] });
    },
  });

  // Filter client-side too. Amplify and ECS deploy independently, so during a
  // rollout this card can hit a backend that ignores detector_source and
  // returns every alert type — which would render price-threshold events under
  // an "Anomaly Feed" heading labelled "experimental".
  const events: AlertEventResponse[] = useMemo(
    () => (data?.items ?? []).filter((e) => isQpulse(e.payload)),
    [data],
  );
  const newest = events[0]?.evaluated_at;

  return (
    <div className="q-card overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--card-border)] px-5 py-3">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="text-[11px] text-[var(--text-muted)]">
            Qpulse · {newest ? `last event ${relativeTime(newest)}` : "on-demand detector"}
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-2 p-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded bg-[var(--card-muted)]" />
          ))}
        </div>
      ) : isError ? (
        <div className="px-5 py-8 text-center text-sm text-[var(--text-muted)]">
          Could not load anomaly alerts.
        </div>
      ) : events.length === 0 ? (
        <div className="px-5 py-8 text-center">
          <p className="text-sm text-[var(--text-muted)]">No anomaly alerts yet.</p>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Qpulse runs on demand. Create an alert rule of type “Anomaly (Qpulse)”
            for a ticker, then start the detector to receive alerts here.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-[var(--card-border)]">
          {events.map((ev) => {
            const p = isQpulse(ev.payload) ? ev.payload : null;
            const q = p?.qpulse;
            return (
              <li key={ev.id} className="px-5 py-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold">{ev.ticker}</span>
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={q?.severity} />
                    <span className="text-[11px] text-[var(--text-muted)]">
                      {relativeTime(ev.evaluated_at)}
                    </span>
                  </div>
                </div>

                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  {q?.narrative ?? `${q?.kind ?? "anomaly"} detected`}
                </p>

                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <span className="rounded bg-[var(--card-muted)] px-1.5 py-0.5 font-mono text-[10px]">
                    {q?.kind}
                  </span>
                  {typeof q?.score === "number" && (
                    <span
                      className="text-[10px] text-[var(--text-muted)]"
                      title="Scores are per-detector units and are not comparable across kinds."
                    >
                      score {q.score.toFixed(2)}
                    </span>
                  )}
                  {q?.feed && NON_LIVE_FEEDS.has(q.feed.toLowerCase()) && (
                    <span
                      className="rounded bg-[var(--amber-light)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--amber)]"
                      title={`Generated from the ${q.feed} feed, not live market data.`}
                    >
                      {q.feed === "csv" ? "replay" : "synthetic"}
                    </span>
                  )}
                  {p?.gated_on_reference_catalog ? (
                    <span
                      className="text-[10px] text-[var(--text-muted)]"
                      title={`This alert kind was scored against ${p.reference_gate} on historical daily bars. Live-stream performance is not measured.`}
                    >
                      · scored offline on {p.reference_gate}
                    </span>
                  ) : (
                    <span
                      className="text-[10px] text-[var(--amber)]"
                      title="This detector/asset-class combination has not been scored against a labeled catalog."
                    >
                      · experimental
                    </span>
                  )}

                  <span className="ml-auto flex items-center gap-1">
                    {rated[ev.id] ? (
                      <span className="text-[10px] text-[var(--text-muted)]">
                        {rated[ev.id] === "useful" ? "marked useful" : "marked not useful"}
                      </span>
                    ) : (
                      <>
                        <button
                          type="button"
                          aria-label="Mark this alert useful"
                          disabled={feedback.isPending}
                          onClick={() => feedback.mutate({ id: ev.id, rating: "useful" })}
                          className="rounded px-1.5 py-0.5 text-[11px] text-[var(--text-muted)] hover:bg-[var(--card-muted)] disabled:opacity-40"
                          title="Useful — send more like this"
                        >
                          👍
                        </button>
                        <button
                          type="button"
                          aria-label="Mark this alert not useful"
                          disabled={feedback.isPending}
                          onClick={() => feedback.mutate({ id: ev.id, rating: "not_useful" })}
                          className="rounded px-1.5 py-0.5 text-[11px] text-[var(--text-muted)] hover:bg-[var(--card-muted)] disabled:opacity-40"
                          title="Not useful — fewer like this"
                        >
                          👎
                        </button>
                      </>
                    )}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {muteNotice && (
        <div className="border-t border-[var(--card-border)] bg-[var(--amber-light)] px-5 py-2 text-[11px] text-[var(--amber)]">
          {muteNotice}
          <button
            type="button"
            onClick={() => setMuteNotice(null)}
            className="ml-2 underline"
          >
            dismiss
          </button>
        </div>
      )}
    </div>
  );
}
