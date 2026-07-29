"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
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
import {
  portfolioApi,
  agentsApi,
  type VarBacktestResponse,
  type VarBacktestCompareResponse,
  type VarBacktestMethodResult,
  type VarBacktestExplainResponse,
} from "@/lib/api";
import { SourceDataPanel } from "@/components/shared/SourceDataPanel";

type Props = { portfolioId: string | number };
type View = "historical" | "mps_fan" | "compare";

const VIEW_LABEL: Record<View, string> = {
  historical: "Historical",
  mps_fan: "MPS fan",
  compare: "Compare",
};

// historical is instant; mps_fan refits the copula each day, so trim the window.
// Always request the highest-fidelity composition basis; the backend falls back
// to constant weights for portfolios without share quantities (and that fallback
// still hits the prewarmed constant cache).
const SINGLE_PAYLOAD: Record<"historical" | "mps_fan", Parameters<typeof portfolioApi.varBacktest>[1]> = {
  historical: { method: "historical", weight_mode: "drift" },
  mps_fan: { method: "mps_fan", n_backtest: 120, n_simulations: 400, weight_mode: "drift" },
};

const METHOD_COLOR: Record<string, string> = {
  historical: "#0F8B6E",
  parametric: "#3B6FB5",
  mps_d4: "#D85A30",
  mps_d8: "#D4920B",
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

function CompositionBadge({ mode }: { mode?: "constant" | "drift" }) {
  const drift = mode === "drift";
  return (
    <span
      title={drift
        ? "Buy-and-hold value weights (shares × price) — the realized composition of a held book"
        : "Current weights applied across the whole window — a VaR model-validation backtest, not a realized-book P&L backtest"}
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-semibold ${
        drift
          ? "bg-[var(--teal-light)] text-[var(--teal-muted)]"
          : "bg-[var(--content-bg)] text-[var(--text-secondary)] border border-[var(--card-border)]"
      }`}
    >
      {drift ? "Realized book · buy-and-hold" : "Model validation · current weights"}
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

function pct(x: number | null | undefined, digits = 2) {
  return x == null ? "—" : `${(x * 100).toFixed(digits)}%`;
}

function spinner(msg: string) {
  return (
    <div className="flex h-[300px] flex-col items-center justify-center gap-2 text-sm text-[var(--text-muted)]">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--card-border)] border-t-[var(--teal)]" />
      {msg}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Single-method chart: realized vs VaR threshold + breach markers
// --------------------------------------------------------------------------- //
function SingleChart({ data }: { data: VarBacktestResponse }) {
  const dates = data.series.date;
  const rows = data.series.realized_return.map((r, i) => {
    const realized = +(r * 100).toFixed(3);
    return {
      label: dates?.[i] ?? String(i),
      realized,
      var: +(data.series.var_threshold[i] * 100).toFixed(3),
      breachVal: data.series.breach[i] ? realized : null,
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
        <XAxis dataKey="label" tick={{ fontSize: 9, fill: "#8B95A2" }} interval={tickEvery}
          tickFormatter={(v: string) => (v.length >= 7 ? v.slice(0, 7) : v)} />
        <YAxis tick={{ fontSize: 10, fill: "#8B95A2" }} tickFormatter={(v) => `${v}%`} width={44} />
        <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
          // @ts-expect-error recharts Formatter typing quirk (matches ReturnsChart pattern)
          formatter={(value: number, name: string) => [`${Number(value ?? 0).toFixed(2)}%`, name]} />
        <Legend wrapperStyle={{ fontSize: 11 }} iconType="plainline" />
        <ReferenceLine y={0} stroke="#8B95A2" strokeWidth={1} />
        <Line type="monotone" dataKey="var" name="VaR 95 threshold" stroke="#D85A30" strokeWidth={1.5}
          strokeDasharray="4 3" dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="realized" name="Realized return" stroke="#3B6FB5" strokeWidth={1}
          dot={false} isAnimationActive={false} />
        <Scatter dataKey="breachVal" name="Breach" fill="#D85A30" isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function SingleView({ data, method }: { data: VarBacktestResponse; method: "historical" | "mps_fan" }) {
  return (
    <>
      <div className="flex flex-wrap gap-2">
        <Pill ok={!data.kupiec.reject} label="Kupiec POF" />
        <Pill ok={!data.christoffersen.conditional_coverage.reject} label="Christoffersen CC" />
        <Pill ok={!data.christoffersen.independence.reject} label="Independence" />
        <ZonePill zone={data.basel_traffic_light.zone} />
        <CompositionBadge mode={data.weight_mode} />
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile label="Exceptions" value={`${data.exceptions} / ${data.expected_exceptions}`}
          sub={`over ${data.n_observations} days`} warn={data.exceptions > data.expected_exceptions} />
        <Tile label="Breach rate" value={pct(data.breach_rate)} sub={`target ${pct(data.expected_breach_rate, 1)}`}
          warn={data.breach_rate > data.expected_breach_rate * 1.5} />
        <Tile label="Kupiec p-value" value={data.kupiec.p_value.toFixed(3)}
          sub={data.kupiec.reject ? `reject @ α=${data.alpha}` : "not rejected"} warn={data.kupiec.reject} />
        <Tile label="Expected shortfall"
          value={data.observed_expected_shortfall == null ? "—" : pct(data.observed_expected_shortfall)}
          sub="avg breach-day loss" />
      </div>
      <SingleChart data={data} />
      <div className="space-y-1 text-[11px] text-[var(--text-muted)]">
        <p>
          {VIEW_LABEL[method]} method · {Math.round(data.confidence * 100)}% confidence · {data.horizon_days}-day horizon
          {data.data_window ? ` · ${data.data_window.start} → ${data.data_window.end}` : ""}
          {data.cache?.hit ? " · cached" : ""}
        </p>
        {data.overlapping_windows && (
          <p className="text-[var(--amber)]">⚠ Horizon &gt; 1 uses overlapping windows; coverage tests assume independence.</p>
        )}
        {data.weight_mode_note && <p>Composition basis: {data.weight_mode_note}.</p>}
      </div>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Compare view: table + recommendation + multi-method VaR overlay
// --------------------------------------------------------------------------- //
function CompareChart({ data }: { data: VarBacktestCompareResponse }) {
  const ok = data.methods.filter((m) => m.status === "ok" && m.var_threshold);
  const dates = data.shared.dates;
  const rows = data.shared.realized_return.map((r, i) => {
    const row: Record<string, number | string | null> = {
      label: dates[i] ?? String(i),
      realized: +(r * 100).toFixed(3),
    };
    for (const m of ok) row[m.key] = +((m.var_threshold![i] ?? 0) * 100).toFixed(3);
    return row;
  });
  if (rows.length === 0) return null;
  const tickEvery = Math.max(1, Math.floor(rows.length / 6));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={rows} margin={{ top: 8, right: 10, left: 6, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F3" vertical={false} />
        <XAxis dataKey="label" tick={{ fontSize: 9, fill: "#8B95A2" }} interval={tickEvery}
          tickFormatter={(v: string) => (v.length >= 7 ? v.slice(0, 7) : v)} />
        <YAxis tick={{ fontSize: 10, fill: "#8B95A2" }} tickFormatter={(v) => `${v}%`} width={44} />
        <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
          // @ts-expect-error recharts Formatter typing quirk (matches ReturnsChart pattern)
          formatter={(value: number, name: string) => [`${Number(value ?? 0).toFixed(2)}%`, name]} />
        <Legend wrapperStyle={{ fontSize: 10 }} iconType="plainline" />
        <ReferenceLine y={0} stroke="#8B95A2" strokeWidth={1} />
        <Line type="monotone" dataKey="realized" name="Realized" stroke="#1A2B45" strokeWidth={1} dot={false} isAnimationActive={false} />
        {ok.map((m) => (
          <Line key={m.key} type="monotone" dataKey={m.key} name={m.label}
            stroke={METHOD_COLOR[m.key] ?? "#8B95A2"} strokeWidth={1.25} strokeDasharray="4 3"
            dot={false} isAnimationActive={false} />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function Verdict({ m }: { m: VarBacktestMethodResult }) {
  if (m.status === "skipped")
    return <span className="text-[var(--text-muted)]">skipped</span>;
  return (
    <span className={`font-semibold ${m.model_passes ? "text-[var(--teal-muted)]" : "text-[var(--coral)]"}`}>
      {m.model_passes ? "PASS" : "FAIL"}
    </span>
  );
}

function CompareView({ data }: { data: VarBacktestCompareResponse }) {
  const recKey = data.recommended?.key;
  return (
    <>
      <div className="flex justify-end">
        <CompositionBadge mode={data.weight_mode} />
      </div>
      {data.recommended ? (
        <div className="rounded-lg bg-[var(--teal-light)] px-4 py-3 text-sm text-[var(--teal-muted)]">
          ✓ Recommended: <span className="font-semibold">{data.recommended.label}</span> — {data.recommended.why}
        </div>
      ) : (
        <div className="rounded-lg bg-[var(--coral-light)] px-4 py-3 text-sm text-[var(--coral)]">
          ⚠ No method passed VaR 95 coverage on this window.
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              <th className="py-2 pr-3">Method</th>
              <th className="py-2 px-3">Breaches</th>
              <th className="py-2 px-3">Breach rate</th>
              <th className="py-2 px-3">Kupiec p</th>
              <th className="py-2 px-3">Christoffersen p</th>
              <th className="py-2 px-3">Basel</th>
              <th className="py-2 pl-3">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {data.methods.map((m) => {
              const rec = m.key === recKey;
              if (m.status === "skipped") {
                return (
                  <tr key={m.key} className="border-t border-[var(--card-border)] text-[var(--text-muted)]">
                    <td className="py-2 pr-3 font-medium">{m.label}</td>
                    <td className="py-2 px-3 italic" colSpan={6}>skipped — {m.reason}</td>
                  </tr>
                );
              }
              return (
                <tr key={m.key}
                  className={`border-t border-[var(--card-border)] ${rec ? "bg-[var(--teal-light)]/40" : ""}`}>
                  <td className="py-2 pr-3 font-medium text-[var(--navy)]">
                    {rec && <span className="mr-1 text-[var(--teal)]">★</span>}{m.label}
                  </td>
                  <td className="py-2 px-3">{m.exceptions} / {m.expected_exceptions}</td>
                  <td className={`py-2 px-3 ${(m.breach_rate ?? 0) > (m.expected_breach_rate ?? 0.05) * 1.5 ? "text-[var(--coral)]" : ""}`}>
                    {pct(m.breach_rate)}
                  </td>
                  <td className={`py-2 px-3 ${m.kupiec?.reject ? "text-[var(--coral)]" : ""}`}>{m.kupiec?.p_value.toFixed(3)}</td>
                  <td className={`py-2 px-3 ${m.christoffersen_cc?.reject ? "text-[var(--coral)]" : ""}`}>{m.christoffersen_cc?.p_value.toFixed(3)}</td>
                  <td className="py-2 px-3 capitalize">{m.basel_zone}</td>
                  <td className="py-2 pl-3"><Verdict m={m} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <CompareChart data={data} />

      <div className="space-y-1 text-[11px] text-[var(--text-muted)]">
        <p>
          {Math.round(data.confidence * 100)}% confidence · {data.horizon_days}-day horizon · {data.n_observations} obs
          {data.data_window ? ` · ${data.data_window.start} → ${data.data_window.end}` : ""}
          {data.cache?.hit ? " · cached" : ""}
        </p>
        <p>All methods scored on the identical date sample. The MPS d-sweep shows whether finer return binning corrects the anti-conservative d=4 tails.</p>
        {data.weight_mode_note && <p>Composition basis: {data.weight_mode_note}.</p>}
      </div>
    </>
  );
}

// --------------------------------------------------------------------------- //
// AI risk read — plain-English interpretation of the comparison (var_backtest_explain
// agent). Demonstrates the better agent-UI pattern: structured render (no prose
// blob), loading skeleton, humanized error, copy, source-data panel, inline disclaimer.
// --------------------------------------------------------------------------- //
function ExplainPanel({ portfolioId }: { portfolioId: string | number }) {
  const [data, setData] = useState<VarBacktestExplainResponse | null>(null);
  const m = useMutation({
    mutationFn: () => agentsApi.varBacktestExplain(portfolioId),
    onSuccess: setData,
  });
  const err = m.error as { response?: { data?: { detail?: string } }; message?: string } | null;
  const errMsg = err ? (err.response?.data?.detail ?? err.message ?? "Explanation unavailable") : null;
  const copy = () => {
    if (!data) return;
    navigator.clipboard?.writeText(
      [data.headline, "", data.assessment, "",
        ...data.method_notes.map((n) => `• ${n.method}: ${n.note}`),
        ...data.watch.map((w) => `⚠ ${w}`)].join("\n"),
    );
  };
  return (
    <div className="rounded-lg border border-[var(--card-border)] p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">AI risk read</h3>
          <p className="text-[11px] text-[var(--text-secondary)]">Plain-English interpretation of the coverage results.</p>
        </div>
        <div className="flex items-center gap-2">
          {data && (
            <button onClick={copy} className="text-[11px] font-medium text-[var(--text-secondary)] hover:text-[var(--navy)]">
              Copy
            </button>
          )}
          <button
            onClick={() => m.mutate()}
            disabled={m.isPending}
            className="text-xs font-medium bg-[var(--btn-navy)] text-white px-3 py-1.5 rounded-lg hover:opacity-90 disabled:opacity-50"
          >
            {m.isPending ? "Reading…" : data ? "Refresh" : "Explain this backtest"}
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
        <div className="space-y-3">
          <p className="text-sm font-semibold text-[var(--navy)]">{data.headline}</p>
          <p className="text-sm leading-relaxed text-[var(--text-primary)]">{data.assessment}</p>
          {data.method_notes.length > 0 && (
            <ul className="space-y-1">
              {data.method_notes.map((n, i) => (
                <li key={i} className="text-xs text-[var(--text-secondary)]">
                  <span className="font-medium text-[var(--text-primary)]">{n.method}:</span> {n.note}
                </li>
              ))}
            </ul>
          )}
          {data.watch.length > 0 && (
            <div className="space-y-0.5">
              {data.watch.map((w, i) => (
                <p key={i} className="text-xs text-[var(--amber)]">⚠ {w}</p>
              ))}
            </div>
          )}
          <SourceDataPanel data={data.source_data} />
          <p className="text-[10px] text-[var(--text-muted)]">
            {data.cached ? "Cached · " : ""}{data.model} · {data.disclaimer}
          </p>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
export function VarBacktestCard({ portfolioId }: Props) {
  const [view, setView] = useState<View>("historical");

  const single = useQuery({
    queryKey: ["portfolio-var-backtest", portfolioId, view],
    queryFn: () => portfolioApi.varBacktest(portfolioId, SINGLE_PAYLOAD[view as "historical" | "mps_fan"]),
    enabled: view !== "compare",
    staleTime: 1000 * 60 * 30,
    retry: false,
  });

  const compare = useQuery({
    queryKey: ["portfolio-var-backtest-compare", portfolioId],
    queryFn: () => portfolioApi.varBacktestCompare(portfolioId, { weight_mode: "drift" }),
    enabled: view === "compare",
    staleTime: 1000 * 60 * 30,
    retry: false,
  });

  const active = view === "compare" ? compare : single;
  const passes = view !== "compare" ? (single.data as VarBacktestResponse | undefined)?.model_passes : undefined;

  return (
    <div className="q-card p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">VaR 95 Backtest</h2>
          <p className="text-xs text-[var(--text-secondary)]">
            As-of replay scored with Kupiec &amp; Christoffersen coverage tests
          </p>
        </div>
        <div className="flex items-center gap-3">
          {view !== "compare" && single.data && (
            <span className={`rounded-full px-3 py-1 text-xs font-bold ${
              passes ? "bg-[var(--teal-light)] text-[var(--teal-muted)]" : "bg-[var(--coral-light)] text-[var(--coral)]"
            }`}>
              {passes ? "MODEL PASSES" : "MODEL FAILS"}
            </span>
          )}
          <div className="inline-flex rounded-lg border border-[var(--card-border)] p-0.5">
            {(Object.keys(VIEW_LABEL) as View[]).map((v) => (
              <button key={v} onClick={() => setView(v)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                  view === v ? "bg-[var(--btn-navy)] text-white" : "text-[var(--text-secondary)] hover:text-[var(--navy)]"
                }`}>
                {VIEW_LABEL[v]}
              </button>
            ))}
          </div>
        </div>
      </div>

      {active.isLoading &&
        spinner(view === "compare" ? "Comparing methods (MPS sweep refits per day) — ~30s…"
          : view === "mps_fan" ? "Refitting the MPS fan per day — this takes ~15s…" : "Running backtest…")}

      {active.isError && !active.isLoading && (
        <div className="rounded-lg bg-[var(--coral-light)] px-4 py-3 text-sm text-[var(--coral)]">
          {(active.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            "Backtest unavailable (insufficient price history or too few assets)."}
        </div>
      )}

      {view !== "compare" && single.data && !single.isLoading && (
        <SingleView data={single.data} method={view as "historical" | "mps_fan"} />
      )}
      {view === "compare" && compare.data && !compare.isLoading && (
        <>
          <CompareView data={compare.data} />
          <ExplainPanel portfolioId={portfolioId} />
        </>
      )}
    </div>
  );
}
