"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  reportsApi,
  portfolioListApi,
  type PortfolioResponse,
  type ReportAsset,
} from "@/lib/api";
import { useBranding } from "@/components/providers/BrandingProvider";

const REPORT_TYPES = [
  {
    key: "quarterly",
    title: "Quarterly Review",
    desc: "Full risk intelligence report with ensemble forecast, GARCH volatility, scenario analysis, and holdings breakdown.",
    color: "#0F8B6E",
    bg: "#E6F5F0",
  },
  {
    key: "onboarding",
    title: "New Client Assessment",
    desc: "Risk alignment report comparing client's stated tolerance to actual portfolio volatility.",
    color: "#2B7ACC",
    bg: "#EAF2FB",
  },
  {
    key: "market-event",
    title: "Market Event Briefing",
    desc: "Sent during market turbulence. Shows portfolio impact vs. benchmark with forward outlook.",
    color: "#D85A30",
    bg: "#FDECEC",
  },
  {
    key: "rebalancing",
    title: "Rebalancing Proposal",
    desc: "Before/after risk comparison with trade list, scenario stress test, and tax considerations.",
    color: "#D4920B",
    bg: "#FDF5E6",
  },
  {
    key: "year-end",
    title: "Year-End Review",
    desc: "Annual performance review with monthly heatmap, risk evolution, model accuracy, and year-ahead themes.",
    color: "#0B1D3A",
    bg: "#F0F2F5",
  },
];

