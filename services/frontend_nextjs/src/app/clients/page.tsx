"use client";

import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useBranding } from "@/components/providers/BrandingProvider";
import {
  portfolioApi,
  portfolioListApi,
  type PortfolioResponse,
  type ImportHolding,
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
  // Two-step import: parse a CSV into an editable preview, then commit.
  const [importName, setImportName] = useState("");
  const [preview, setPreview] = useState<ImportHolding[] | null>(null);
  const [previewReport, setPreviewReport] = useState<
    { warnings: string[]; skipped: { row: number; reason: string }[]; weight_basis: string } | null
  >(null);
  const [importResult, setImportResult] = useState<
    { name: string; count: number; basis: string } | null
  >(null);

  const parseMutation = useMutation({
    mutationFn: (file: File) => portfolioApi.importParse(file),
    onSuccess: (res) => {
      setPreview(res.holdings);
      setPreviewReport(res.report);
      setImportName(`Imported ${new Date().toISOString().slice(0, 10)}`);
    },
  });
  const commitMutation = useMutation({
    mutationFn: () => portfolioApi.importCommit(importName.trim(), preview ?? []),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["portfolios-list"] });
      setImportResult({ name: res.name, count: res.import_report.imported, basis: res.import_report.weight_basis });
      setPreview(null);
      setPreviewReport(null);
    },
  });
  const importErr = (parseMutation.error || commitMutation.error) as
    | { response?: { data?: { detail?: string } }; message?: string }
    | null;
  const importErrorMsg = importErr
    ? importErr.response?.data?.detail ?? importErr.message ?? "Import failed"
    : null;

  function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) {
      setImportResult(null);
      parseMutation.mutate(f);
    }
    e.target.value = ""; // allow re-importing the same filename
  }

  function editHolding(i: number, field: keyof ImportHolding, val: string) {
    if (!preview) return;
    const next = [...preview];
    if (field === "ticker") next[i] = { ...next[i], ticker: val.toUpperCase() };
    else if (field === "purchase_date" || field === "asset_type") next[i] = { ...next[i], [field]: val };
    else if (field === "weight") next[i] = { ...next[i], weight: (parseFloat(val) || 0) / 100 }; // input is %
    else next[i] = { ...next[i], [field]: parseFloat(val) || 0 };
    setPreview(next);
  }
  const previewTotalWeight = (preview ?? []).reduce((a, h) => a + (h.weight || 0), 0);
  function removeHolding(i: number) {
    if (preview) setPreview(preview.filter((_, j) => j !== i));
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
            disabled={parseMutation.isPending}
            className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--content-bg)] disabled:opacity-50 transition-colors"
            title="Import real holdings from a custodian or brokerage CSV export"
          >
            {parseMutation.isPending ? "Reading…" : "Import holdings (CSV)"}
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
            : importResult.basis === "user_adjusted"
              ? " (weights as you set them)"
              : importResult.basis === "supplied_weight"
                ? " (weights from the file)"
                : " (equal-weighted)"}
        </div>
      )}

      {/* Import preview — edit the parsed holdings before saving */}
      {preview && (
        <div className="q-card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              Review imported holdings ({preview.length})
            </h2>
            <span className="text-[11px] text-[var(--text-muted)]">
              weights total {(previewTotalWeight * 100).toFixed(0)}%
              {Math.abs(previewTotalWeight - 1) > 0.02 && " (normalized on save)"}
            </span>
          </div>
          {previewReport && (previewReport.warnings.length > 0 || previewReport.skipped.length > 0) && (
            <p className="text-[11px] text-[var(--text-muted)]">
              {previewReport.warnings.join(" ")}
              {previewReport.skipped.length > 0 &&
                ` ${previewReport.skipped.length} row(s) skipped: ` +
                  previewReport.skipped.slice(0, 3).map((s) => s.reason).join("; ")}
            </p>
          )}
          <div>
            <label htmlFor="import-portfolio-name" className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Portfolio name</label>
            <input
              id="import-portfolio-name"
              value={importName}
              onChange={(e) => setImportName(e.target.value)}
              className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--teal)]"
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[var(--text-muted)]">
                  <th className="py-1 pr-2 font-semibold">Ticker</th>
                  <th className="py-1 px-2 font-semibold">Quantity</th>
                  <th className="py-1 px-2 font-semibold">Cost basis ($)</th>
                  <th className="py-1 px-2 font-semibold">Purchase date</th>
                  <th className="py-1 px-2 font-semibold">Weight (%)</th>
                  <th className="py-1 pl-2"></th>
                </tr>
              </thead>
              <tbody>
                {preview.map((h, i) => (
                  <tr key={i} className="border-t border-[var(--border)]">
                    {([
                      ["ticker", h.ticker, "w-20"],
                      ["quantity", String(h.quantity ?? ""), "w-24"],
                      ["cost_basis", String(h.cost_basis ?? ""), "w-28"],
                      ["purchase_date", h.purchase_date ?? "", "w-32"],
                      ["weight", (h.weight * 100).toFixed(1), "w-20"],
                    ] as const).map(([field, val, w]) => (
                      <td key={field} className="py-1 pr-2">
                        <input
                          value={val}
                          onChange={(e) => editHolding(i, field as keyof ImportHolding, e.target.value)}
                          className={`${w} rounded border border-[var(--border)] bg-white px-2 py-1 text-xs outline-none focus:border-[var(--teal)]`}
                        />
                      </td>
                    ))}
                    <td className="py-1 pl-2">
                      <button
                        onClick={() => removeHolding(i)}
                        className="text-[var(--text-muted)] hover:text-[var(--coral)]"
                        title="Remove"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={() => commitMutation.mutate()}
              disabled={commitMutation.isPending || preview.length === 0 || !importName.trim()}
              className="rounded-lg bg-[var(--teal)] px-5 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {commitMutation.isPending ? "Saving…" : `Import ${preview.length} holdings`}
            </button>
            <button
              onClick={() => { setPreview(null); setPreviewReport(null); }}
              className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--content-bg)] transition-colors"
            >
              Cancel
            </button>
          </div>
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
              className="rounded-lg bg-[var(--btn-navy)] px-4 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
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
            <div key={i} className="h-48 rounded-xl bg-[var(--card-bg)] border border-[var(--card-border)] animate-pulse" />
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
