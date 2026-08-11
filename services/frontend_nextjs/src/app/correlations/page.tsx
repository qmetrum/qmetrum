"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  correlationApi,
  type CorrelationMonitorResponse,
  type CorrelationReplayResponse,
  type CorrelationPair,
} from "@/lib/api";
import { CorrelationChart } from "@/components/charts/CorrelationChart";
import { ReplayChart } from "@/components/charts/ReplayChart";

// Per-pair caveat where the sign needs context (high-yield credit is equity-like,
// so a positive reading is expected, not a diversification failure).
const PAIR_NOTES: Record<string, string> = {
  SPY_HYG: "High-yield credit is equity-like — a positive reading is normal here.",
};

const TEAL = "#0F8B6E";
const AMBER = "#D4920B";
const CORAL = "#D85A30";

function corrColor(x: number): string {
  if (x <= 0) return TEAL; // moving opposite → still diversifying
  if (x >= 0.4) return CORAL; // moving together → diversification weakening
  return AMBER;
}

function fmtCorr(x: number): string {
  return `${x >= 0 ? "+" : ""}${x.toFixed(2)}`;
}

function heroRead(pearson: number): { headline: string; tone: string } {
  if (pearson >= 0.4)
    return {
      headline: "Stocks and bonds are moving together — the diversification a 60/40 assumes is weak right now.",
      tone: CORAL,
    };
  if (pearson <= 0)
    return {
      headline: "Stocks and bonds are moving in opposite directions — the 60/40's diversification is intact.",
      tone: TEAL,
    };
  return {
    headline: "Stocks and bonds are only loosely linked — the 60/40 is partly, but not fully, diversified.",
    tone: AMBER,
  };
}

