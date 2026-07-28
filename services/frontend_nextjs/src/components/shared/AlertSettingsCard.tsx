"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  alertApi,
  type AlertPreferences,
  type AlertSeverity,
} from "@/lib/api";

const SEVERITIES: { value: AlertSeverity; label: string; hint: string }[] = [
  { value: "INFO", label: "Everything", hint: "every alert, including minor deviations" },
  { value: "ALERT", label: "Standard", hint: "moderate deviations and above" },
  { value: "WARNING", label: "Fewer", hint: "significant deviations only" },
  { value: "ANOMALY", label: "Only the largest", hint: "extreme deviations only" },
];

const HOURS = Array.from({ length: 24 }, (_, i) => i);

function fmtHour(h: number) {
  return `${String(h).padStart(2, "0")}:00`;
}

/**
 * Per-user alert notification settings.
 *
 * Deliberately phrased in outcomes ("fewer alerts") rather than sigma
 * thresholds: this controls who gets emailed, not how the detector runs. The
 * detector is shared, so one user's preferences must never change what another
 * user sees — muting here only silences this user's inbox, and the alert stays
 * visible in the feed.
 */
export function AlertSettingsCard({ title = "Alert Settings" }: { title?: string }) {
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState(false);

  // Server state is the single source of truth — every control saves on change,
  // so there is no local draft to keep in sync (and no setState-in-effect).
  const { data: draft, isLoading, isError } = useQuery({
    queryKey: ["alert-preferences"],
    queryFn: () => alertApi.preferences(),
  });

  const { data: summary } = useQuery({
    queryKey: ["alert-feedback-summary"],
    queryFn: () => alertApi.feedbackSummary(),
  });

  const save = useMutation({
    mutationFn: (patch: Partial<AlertPreferences>) => alertApi.updatePreferences(patch),
    onSuccess: (fresh) => {
      queryClient.setQueryData(["alert-preferences"], fresh);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    },
  });

  const monitor = useMutation({
    mutationFn: () => alertApi.monitorHoldings(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
    },
  });

  if (isLoading || !draft) {
    return (
      <div className="q-card p-5">
        <h2 className="text-sm font-semibold">{title}</h2>
        <div className="mt-3 h-24 animate-pulse rounded bg-[var(--card-muted)]" />
      </div>
    );
  }
  if (isError) {
    return (
      <div className="q-card p-5">
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Could not load alert settings.
        </p>
      </div>
    );
  }

  const quietOn = draft.quiet_hours_start !== draft.quiet_hours_end;

  return (
    <div className="q-card overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--card-border)] px-5 py-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {saved && <span className="text-[11px] text-[var(--teal)]">saved</span>}
      </div>

      <div className="space-y-5 p-5">
        {/* Email on/off */}
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={draft.email_enabled}
            onChange={(e) => save.mutate({ email_enabled: e.target.checked })}
            className="mt-0.5"
          />
          <span>
            <span className="text-sm font-medium">Email me about anomalies</span>
            <span className="block text-[11px] text-[var(--text-muted)]">
              Alerts always appear in the feed; this controls your inbox only.
            </span>
          </span>
        </label>

        {/* Sensitivity */}
        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            How much to send
          </label>
          <select
            value={draft.min_severity}
            onChange={(e) => save.mutate({ min_severity: e.target.value as AlertSeverity })}
            className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm"
          >
            {SEVERITIES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label} — {s.hint}
              </option>
            ))}
          </select>
        </div>

        {/* Quiet hours */}
        <div>
          <label className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            <input
              type="checkbox"
              checked={quietOn}
              onChange={(e) =>
                save.mutate(
                  e.target.checked
                    ? { quiet_hours_start: 22, quiet_hours_end: 7 }
                    : { quiet_hours_start: 0, quiet_hours_end: 0 },
                )
              }
            />
            Quiet hours
          </label>
          {quietOn && (
            <div className="flex items-center gap-2">
              <select
                value={draft.quiet_hours_start}
                onChange={(e) => save.mutate({ quiet_hours_start: Number(e.target.value) })}
                className="rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-2 py-1.5 text-sm"
              >
                {HOURS.map((h) => <option key={h} value={h}>{fmtHour(h)}</option>)}
              </select>
              <span className="text-xs text-[var(--text-muted)]">to</span>
              <select
                value={draft.quiet_hours_end}
                onChange={(e) => save.mutate({ quiet_hours_end: Number(e.target.value) })}
                className="rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-2 py-1.5 text-sm"
              >
                {HOURS.map((h) => <option key={h} value={h}>{fmtHour(h)}</option>)}
              </select>
              <span className="text-[11px] text-[var(--text-muted)]">
                no emails in this window
              </span>
            </div>
          )}
        </div>

        {/* Mutes */}
        {(draft.muted_kinds.length > 0 || draft.muted_tickers.length > 0) && (
          <div>
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              Muted
            </span>
            <div className="flex flex-wrap gap-1.5">
              {draft.muted_kinds.map((k) => (
                <button
                  key={`k-${k}`}
                  type="button"
                  onClick={() =>
                    save.mutate({ muted_kinds: draft.muted_kinds.filter((x) => x !== k) })
                  }
                  className="rounded bg-[var(--card-muted)] px-2 py-0.5 font-mono text-[11px] hover:line-through"
                  title="Click to unmute"
                >
                  {k} ✕
                </button>
              ))}
              {draft.muted_tickers.map((t) => (
                <button
                  key={`t-${t}`}
                  type="button"
                  onClick={() =>
                    save.mutate({ muted_tickers: draft.muted_tickers.filter((x) => x !== t) })
                  }
                  className="rounded bg-[var(--card-muted)] px-2 py-0.5 text-[11px] font-semibold hover:line-through"
                  title="Click to unmute"
                >
                  {t} ✕
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Auto-mute */}
        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Auto-mute
          </label>
          <div className="flex items-center gap-2">
            {/* Uncontrolled so typing is not fought by the server value; keyed
                so it resets if the stored setting changes elsewhere. */}
            <input
              key={`automute-${draft.auto_mute_after}`}
              type="number"
              min={0}
              max={20}
              defaultValue={draft.auto_mute_after}
              onBlur={(e) => {
                const next = Math.max(0, Math.min(20, Number(e.target.value) || 0));
                if (next !== draft.auto_mute_after) save.mutate({ auto_mute_after: next });
              }}
              className="w-16 rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-2 py-1.5 text-sm"
            />
            <span className="text-[11px] text-[var(--text-muted)]">
              consecutive “not useful” ratings before a detector is muted (0 = never)
            </span>
          </div>
        </div>

        {/* Bulk monitor */}
        <div className="border-t border-[var(--card-border)] pt-4">
          <button
            type="button"
            onClick={() => monitor.mutate()}
            disabled={monitor.isPending}
            className="rounded bg-[var(--navy)] px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {monitor.isPending ? "Setting up…" : "Monitor all my holdings"}
          </button>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Creates an anomaly alert for every ticker you hold. Already-monitored
            tickers are skipped.
          </p>
          {monitor.data && (
            <p className="mt-1 text-[11px] text-[var(--teal)]">
              {monitor.data.created.length > 0
                ? `Now monitoring ${monitor.data.created.join(", ")}.`
                : "Everything you hold was already monitored."}
            </p>
          )}
        </div>

        {/* Feedback so far — the raw material for tuning */}
        {summary && summary.total > 0 && (
          <div className="border-t border-[var(--card-border)] pt-4 text-[11px] text-[var(--text-muted)]">
            You have rated {summary.total} alert{summary.total === 1 ? "" : "s"} —{" "}
            {summary.useful} useful, {summary.not_useful} not useful.
          </div>
        )}
      </div>
    </div>
  );
}
