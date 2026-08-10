"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import { regimeApi, type RegimeWatchResponse } from "@/lib/api";
import { CorrelationChart } from "@/components/charts/CorrelationChart";

type Props = { portfolioId: string | number };

const TEAL = "#0F8B6E";
const AMBER = "#D4920B";
const CORAL = "#D85A30";

// Colour by the DELTA (short-window corr minus the book's own baseline): a rising
// correlation means the sleeves are moving together more than this book's norm —
// diversification weakening. Purely descriptive; no prediction implied.
function deltaColor(d?: number | null): string {
  if (d == null) return AMBER;
  if (d >= 0.1) return CORAL;
  if (d <= -0.1) return TEAL;
  return AMBER;
}

function fmt(x?: number | null): string {
  return x == null ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}`;
}

function sleeveLine(sw?: Record<string, number>): string {
  if (!sw) return "";
  return Object.entries(sw)
    .map(([k, v]) => `${k} ${(v * 100).toFixed(0)}%`)
    .join(" · ");
}

export function RegimeWatchCard({ portfolioId }: Props) {
  const { data, isLoading, isError, error } = useQuery<RegimeWatchResponse>({
    queryKey: ["portfolio-regime-watch", portfolioId],
    queryFn: () => regimeApi.get(portfolioId),
    staleTime: 1000 * 60 * 30,
    retry: false,
  });
  const enable = useMutation({ mutationFn: () => regimeApi.enableAlert(portfolioId, 0.15) });

  return (
    <div className="q-card p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Regime Watch — Diversification</h2>
          <p className="text-xs text-[var(--text-secondary)]">
            Realized equity-vs-bond correlation on your holdings, versus this book&apos;s own baseline
          </p>
        </div>
        {data?.status === "ok" &&
          (enable.isSuccess ? (
            <span className="rounded-full bg-[var(--teal-light)] px-3 py-1 text-xs font-semibold text-[var(--teal-muted)]">
              Alert enabled
            </span>
          ) : (
            <button
              onClick={() => enable.mutate()}
              disabled={enable.isPending}
              className="rounded-lg bg-[var(--btn-navy)] px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              {enable.isPending ? "Enabling…" : "Enable alert"}
            </button>
          ))}
      </div>

      {isLoading && <div className="text-sm text-[var(--text-muted)]">Loading…</div>}

      {isError && (
        <div className="rounded-lg bg-[var(--coral-light)] px-4 py-3 text-sm text-[var(--coral)]">
          {(error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            "Regime Watch unavailable."}
        </div>
      )}

      {data?.status === "pending" && (
        <div className="text-sm text-[var(--text-secondary)]">
          {data.note ?? "Computing on the next daily refresh."}
        </div>
      )}

      {data?.status === "na" && (
        <div className="rounded-lg bg-[var(--content-bg)] px-4 py-3 text-sm text-[var(--text-secondary)]">
          <span className="font-medium">Not measurable yet.</span> {data.reason}
          {data.sleeve_weights && Object.keys(data.sleeve_weights).length > 0 && (
            <div className="mt-1 text-xs text-[var(--text-muted)]">Sleeves: {sleeveLine(data.sleeve_weights)}</div>
          )}
        </div>
      )}

      {data?.status === "ok" && (
        <>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                {data.short_window}-day realized correlation
              </div>
              <div className="text-4xl font-bold tabular-nums" style={{ color: deltaColor(data.delta) }}>
                {fmt(data.short_corr)}
              </div>
              <div className="text-xs text-[var(--text-secondary)]">
                vs own baseline {fmt(data.baseline_corr)} · Δ {fmt(data.delta)}
              </div>
            </div>
            <div className="text-right text-[11px] text-[var(--text-muted)]">
              <div>
                n={data.n_obs} · as of {data.as_of ?? "—"}
              </div>
              {data.stale && <div className="text-[var(--amber)]">⚠ stale — awaiting refresh</div>}
              {data.sleeve_weights && <div>{sleeveLine(data.sleeve_weights)}</div>}
            </div>
          </div>

          {data.delta != null && (
            <p className="text-sm font-medium" style={{ color: deltaColor(data.delta) }}>
              {data.delta >= 0.1
                ? "Equity and bond sleeves are moving together more than this book's norm — the diversification you're counting on is weakening."
                : data.delta <= -0.1
                  ? "Sleeves are diversifying better than this book's norm."
                  : "In line with this book's own baseline."}
            </p>
          )}

          {data.series && data.series.length > 0 && (
            <CorrelationChart series={data.series} color={deltaColor(data.delta)} height={160} />
          )}

          {enable.isError && <p className="text-xs text-[var(--coral)]">Couldn&apos;t enable the alert. Please try again.</p>}

          <ul className="space-y-1 text-[11px] text-[var(--text-muted)]">
            {(data.disclaimers ?? []).map((d, i) => (
              <li key={i}>· {d}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