export default function CorrelationsPage() {
  const { data, isLoading, isError } = useQuery<CorrelationMonitorResponse>({
    queryKey: ["public-correlations"],
    queryFn: correlationApi.get,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });

  const windows = data?.windows ?? [30, 60, 90];
  const [win, setWin] = useState<number>(60);
  const activeWin = windows.includes(win) ? win : windows[Math.min(1, windows.length - 1)] ?? 60;

  const pairs = data?.pairs ?? [];
  const hero = pairs.find((p) => p.pair_key === "SPY_AGG");
  const heroStat = hero?.windows[String(activeWin)];

  return (
    <div className="min-h-screen bg-[var(--content-bg)] text-[var(--text-primary)]">
      {/* Top wordmark bar */}
      <header className="border-b border-[var(--card-border)] bg-[var(--card-bg)]">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-3">
          <span className="text-sm font-bold uppercase tracking-[0.18em] text-[var(--navy)]">
            Qmetrum
          </span>
          <Link
            href="/"
            className="text-xs font-medium text-[var(--teal)] hover:underline"
          >
            Qsight for advisors →
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-5 pb-20 pt-10">
        {/* Hero */}
        <div className="max-w-2xl">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--teal)]">
            Cross-Asset Correlation Monitor
          </p>
          <h1 className="text-3xl font-bold leading-tight text-[var(--navy)] sm:text-4xl">
            Is the 60/40 still diversified?
          </h1>
          <p className="mt-3 text-[15px] leading-relaxed text-[var(--text-secondary)]">
            A 60/40 portfolio only works if stocks and bonds don&apos;t fall together. This tracks
            the <strong>realized</strong> correlation between them and other cross-asset pairs — a
            measurement of what markets have actually done, updated daily. It is not a forecast.
          </p>
        </div>

        {/* Window toggle */}
        <div className="mt-7 flex items-center gap-2">
          <span className="text-xs font-medium text-[var(--text-muted)]">Trailing window:</span>
          {windows.map((w) => (
            <button
              key={w}
              onClick={() => setWin(w)}
              aria-pressed={activeWin === w}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                activeWin === w
                  ? "bg-[var(--btn-navy)] text-white"
                  : "bg-[var(--card-bg)] text-[var(--text-secondary)] border border-[var(--card-border)] hover:border-[var(--teal)]"
              }`}
            >
              {w} days
            </button>
          ))}
        </div>

        {isLoading && (
          <div className="mt-8 text-sm text-[var(--text-muted)]">Loading latest correlations…</div>
        )}
        {isError && (
          <div className="mt-8 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] p-5 text-sm text-[var(--text-secondary)]">
            Couldn&apos;t load the latest data right now. Please refresh in a moment.
          </div>
        )}

        {/* Hero metric */}
        {hero && heroStat && (
          <section className="mt-6 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6 shadow-[var(--card-shadow)]">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  S&amp;P 500 vs U.S. Aggregate Bonds · {activeWin}-day realized
                </p>
                <div
                  className="mt-1 text-5xl font-bold tabular-nums"
                  style={{ color: corrColor(heroStat.pearson) }}
                >
                  {fmtCorr(heroStat.pearson)}
                </div>
              </div>
              <p
                className="max-w-md text-sm font-medium leading-snug"
                style={{ color: heroRead(heroStat.pearson).tone }}
              >
                {heroRead(heroStat.pearson).headline}
              </p>
            </div>
            <div className="mt-5">
              <CorrelationChart
                series={hero.series[String(activeWin)] ?? []}
                color={corrColor(heroStat.pearson)}
                label="S&P 500 vs U.S. Aggregate Bonds"
                height={200}
              />
            </div>
          </section>
        )}

        {/* Legend */}
        {pairs.length > 0 && (
          <p className="mt-4 text-xs leading-relaxed text-[var(--text-muted)]">
            <span style={{ color: TEAL }}>●</span> ≤ 0 diversifying (moving opposite) &nbsp;·&nbsp;
            <span style={{ color: AMBER }}>●</span> 0 to +0.4 partial &nbsp;·&nbsp;
            <span style={{ color: CORAL }}>●</span> ≥ +0.4 moving together (diversification weak).
            For a stock/bond mix, a reading near 0 or below means the two legs still offset each other.
          </p>
        )}

        {/* Pair grid */}
        {pairs.length > 0 && (
          <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
            {pairs
              .filter((p) => p.pair_key !== "SPY_AGG")
              .map((p) => (
                <PairCard key={p.pair_key} pair={p} activeWin={activeWin} />
              ))}
          </div>
        )}

        {/* Historical replay — the credibility artifact */}
        <ReplaySection />

        {/* Email capture */}
        <SignupCard />

        {/* Methodology / honesty panel */}
        {data && (
          <section className="mt-10 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6">
            <h2 className="text-sm font-semibold text-[var(--navy)]">How this is computed</h2>
            <dl className="mt-3 grid grid-cols-1 gap-x-8 gap-y-2 text-xs text-[var(--text-secondary)] sm:grid-cols-2">
              <div className="flex justify-between gap-4">
                <dt className="text-[var(--text-muted)]">As of</dt>
                <dd className="font-medium">{data.as_of ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-[var(--text-muted)]">Data source</dt>
                <dd className="font-medium">{data.data_source ?? "—"} · end-of-day closes</dd>
              </div>
            </dl>
            <ul className="mt-4 space-y-1.5 text-xs leading-relaxed text-[var(--text-muted)]">
              {(data.disclaimers ?? []).map((d, i) => (
                <li key={i}>· {d}</li>
              ))}
            </ul>
          </section>
        )}

        <footer className="mt-10 text-center text-xs text-[var(--text-muted)]">
          Built by <span className="font-semibold text-[var(--navy)]">Qmetrum</span> · Measurement, not prediction.
        </footer>
      </main>
    </div>
  );
}

function PairCard({ pair, activeWin }: { pair: CorrelationPair; activeWin: number }) {
  const stat = pair.windows[String(activeWin)];
  const series = pair.series[String(activeWin)] ?? [];
  const note = PAIR_NOTES[pair.pair_key];
  if (!stat) return null;
  const color = corrColor(stat.pearson);
  return (
    <div className="rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-5 shadow-[var(--card-shadow)]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-[var(--text-primary)]">{pair.label}</p>
          <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
            {pair.symbol_a} · {pair.symbol_b} · {activeWin}-day
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold tabular-nums" style={{ color }}>
            {fmtCorr(stat.pearson)}
          </div>
          <div className="text-[10px] text-[var(--text-muted)]">
            Spearman {fmtCorr(stat.spearman)} · n={stat.n_obs}
          </div>
        </div>
      </div>
      <div className="mt-3">
        <CorrelationChart series={series} color={color} label={pair.label} height={150} />
      </div>
      {note && <p className="mt-2 text-[11px] italic text-[var(--text-muted)]">{note}</p>}
    </div>
  );
}

function ReplaySection() {
  const { data } = useQuery<CorrelationReplayResponse>({
    queryKey: ["public-correlation-replay"],
    queryFn: correlationApi.replay,
    staleTime: 60 * 60_000,
    refetchOnWindowFocus: false,
  });
  if (!data || data.status !== "ok" || !data.points?.length) return null;

  return (
    <section className="mt-10 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6 shadow-[var(--card-shadow)]">
      <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-[var(--coral)]">
        Has this ever mattered?
      </p>
      <h2 className="text-xl font-bold text-[var(--navy)]">When diversification stopped working</h2>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[var(--text-secondary)]">
        Two decades of the realized stock–bond correlation (green), against the drawdown of a
        60/40 portfolio (orange). Notice where the green line climbs above zero — stocks and bonds
        falling together — right as the 60/40 takes its deepest hits. This is realized history, not
        a forecast.
      </p>

      <div className="mt-5">
        <ReplayChart points={data.points} height={300} />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {(data.episodes ?? []).map((e) => (
          <div key={e.name} className="rounded-lg border border-[var(--card-border)] bg-[var(--content-bg)] p-4">
            <p className="text-sm font-semibold text-[var(--navy)]">{e.name}</p>
            <p className="mt-2 text-2xl font-bold tabular-nums" style={{ color: (e.corr ?? 0) > 0 ? CORAL : TEAL }}>
              {e.corr == null ? "—" : `${e.corr >= 0 ? "+" : ""}${e.corr.toFixed(2)}`}
            </p>
            <p className="text-[11px] text-[var(--text-muted)]">realized stock–bond correlation</p>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">
              60/40 fell <span className="font-semibold text-[var(--coral)]">{e.blend_drawdown_pct.toFixed(0)}%</span>
            </p>
          </div>
        ))}
      </div>

      <p className="mt-4 text-[11px] leading-relaxed text-[var(--text-muted)]">
        {data.start} to {data.as_of} · {data.window}-day rolling window · source {data.data_source ?? "—"}.
        The bond side is supposed to cushion equity drawdowns; a positive correlation is exactly when it cushions least.
      </p>
    </section>
  );
}

function SignupCard() {
  const [email, setEmail] = useState("");
  const mutation = useMutation({
    mutationFn: () => correlationApi.signup(email),
  });

  return (
    <section className="mt-10 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6">
      <h2 className="text-lg font-semibold text-[var(--navy)]">Get the weekly correlation note</h2>
      <p className="mt-1 text-sm text-[var(--text-secondary)]">
        A short weekly read on where cross-asset diversification is holding — and where it isn&apos;t.
        No spam.
      </p>
      {mutation.isSuccess ? (
        <p className="mt-4 text-sm font-medium text-[var(--teal)]">
          Thanks — you&apos;re on the list. We&apos;ll be in touch.
        </p>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (email.trim()) mutation.mutate();
          }}
          className="mt-4 flex flex-col gap-2 sm:flex-row"
        >
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@advisoryfirm.com"
            aria-label="Email address"
            className="flex-1 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--teal)]"
          />
          <button
            type="submit"
            disabled={mutation.isPending || !email.trim()}
            className="rounded-lg bg-[var(--btn-navy)] px-5 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {mutation.isPending ? "Adding…" : "Notify me"}
          </button>
        </form>
      )}
      {mutation.isError && (
        <p className="mt-2 text-xs text-[var(--coral)]">
          {(mutation.error as Error)?.message ?? "Something went wrong. Please try again."}
        </p>
      )}
    </section>
  );
}
