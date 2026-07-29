"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  portfolioApi,
  type DrawdownAllocationResponse,
  type AllocationMethod,
} from "@/lib/api";

type Props = {
  portfolioId: string | number;
  onApply?: (weights: Record<string, number>, label: string) => void | Promise<void>;
};

function pct(x: number | null | undefined, digits = 1) {
  return x == null || Number.isNaN(x) ? "—" : `${(x * 100).toFixed(digits)}%`;
}
function num(x: number | null | undefined, digits = 2) {
  return x == null || Number.isNaN(x) ? "—" : x.toFixed(digits);
}

export function DrawdownAllocationCard({ portfolioId, onApply }: Props) {
  const [selected, setSelected] = useState("drawdown_mgd");
  const [apply, setApply] = useState<{ status: "idle" | "applying" | "done" | "error"; msg?: string }>({
    status: "idle",
  });

  const run = useMutation({
    mutationFn: () => portfolioApi.drawdownAllocation(portfolioId, { period: "5y" }),
  });
  const data: DrawdownAllocationResponse | undefined = run.data;

  const selMethod: AllocationMethod | undefined =
    data?.methods.find((m) => m.key === selected) ?? data?.methods[0];

  return (
    <div className="q-card p-5 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            Drawdown-Managed Allocation
          </h2>
          <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
            Suggested weights from several risk-based methods, each with its backtested profile.
          </p>
        </div>
        <button
          onClick={() => { setApply({ status: "idle" }); run.mutate(); }}
          disabled={run.isPending}
          className="rounded-lg bg-[var(--teal)] px-4 py-2 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {run.isPending ? "Computing…" : data ? "Recompute" : "Run allocation"}
        </button>
      </div>

      {/* Honest framing banner */}
      <div className="rounded-lg border border-[var(--amber)]/30 bg-[var(--amber-light)] px-3 py-2 text-[11px] leading-relaxed text-[var(--text-secondary)]">
        <span className="font-semibold text-[var(--amber)]">How to read this:</span> higher Sharpe = better
        risk-adjusted return; a less-negative Max Drawdown / CDaR = smaller losses. The{" "}
        <span className="font-semibold">drawdown-managed</span> method targets{" "}
        <span className="font-semibold">smaller drawdowns, not higher returns</span> — it typically
        trades a little Sharpe and more turnover for a shallower drawdown. Backtested across regimes it
        does <span className="font-semibold">not</span> beat inverse-vol on risk-adjusted return. Pick a
        method to fit the client&apos;s risk preference, not to chase alpha.
      </div>

      {run.isError && (
        <p className="text-xs text-[var(--coral)]">
          {(run.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            "Could not compute allocation. Portfolio needs ≥2 holdings with overlapping price history."}
        </p>
      )}

      {!data && !run.isPending && !run.isError && (
        <p className="py-6 text-center text-xs text-[var(--text-muted)]">
          Run the allocation to compare methods on this portfolio&apos;s holdings.
        </p>
      )}

      {run.isPending && (
        <div className="flex h-[160px] flex-col items-center justify-center gap-2 text-sm text-[var(--text-muted)]">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--card-border)] border-t-[var(--teal)]" />
          Backtesting methods point-in-time…
        </div>
      )}

      {data && (
        <div className="space-y-4">
          <div className="text-[11px] text-[var(--text-muted)]">
            {data.n_assets} holdings · backtest {data.data_window.years}y ({data.data_window.start} →{" "}
            {data.data_window.end}) · net of {data.params.cost_bps}bps · monthly rebalance
          </div>

          {/* Method comparison table */}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                  <th className="py-2 text-left font-semibold">Method</th>
                  <th className="py-2 text-right font-semibold">Sharpe</th>
                  <th className="py-2 text-right font-semibold">Max DD</th>
                  <th className="py-2 text-right font-semibold">CDaR 95%</th>
                  <th className="py-2 text-right font-semibold">Turnover/yr</th>
                </tr>
              </thead>
              <tbody>
                {data.methods.map((m) => {
                  const p = m.profile;
                  const isSel = m.key === selected;
                  const isDd = m.key === "drawdown_mgd";
                  return (
                    <tr
                      key={m.key}
                      onClick={() => { setSelected(m.key); setApply({ status: "idle" }); }}
                      className={`cursor-pointer border-t border-[var(--card-border)] transition-colors ${
                        isSel ? "bg-[var(--teal-light)]" : "hover:bg-[var(--content-bg)]"
                      }`}
                    >
                      <td className="py-2.5 text-left">
                        <span className={`font-semibold ${isDd ? "text-[var(--teal-muted)]" : "text-[var(--navy)]"}`}>
                          {m.label}
                        </span>
                      </td>
                      <td className="py-2.5 text-right font-semibold text-[var(--navy)]">{num(p?.sharpe)}</td>
                      <td className="py-2.5 text-right text-[var(--coral)]">{pct(p?.max_drawdown)}</td>
                      <td className="py-2.5 text-right text-[var(--coral)]">{pct(p?.cdar95)}</td>
                      <td className="py-2.5 text-right text-[var(--text-secondary)]">{num(p?.turnover_per_yr)}×</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Selected method: note + suggested weights */}
          {selMethod && (
            <div className="rounded-lg bg-[var(--content-bg)] p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-semibold text-[var(--navy)]">{selMethod.label}</span>
                {onApply && (
                  <button
                    onClick={async () => {
                      setApply({ status: "applying" });
                      try {
                        await onApply(selMethod.weights, selMethod.label);
                        setApply({ status: "done", msg: `${selMethod.label} weights saved as the portfolio's targets` });
                      } catch (e) {
                        setApply({
                          status: "error",
                          msg: (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
                            ?? "Failed to apply — the portfolio was not changed.",
                        });
                      }
                    }}
                    disabled={apply.status === "applying"}
                    className="rounded-lg border border-[var(--teal)] px-3 py-1.5 text-xs font-semibold text-[var(--teal-muted)] hover:bg-[var(--teal-light)] disabled:opacity-50"
                  >
                    {apply.status === "applying" ? "Applying…" : apply.status === "done" ? "Applied ✓" : "Apply these weights"}
                  </button>
                )}
              </div>
              {onApply && apply.status !== "done" && apply.status !== "error" && (
                <p className="text-[10px] text-[var(--text-muted)]">
                  Applying saves these as the portfolio&apos;s <span className="font-semibold">target weights</span> (updates the
                  holdings and risk metrics above) — it does not place any trades.
                </p>
              )}
              {apply.status === "done" && (
                <p className="text-[11px] font-medium text-[var(--positive)]">
                  ✓ {apply.msg}. The holdings table and risk metrics above have refreshed.
                </p>
              )}
              {apply.status === "error" && (
                <p className="text-[11px] font-medium text-[var(--coral)]">{apply.msg}</p>
              )}
              <p className="text-[11px] leading-relaxed text-[var(--text-secondary)]">{selMethod.note}</p>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[360px] text-xs">
                  <thead>
                    <tr className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                      <th className="py-1.5 text-left font-semibold">Holding</th>
                      <th className="py-1.5 text-right font-semibold">Current</th>
                      <th className="py-1.5 text-right font-semibold">Suggested</th>
                      <th className="py-1.5 text-right font-semibold">Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.tickers.map((t) => {
                      const cur = data.current_weights?.[t] ?? 0;
                      const sug = selMethod.weights[t] ?? 0;
                      const d = sug - cur;
                      return (
                        <tr key={t} className="border-t border-[var(--card-border)]">
                          <td className="py-1.5 text-left font-semibold text-[var(--navy)]">{t}</td>
                          <td className="py-1.5 text-right text-[var(--text-secondary)]">{pct(cur)}</td>
                          <td className="py-1.5 text-right font-semibold text-[var(--navy)]">{pct(sug)}</td>
                          <td className={`py-1.5 text-right ${d > 0.0005 ? "text-[var(--positive)]" : d < -0.0005 ? "text-[var(--negative)]" : "text-[var(--text-muted)]"}`}>
                            {d > 0 ? "+" : ""}{pct(d)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <p className="text-[10px] leading-relaxed text-[var(--text-muted)]">{data.note}</p>
        </div>
      )}
    </div>
  );
}
