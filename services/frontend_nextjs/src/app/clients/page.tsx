"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useBranding } from "@/components/providers/BrandingProvider";
import {
  portfolioApi,
  portfolioListApi,
  reportsApi,
  type PortfolioResponse,
  type ReportAsset,
} from "@/lib/api";

type NewPortfolio = {
  name: string;
  assets: { ticker: string; weight: string }[];
};

const REPORT_TYPES = [
  { key: "quarterly", label: "Quarterly Review", color: "var(--teal)" },
  { key: "onboarding", label: "New Client Assessment", color: "var(--blue)" },
  { key: "market-event", label: "Market Event", color: "var(--coral)" },
  { key: "rebalancing", label: "Rebalancing", color: "var(--amber)" },
  { key: "year-end", label: "Year-End Review", color: "var(--navy)" },
] as const;

export default function ClientsPage() {
  const branding = useBranding();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [newPortfolio, setNewPortfolio] = useState<NewPortfolio>({
    name: "",
    assets: [{ ticker: "", weight: "" }],
  });
  const [generating, setGenerating] = useState<string | null>(null);

  const { data: portfolios, isLoading } = useQuery({
    queryKey: ["portfolios-list"],
    queryFn: portfolioListApi.list,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      portfolioApi.create({
        name: newPortfolio.name,
        assets: newPortfolio.assets
          .filter((a) => a.ticker.trim())
          .map((a) => ({
            ticker: a.ticker.trim().toUpperCase(),
            weight: parseFloat(a.weight) / 100 || 0,
          })),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portfolios-list"] });
      setShowCreate(false);
      setNewPortfolio({ name: "", assets: [{ ticker: "", weight: "" }] });
    },
  });

  function addAssetRow() {
    setNewPortfolio({
      ...newPortfolio,
      assets: [...newPortfolio.assets, { ticker: "", weight: "" }],
    });
  }

  function updateAsset(i: number, field: "ticker" | "weight", val: string) {
    const assets = [...newPortfolio.assets];
    assets[i] = { ...assets[i], [field]: val };
    setNewPortfolio({ ...newPortfolio, assets });
  }

  async function generateReport(p: PortfolioResponse, type: string) {
    setGenerating(`${p.portfolio_id}-${type}`);
    const assets: ReportAsset[] = (p.assets ?? []).map((a) => ({
      ticker: a.ticker,
      weight: a.weight ?? 0,
    }));
    const base = {
      client_name: p.name ?? `Portfolio #${p.portfolio_id}`,
      advisor_name: branding.advisorName,
      firm_name: branding.firmName,
      assets,
    };
    try {
      switch (type) {
        case "quarterly":
          await reportsApi.quarterly(base);
          break;
        case "onboarding":
          await reportsApi.onboarding({ ...base, risk_tolerance: "Moderate", target_vol: 0.10 });
          break;
        case "market-event":
          await reportsApi.marketEvent({
            ...base,
            event_name: "Market Event",
            event_date: new Date().toISOString().split("T")[0],
            event_summary: "Market turbulence event analysis.",
          });
          break;
        case "rebalancing":
          await reportsApi.rebalancing({
            ...base,
            current_assets: assets,
            proposed_assets: assets,
            rationale: "Periodic rebalancing review.",
          });
          break;
        case "year-end":
          await reportsApi.yearEnd({ ...base, review_year: new Date().getFullYear() - 1 });
          break;
      }
    } catch {
      // handle silently
    } finally {
      setGenerating(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--navy)]">Client Management</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Manage client portfolios and generate reports
          </p>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="rounded-lg bg-[var(--teal)] px-4 py-2 text-sm font-medium text-white hover:opacity-90 transition-opacity"
        >
          {showCreate ? "Cancel" : "Add Client Portfolio"}
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="q-card p-5 space-y-4">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">New Portfolio</h2>
          <input
            value={newPortfolio.name}
            onChange={(e) => setNewPortfolio({ ...newPortfolio, name: e.target.value })}
            placeholder="Client / Portfolio name"
            className="w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--teal)]"
          />
          <div className="space-y-2">
            {newPortfolio.assets.map((a, i) => (
              <div key={i} className="flex gap-2">
                <input
                  value={a.ticker}
                  onChange={(e) => updateAsset(i, "ticker", e.target.value)}
                  placeholder="Ticker (e.g. VTI)"
                  className="flex-1 rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--teal)]"
                />
                <input
                  value={a.weight}
                  onChange={(e) => updateAsset(i, "weight", e.target.value)}
                  placeholder="Weight %"
                  type="number"
                  className="w-24 rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--teal)]"
                />
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <button onClick={addAssetRow} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] hover:bg-[var(--content-bg)]">
              + Add holding
            </button>
            <button
              onClick={() => createMutation.mutate()}
              disabled={!newPortfolio.name.trim() || createMutation.isPending}
              className="rounded-lg bg-[var(--navy)] px-4 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {createMutation.isPending ? "Creating..." : "Create Portfolio"}
            </button>
          </div>
        </div>
      )}

      {/* Portfolio cards */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-48 rounded-xl bg-white border border-[var(--card-border)] animate-pulse" />
          ))}
        </div>
      ) : (portfolios ?? []).length === 0 ? (
        <div className="q-card py-16 text-center">
          <p className="text-[var(--text-muted)]">No client portfolios. Create one above.</p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {(portfolios ?? []).map((p: PortfolioResponse) => (
            <div key={p.portfolio_id} className="q-card p-5 space-y-3">
              <div className="flex items-center justify-between">
                <Link
                  href={`/portfolios/${p.portfolio_id}`}
                  className="text-base font-semibold text-[var(--navy)] hover:underline"
                >
                  {p.name ?? `Portfolio #${p.portfolio_id}`}
                </Link>
                <span className="text-xs text-[var(--text-muted)]">
                  {(p.assets ?? []).length} holdings
                </span>
              </div>

              {/* Holdings preview */}
              <div className="flex flex-wrap gap-1.5">
                {(p.assets ?? []).slice(0, 6).map((a, i) => (
                  <span
                    key={i}
                    className="rounded-md bg-[var(--content-bg)] px-2 py-0.5 text-xs font-medium text-[var(--text-secondary)]"
                  >
                    {a.ticker} {a.weight != null ? `${(a.weight * 100).toFixed(0)}%` : ""}
                  </span>
                ))}
                {(p.assets ?? []).length > 6 && (
                  <span className="text-xs text-[var(--text-muted)]">+{(p.assets ?? []).length - 6} more</span>
                )}
              </div>

              {/* Report buttons */}
              <div className="pt-1">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Generate Report
                </span>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {REPORT_TYPES.map((rt) => (
                    <button
                      key={rt.key}
                      onClick={() => generateReport(p, rt.key)}
                      disabled={generating === `${p.portfolio_id}-${rt.key}`}
                      className="rounded-md border border-[var(--border)] px-2.5 py-1 text-[11px] font-medium text-[var(--text-secondary)] hover:bg-[var(--content-bg)] disabled:opacity-50 transition-colors"
                    >
                      {generating === `${p.portfolio_id}-${rt.key}` ? "..." : rt.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
