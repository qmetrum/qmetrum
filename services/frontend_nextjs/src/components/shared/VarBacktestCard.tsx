"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  Legend,
} from "recharts";
import { portfolioApi, type VarBacktestResponse } from "@/lib/api";

type Props = { portfolioId: string | number };
type Method = "historical" | "mps_fan";

const METHOD_LABEL: Record<Method, string> = {
  historical: "Historical",
  mps_fan: "MPS fan",
};

// historical is instant; mps_fan refits the copula each day, so trim the
// window from the 250 default to keep the round-trip ~15s.
const METHOD_PAYLOAD: Record<Method, Parameters<typeof portfolioApi.varBacktest>[1]> = {
  historical: { method: "historical" },
  mps_fan: { method: "mps_fan", n_backtest: 120, n_simulations: 400 },
};

function Pill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${
        ok ? "bg-[var(--teal-light)] text-[var(--teal-muted)]" : "bg-[var(--coral-light)] text-[var(--coral)]"
      }`}
    >
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? "bg-[var(--teal)]" : "bg-[var(--coral)]"}`} />
      {label}: {ok ? "PASS" : "FAIL"}
    </span>
  );
}

function ZonePill({ zone }: { zone: "green" | "yellow" | "red" }) {
  const style =
    zone === "green"
      ? "bg-[var(--teal-light)] text-[var(--teal-muted)]"
      : zone === "yellow"
        ? "bg-[var(--amber-light)] text-[var(--amber)]"
        : "bg-[var(--coral-light)] text-[var(--coral)]";
  const dot = zone === "green" ? "bg-[var(--teal)]" : zone === "yellow" ? "bg-[var(--amber)]" : "bg-[var(--coral)]";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${style}`}>
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot}`} />
      Basel: {zone.toUpperCase()}
    </span>
  );
}

function Tile({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div className="rounded-lg bg-[var(--content-bg)] px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
      <div className={`text-lg font-bold ${warn ? "text-[var(--coral)]" : "text-[var(--navy)]"}`}>{value}</div>
      {sub && <div className="text-[11px] text-[var(--text-secondary)]">{sub}</div>}
    </div>
  );
}

function pct(x: number, digits = 2) {
  return `${(x * 100).toFixed(digits)}%`;
}

