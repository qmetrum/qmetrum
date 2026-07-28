"use client";

import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useBranding } from "@/components/providers/BrandingProvider";
import {
  portfolioApi,
  portfolioListApi,
  type PortfolioResponse,
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

  const fileRef = useRef<HTMLInputElement>(null);
  const [importResult, setImportResult] = useState<
    { name: string; count: number; basis: string; warnings: string[]; skipped: number } | null
  >(null);
  const importMutation = useMutation({
    mutationFn: (file: File) => portfolioApi.importCsv(file),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["portfolios-list"] });
      setImportResult({
        name: res.name,
        count: res.import_report.imported,
        basis: res.import_report.weight_basis,
        warnings: res.import_report.warnings ?? [],
        skipped: (res.import_report.skipped ?? []).length,
      });
    },
  });
  const importErr = importMutation.error as
    | { response?: { data?: { detail?: string } }; message?: string }
    | null;
  const importErrorMsg = importErr
    ? importErr.response?.data?.detail ?? importErr.message ?? "Import failed"
    : null;

  function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) {
      setImportResult(null);
      importMutation.mutate(f);
    }
    e.target.value = ""; // allow re-importing the same filename
  }

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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--navy)]">Client Management</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Manage client portfolios and generate reports
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            onChange={onPickFile}
            className="hidden"
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={importMutation.isPending}
            className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--content-bg)] disabled:opacity-50 transition-colors"
            title="Import real holdings from a custodian or brokerage CSV export"
          >
            {importMutation.isPending ? "Importing…" : "Import holdings (CSV)"}
          </button>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="rounded-lg bg-[var(--teal)] px-4 py-2 text-sm font-medium text-white hover:opacity-90 transition-opacity"
          >
            {showCreate ? "Cancel" : "Add Client Portfolio"}
          </button>
        </div>
      </div>

      {importErrorMsg && (
        <div className="rounded-lg bg-[var(--coral-light)] px-4 py-2.5 text-sm text-[var(--coral)]">
          Import failed: {importErrorMsg}
        </div>
      )}
      {importResult && (
        <div className="rounded-lg bg-[var(--teal-light)] px-4 py-2.5 text-sm text-[var(--text-primary)]">
          Imported <span className="font-semibold">{importResult.count}</span> holdings into{" "}
          <span className="font-semibold">{importResult.name}</span>
          {importResult.basis === "market_value"
            ? " (weights from live market value)"
            : importResult.basis === "supplied_weight"
              ? " (weights from the file)"
              : " (equal-weighted — add quantities to get real weights)"}
          {importResult.skipped > 0 && ` · ${importResult.skipped} row(s) skipped`}
          {importResult.warnings.length > 0 && (
            <span className="block text-xs text-[var(--text-muted)] mt-0.5">
              {importResult.warnings.join(" ")}
            </span>
          )}
        </div>
      )}

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
                {/* Reports need real inputs (value, event details, proposed
                    weights), so route to the Report Center preconfigured
                    instead of firing invented payloads from here. */}
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {REPORT_TYPES.map((rt) => (
                    <Link
                      key={rt.key}
                      href={`/reports?portfolio=${p.portfolio_id}&type=${rt.key}`}
                      className="rounded-md border border-[var(--border)] px-2.5 py-1 text-[11px] font-medium text-[var(--text-secondary)] hover:bg-[var(--content-bg)] transition-colors"
                    >
                      {rt.label}
                    </Link>
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
