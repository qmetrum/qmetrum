"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { portfolioListApi, healthApi, type PortfolioResponse } from "@/lib/api";
import { MetricCard } from "@/components/shared/MetricCard";
import { RegimeBadge } from "@/components/shared/RegimeBadge";
import { AlertRulesList } from "@/components/shared/AlertRulesList";
import { AnomalyFeedCard } from "@/components/shared/AnomalyFeedCard";
import { AlertSettingsCard } from "@/components/shared/AlertSettingsCard";

export default function DashboardPage() {
  const { data: portfolios, isLoading: pLoading } = useQuery({
    queryKey: ["portfolios-list"],
    queryFn: portfolioListApi.list,
  });

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: healthApi.check,
  });

  const totalAUM = (portfolios ?? []).reduce((sum, p) => {
    const weights = (p.assets ?? []).reduce((s, a) => s + (a.weight ?? 0), 0);
    return sum + weights * 1_000_000; // approximate AUM
  }, 0);

  const portfolioCount = (portfolios ?? []).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--navy)]">Dashboard</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Portfolio overview and risk intelligence
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
              health?.status === "ok" || health?.status
                ? "bg-[var(--teal-light)] text-[var(--teal-muted)]"
                : "bg-[var(--coral-light)] text-[var(--coral)]"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                health ? "bg-[var(--teal)]" : "bg-[var(--coral)]"
              }`}
            />
            Engine {health ? "Online" : "Connecting..."}
          </span>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        <MetricCard
          label="Total Portfolios"
          value={pLoading ? "..." : String(portfolioCount)}
          color="navy"
        />
        <MetricCard
          label="Est. AUM"
          value={pLoading ? "..." : `$${(totalAUM / 1_000_000).toFixed(1)}M`}
          color="teal"
        />
        <MetricCard
          label="Risk Service"
          value={health?.risk_service ? "Connected" : "Offline"}
          color={health?.risk_service ? "teal" : "coral"}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Portfolio List */}
        <div className="lg:col-span-2 space-y-4">
          <div className="q-card overflow-hidden">
            <div className="flex items-center justify-between border-b border-[var(--card-border)] px-5 py-3">
              <h2 className="text-sm font-semibold text-[var(--text-primary)]">Client Portfolios</h2>
              <Link
                href="/clients"
                className="text-xs font-medium text-[var(--teal)] hover:underline"
              >
                View all
              </Link>
            </div>
            {pLoading ? (
              <div className="space-y-2 p-4">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-14 rounded-lg bg-[var(--content-bg)] animate-pulse" />
                ))}
              </div>
            ) : portfolioCount === 0 ? (
              <div className="py-12 text-center">
                <p className="text-sm text-[var(--text-muted)]">
                  No portfolios yet.
                </p>
                <Link
                  href="/clients"
                  className="mt-2 inline-block text-sm font-medium text-[var(--teal)] hover:underline"
                >
                  Create your first portfolio
                </Link>
              </div>
            ) : (
              <div className="divide-y divide-[var(--card-border)]">
                {(portfolios ?? []).slice(0, 8).map((p: PortfolioResponse) => (
                  <Link
                    key={p.portfolio_id}
                    href={`/portfolios/${p.portfolio_id}`}
                    className="flex items-center gap-4 px-5 py-3 hover:bg-[var(--content-bg)] transition-colors"
                  >
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--btn-navy)] text-white text-xs font-bold">
                      {(p.name ?? "P")[0]}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-[var(--text-primary)] truncate">
                        {p.name ?? `Portfolio #${p.portfolio_id}`}
                      </p>
                      <p className="text-xs text-[var(--text-muted)]">
                        {(p.assets ?? []).length} holdings
                      </p>
                    </div>
                    <ChevronRight />
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* Quick Actions */}
          <div className="grid grid-cols-3 gap-3">
            <Link href="/reports" className="q-card flex flex-col items-center gap-2 px-4 py-5 hover:border-[var(--teal)] transition-colors text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--teal-light)]">
                <FileIcon className="h-5 w-5 text-[var(--teal)]" />
              </div>
              <span className="text-xs font-semibold text-[var(--text-primary)]">Generate Report</span>
            </Link>
            <Link href="/scenarios" className="q-card flex flex-col items-center gap-2 px-4 py-5 hover:border-[var(--amber)] transition-colors text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--amber-light)]">
                <SlidersIcon className="h-5 w-5 text-[var(--amber)]" />
              </div>
              <span className="text-xs font-semibold text-[var(--text-primary)]">Run Scenario</span>
            </Link>
            <Link href="/clients" className="q-card flex flex-col items-center gap-2 px-4 py-5 hover:border-[var(--blue)] transition-colors text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--blue-light)]">
                <PlusIcon className="h-5 w-5 text-[var(--blue)]" />
              </div>
              <span className="text-xs font-semibold text-[var(--text-primary)]">Add Portfolio</span>
            </Link>
          </div>
        </div>

        {/* Alerts */}
        <div className="lg:col-span-1 space-y-6">
          <AnomalyFeedCard title="Anomaly Feed" />
          <AlertRulesList title="Alerts" />
          <AlertSettingsCard title="Alert Settings" />
        </div>
      </div>
    </div>
  );
}

function ChevronRight() {
  return (
    <svg className="h-4 w-4 text-[var(--text-muted)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function FileIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}

function SlidersIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" />
      <line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" />
      <line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" />
    </svg>
  );
}

function PlusIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}