export default function ReportsPage() {
  const branding = useBranding();
  const [selected, setSelected] = useState<string | null>(null);
  const [portfolioId, setPortfolioId] = useState<string>("");
  const [generating, setGenerating] = useState(false);

  // Extra fields — initialized from branding context
  const [advisorName, setAdvisorName] = useState(branding.advisorName);
  const [firmName, setFirmName] = useState(branding.firmName);
  const [portfolioValue, setPortfolioValue] = useState("");
  const [riskTolerance, setRiskTolerance] = useState("Moderate");
  const [targetVol, setTargetVol] = useState("10");
  const [eventName, setEventName] = useState("");
  const [eventDate, setEventDate] = useState("");
  const [eventSummary, setEventSummary] = useState("");
  const [rationale, setRationale] = useState("");
  const [taxNotes, setTaxNotes] = useState("");
  const [reviewYear, setReviewYear] = useState(String(new Date().getFullYear() - 1));
  const [valueStart, setValueStart] = useState("");
  const [valueEnd, setValueEnd] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Rebalancing: proposed allocation as editable percents, keyed by ticker.
  const [proposedWeights, setProposedWeights] = useState<Record<string, string>>({});

  const { data: portfolios } = useQuery({
    queryKey: ["portfolios-list"],
    queryFn: portfolioListApi.list,
  });

  // Preselect from /reports?portfolio=..&type=.. (links on the Clients page).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const pid = params.get("portfolio");
    const type = params.get("type");
    if (pid) setPortfolioId(pid);
    if (type && REPORT_TYPES.some((r) => r.key === type)) setSelected(type);
  }, []);

  const selectedPortfolio = (portfolios ?? []).find(
    (p: PortfolioResponse) => String(p.portfolio_id) === portfolioId
  );

  // Seed the proposed allocation from the current one whenever the portfolio
  // changes; the advisor then edits the targets.
  useEffect(() => {
    if (!selectedPortfolio) return;
    setProposedWeights(
      Object.fromEntries(
        (selectedPortfolio.assets ?? []).map((a) => [
          a.ticker,
          ((a.weight ?? 0) * 100).toFixed(1),
        ]),
      ),
    );
  }, [selectedPortfolio]);

  const proposedSum = Object.values(proposedWeights).reduce(
    (acc, v) => acc + (parseFloat(v) || 0), 0);
  const proposedChanged = (selectedPortfolio?.assets ?? []).some(
    (a) => Math.abs((parseFloat(proposedWeights[a.ticker] ?? "0") || 0) - (a.weight ?? 0) * 100) > 0.05,
  );

  // Per-type required inputs; the backend refuses to fabricate missing ones.
  const missingInputs: string[] = [];
  if (!portfolioId) missingInputs.push("portfolio");
  if (selected !== "year-end" && !(Number(portfolioValue) > 0)) missingInputs.push("portfolio value");
  if (selected === "market-event") {
    if (!eventName.trim()) missingInputs.push("event name");
    if (!eventDate) missingInputs.push("event date");
    if (!eventSummary.trim()) missingInputs.push("event summary");
  }
  if (selected === "onboarding" && !(parseFloat(targetVol) > 0)) missingInputs.push("target vol");
  if (selected === "rebalancing" && !(proposedSum > 0)) missingInputs.push("proposed weights");

  async function generate() {
    if (!selected || !selectedPortfolio || missingInputs.length > 0) return;
    setGenerating(true);
    setError(null);

    const assets: ReportAsset[] = (selectedPortfolio.assets ?? []).map((a) => ({
      ticker: a.ticker,
      weight: a.weight ?? 0,
    }));
    const base = {
      client_name: selectedPortfolio.name ?? `Portfolio #${selectedPortfolio.portfolio_id}`,
      advisor_name: advisorName,
      firm_name: firmName,
      assets,
      portfolio_value: portfolioValue ? Number(portfolioValue) : undefined,
    };

    try {
      switch (selected) {
        case "quarterly":
          await reportsApi.quarterly(base);
          break;
        case "onboarding":
          await reportsApi.onboarding({
            ...base,
            risk_tolerance: riskTolerance,
            target_vol: parseFloat(targetVol) / 100,
          });
          break;
        case "market-event":
          await reportsApi.marketEvent({
            ...base,
            event_name: eventName,
            event_date: eventDate,
            event_summary: eventSummary,
          });
          break;
        case "rebalancing":
          await reportsApi.rebalancing({
            ...base,
            current_assets: assets,
            proposed_assets: assets.map((a) => ({
              ticker: a.ticker,
              weight: (parseFloat(proposedWeights[a.ticker] ?? "0") || 0) / 100,
            })),
            rationale,
            ...(taxNotes.trim() ? { tax_considerations: taxNotes } : {}),
          });
          break;
        case "year-end":
          await reportsApi.yearEnd({
            client_name: base.client_name,
            advisor_name: base.advisor_name,
            firm_name: base.firm_name,
            assets,
            review_year: parseInt(reviewYear),
            ...(Number(valueStart) > 0 ? { portfolio_value_start: Number(valueStart) } : {}),
            ...(Number(valueEnd) > 0 ? { portfolio_value_end: Number(valueEnd) } : {}),
          });
          break;
      }
    } catch (e) {
      // The backend refuses to fabricate missing data; show its reason.
      const err = e as { response?: { data?: unknown }; message?: string };
      let detail: unknown;
      const data = err.response?.data;
      if (data instanceof Blob) {
        try { detail = JSON.parse(await data.text())?.detail; } catch { /* not JSON */ }
      } else if (data && typeof data === "object") {
        detail = (data as { detail?: unknown }).detail;
      }
      setError(
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? String((detail[0] as { msg?: string } | undefined)?.msg ?? "Invalid request")
            : err.message ?? "Report generation failed",
      );
    } finally {
      setGenerating(false);
    }
  }

  const inputCls =
    "w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--teal)]";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--navy)]">Report Center</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Generate professional PDF reports for client meetings
        </p>
      </div>

      {/* Report type selector */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {REPORT_TYPES.map((rt) => (
          <button
            key={rt.key}
            onClick={() => setSelected(rt.key)}
            className={`q-card p-4 text-left transition-all ${
              selected === rt.key
                ? "ring-2 ring-offset-1"
                : "hover:shadow-md"
            }`}
            style={{
              borderColor: selected === rt.key ? rt.color : undefined,
              // @ts-expect-error CSS custom property
              "--tw-ring-color": rt.color,
            }}
          >
            <div
              className="mb-2 flex h-8 w-8 items-center justify-center rounded-lg"
              style={{ backgroundColor: rt.bg }}
            >
              <div className="h-3 w-3 rounded-full" style={{ backgroundColor: rt.color }} />
            </div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">{rt.title}</h3>
            <p className="mt-1 text-[11px] leading-snug text-[var(--text-muted)]">{rt.desc}</p>
          </button>
        ))}
      </div>

      {/* Configuration form */}
      {selected && (
        <div className="q-card p-6 space-y-4 max-w-2xl">
          <h2 className="text-base font-semibold text-[var(--navy)]">
            Configure: {REPORT_TYPES.find((r) => r.key === selected)?.title}
          </h2>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Client Portfolio</label>
              <select value={portfolioId} onChange={(e) => setPortfolioId(e.target.value)} className={inputCls}>
                <option value="">Select...</option>
                {(portfolios ?? []).map((p: PortfolioResponse) => (
                  <option key={p.portfolio_id} value={String(p.portfolio_id)}>
                    {p.name ?? `Portfolio #${p.portfolio_id}`}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Portfolio Value ($)</label>
              <input value={portfolioValue} onChange={(e) => setPortfolioValue(e.target.value)} placeholder="e.g. 2450000" className={inputCls} />
            </div>
            <div>
              <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Advisor Name</label>
              <input value={advisorName} onChange={(e) => setAdvisorName(e.target.value)} className={inputCls} />
            </div>
            <div>
              <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Firm Name</label>
              <input value={firmName} onChange={(e) => setFirmName(e.target.value)} className={inputCls} />
            </div>
          </div>

          {/* Conditional fields */}
          {selected === "onboarding" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Risk Tolerance</label>
                <select value={riskTolerance} onChange={(e) => setRiskTolerance(e.target.value)} className={inputCls}>
                  <option>Conservative</option>
                  <option>Moderate</option>
                  <option>Growth</option>
                  <option>Aggressive</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Target Vol (%)</label>
                <input value={targetVol} onChange={(e) => setTargetVol(e.target.value)} type="number" className={inputCls} />
              </div>
            </div>
          )}

          {selected === "market-event" && (
            <div className="space-y-3">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Event Name</label>
                  <input value={eventName} onChange={(e) => setEventName(e.target.value)} placeholder="e.g. Fed Rate Decision" className={inputCls} />
                </div>
                <div>
                  <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Event Date</label>
                  <input value={eventDate} onChange={(e) => setEventDate(e.target.value)} type="date" className={inputCls} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Event Summary</label>
                <textarea value={eventSummary} onChange={(e) => setEventSummary(e.target.value)} rows={3} className={inputCls} placeholder="Brief description of the market event..." />
              </div>
            </div>
          )}

          {selected === "rebalancing" && (
            <div className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">
                  Proposed Allocation (%)
                </label>
                {!selectedPortfolio ? (
                  <p className="text-xs text-[var(--text-muted)]">Select a portfolio to edit the target weights.</p>
                ) : (
                  <div className="space-y-1.5">
                    {(selectedPortfolio.assets ?? []).map((a) => (
                      <div key={a.ticker} className="flex items-center gap-3">
                        <span className="w-16 text-xs font-semibold text-[var(--text-primary)]">{a.ticker}</span>
                        <span className="w-24 text-[11px] text-[var(--text-muted)]">
                          current {((a.weight ?? 0) * 100).toFixed(1)}%
                        </span>
                        <input
                          type="number"
                          step="0.5"
                          min="0"
                          value={proposedWeights[a.ticker] ?? ""}
                          onChange={(e) =>
                            setProposedWeights((prev) => ({ ...prev, [a.ticker]: e.target.value }))
                          }
                          className={`${inputCls} max-w-[110px]`}
                        />
                      </div>
                    ))}
                    <p className="text-[11px] text-[var(--text-muted)]">
                      Total {proposedSum.toFixed(1)}%
                      {Math.abs(proposedSum - 100) > 2 ? " (weights are normalized to 100%)" : ""}
                      {!proposedChanged ? " · identical to current: the report will honestly say the proposal changes essentially nothing" : ""}
                    </p>
                  </div>
                )}
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Rebalancing Rationale</label>
                <textarea value={rationale} onChange={(e) => setRationale(e.target.value)} rows={3} className={inputCls} placeholder="Why rebalance now..." />
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Tax Considerations (optional)</label>
                <textarea value={taxNotes} onChange={(e) => setTaxNotes(e.target.value)} rows={2} className={inputCls} placeholder="e.g. harvesting losses in taxable account..." />
              </div>
            </div>
          )}

          {selected === "year-end" && (
            <div className="grid gap-4 sm:grid-cols-3">
              <div>
                <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Review Year</label>
                <input value={reviewYear} onChange={(e) => setReviewYear(e.target.value)} type="number" className={inputCls} />
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Start Value ($, optional)</label>
                <input value={valueStart} onChange={(e) => setValueStart(e.target.value)} type="number" className={inputCls} placeholder="omit to skip $ figures" />
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">End Value ($, optional)</label>
                <input value={valueEnd} onChange={(e) => setValueEnd(e.target.value)} type="number" className={inputCls} />
              </div>
            </div>
          )}

          {error && (
            <div className="rounded-lg bg-[var(--coral-light)] px-3 py-2 text-xs text-[var(--coral)]">
              Report generation failed: {error}
            </div>
          )}
          {missingInputs.length > 0 && (
            <p className="text-[11px] text-[var(--text-muted)]">
              Required before generating: {missingInputs.join(", ")}. Reports never invent missing data.
            </p>
          )}
          <button
            onClick={generate}
            disabled={missingInputs.length > 0 || generating}
            className="rounded-lg bg-[var(--teal)] px-6 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {generating ? "Generating PDF... (can take a minute)" : "Generate & Download PDF"}
          </button>
        </div>
      )}
    </div>
  );
}