function BacktestChart({ data }: { data: VarBacktestResponse }) {
  const dates = data.series.date;
  const rows = data.series.realized_return.map((r, i) => {
    const realized = +(r * 100).toFixed(3);
    const breach = data.series.breach[i];
    return {
      label: dates?.[i] ?? String(i),
      realized,
      var: +(data.series.var_threshold[i] * 100).toFixed(3),
      breachVal: breach ? realized : null, // Scatter skips null points
    };
  });
  if (rows.length === 0) {
    return <div className="flex h-[240px] items-center justify-center text-sm text-[var(--text-muted)]">No data</div>;
  }
  const tickEvery = Math.max(1, Math.floor(rows.length / 6));

  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={rows} margin={{ top: 8, right: 10, left: 6, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F3" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 9, fill: "#8B95A2" }}
          interval={tickEvery}
          tickFormatter={(v: string) => (v.length >= 7 ? v.slice(0, 7) : v)}
        />
        <YAxis tick={{ fontSize: 10, fill: "#8B95A2" }} tickFormatter={(v) => `${v}%`} width={44} />
        <Tooltip
          contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
          // @ts-expect-error recharts Formatter typing quirk (matches ReturnsChart pattern)
          formatter={(value: number, name: string) => [`${Number(value ?? 0).toFixed(2)}%`, name]}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} iconType="plainline" />
        <ReferenceLine y={0} stroke="#8B95A2" strokeWidth={1} />
        <Line
          type="monotone"
          dataKey="var"
          name="VaR 95 threshold"
          stroke="#D85A30"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          dot={false}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="realized"
          name="Realized return"
          stroke="#3B6FB5"
          strokeWidth={1}
          dot={false}
          isAnimationActive={false}
        />
        <Scatter dataKey="breachVal" name="Breach" fill="#D85A30" isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function VarBacktestCard({ portfolioId }: Props) {
  const [method, setMethod] = useState<Method>("historical");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["portfolio-var-backtest", portfolioId, method],
    queryFn: () => portfolioApi.varBacktest(portfolioId, METHOD_PAYLOAD[method]),
    staleTime: 1000 * 60 * 30,
    retry: false,
  });

  return (
    <div className="q-card p-5 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">VaR 95 Backtest</h2>
          <p className="text-xs text-[var(--text-secondary)]">
            As-of replay scored with Kupiec &amp; Christoffersen coverage tests
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data && (
            <span
              className={`rounded-full px-3 py-1 text-xs font-bold ${
                data.model_passes ? "bg-[var(--teal-light)] text-[var(--teal-muted)]" : "bg-[var(--coral-light)] text-[var(--coral)]"
              }`}
            >
              {data.model_passes ? "MODEL PASSES" : "MODEL FAILS"}
            </span>
          )}
          {/* Method toggle */}
          <div className="inline-flex rounded-lg border border-[var(--card-border)] p-0.5">
            {(Object.keys(METHOD_LABEL) as Method[]).map((m) => (
              <button
                key={m}
                onClick={() => setMethod(m)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                  method === m ? "bg-[var(--navy)] text-white" : "text-[var(--text-secondary)] hover:text-[var(--navy)]"
                }`}
              >
                {METHOD_LABEL[m]}
              </button>
            ))}
          </div>
        </div>
      </div>

      {isLoading && (
        <div className="flex h-[300px] flex-col items-center justify-center gap-2 text-sm text-[var(--text-muted)]">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--card-border)] border-t-[var(--teal)]" />
          {method === "mps_fan" ? "Refitting the MPS fan per day — this takes ~15s…" : "Running backtest…"}
        </div>
      )}

      {isError && !isLoading && (
        <div className="rounded-lg bg-[var(--coral-light)] px-4 py-3 text-sm text-[var(--coral)]">
          {(error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            "Backtest unavailable (insufficient price history or too few assets)."}
        </div>
      )}

      {data && !isLoading && (
        <>
          {/* Coverage verdict pills */}
          <div className="flex flex-wrap gap-2">
            <Pill ok={!data.kupiec.reject} label="Kupiec POF" />
            <Pill ok={!data.christoffersen.conditional_coverage.reject} label="Christoffersen CC" />
            <Pill ok={!data.christoffersen.independence.reject} label="Independence" />
            <ZonePill zone={data.basel_traffic_light.zone} />
          </div>

          {/* Metric tiles */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Tile
              label="Exceptions"
              value={`${data.exceptions} / ${data.expected_exceptions}`}
              sub={`over ${data.n_observations} days`}
              warn={data.exceptions > data.expected_exceptions}
            />
            <Tile
              label="Breach rate"
              value={pct(data.breach_rate)}
              sub={`target ${pct(data.expected_breach_rate, 1)}`}
              warn={data.breach_rate > data.expected_breach_rate * 1.5}
            />
            <Tile
              label="Kupiec p-value"
              value={data.kupiec.p_value.toFixed(3)}
              sub={data.kupiec.reject ? `reject @ α=${data.alpha}` : "not rejected"}
              warn={data.kupiec.reject}
            />
            <Tile
              label="Expected shortfall"
              value={data.observed_expected_shortfall == null ? "—" : pct(data.observed_expected_shortfall)}
              sub="avg breach-day loss"
            />
          </div>

          {/* Realized vs VaR overlay */}
          <BacktestChart data={data} />

          {/* Footnotes */}
          <div className="space-y-1 text-[11px] text-[var(--text-muted)]">
            <p>
              {METHOD_LABEL[method]} method · {Math.round(data.confidence * 100)}% confidence ·{" "}
              {data.horizon_days}-day horizon
              {data.data_window ? ` · ${data.data_window.start} → ${data.data_window.end}` : ""}
              {data.cache?.hit ? " · cached" : ""}
            </p>
            {data.overlapping_windows && (
              <p className="text-[var(--amber)]">
                ⚠ Horizon &gt; 1 uses overlapping windows; coverage tests assume independent observations.
              </p>
            )}
            <p>Position weights are applied across the whole window (no historical weight versioning).</p>
          </div>
        </>
      )}
    </div>
  );
}
