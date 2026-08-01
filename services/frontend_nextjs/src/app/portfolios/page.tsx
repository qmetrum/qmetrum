"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { portfolioListApi, portfolioApi, type PortfolioResponse } from "@/lib/api";
import { formatApiDate } from "@/lib/datetime";
import { useToast } from "@/components/shared/Toast";

export default function PortfoliosPage() {
  const qc = useQueryClient();
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const { toast } = useToast();

  const { data: portfolios, isLoading } = useQuery({
    queryKey: ["portfolios-list"],
    queryFn: portfolioListApi.list,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => portfolioApi.delete(String(id)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portfolios-list"] });
      setConfirmId(null);
      toast("Portfolio deleted", "success");
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--navy)]">Portfolios</h1>
          <p className="text-sm text-[var(--text-secondary)]">Manage and analyze client portfolios</p>
        </div>
        <Link href="/clients" className="rounded-lg bg-[var(--teal)] px-4 py-2 text-sm font-medium text-white hover:opacity-90 transition-opacity">
          New Portfolio
        </Link>
      </div>

      <div className="q-card overflow-hidden">
        {isLoading ? (
          <div className="space-y-2 p-5">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-16 rounded-lg bg-[var(--content-bg)] animate-pulse" />
            ))}
          </div>
        ) : (portfolios ?? []).length === 0 ? (
          <div className="py-16 text-center">
            <p className="text-[var(--text-muted)]">No portfolios found. Create one to get started.</p>
          </div>
        ) : (
          <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-[var(--card-border)] bg-[var(--content-bg)]">
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Name</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Holdings</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Updated</th>
                <th className="px-5 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--card-border)]">
              {(portfolios ?? []).map((p: PortfolioResponse) => (
                <tr key={p.portfolio_id} className="hover:bg-[var(--content-bg)] transition-colors">
                  <td className="px-5 py-3">
                    <Link href={`/portfolios/${p.portfolio_id}`} className="font-medium text-[var(--navy)] hover:underline">
                      {p.name ?? `Portfolio #${p.portfolio_id}`}
                    </Link>
                  </td>
                  <td className="px-5 py-3 text-[var(--text-secondary)]">{(p.assets ?? []).length} assets</td>
                  <td className="px-5 py-3 text-[var(--text-muted)]">
                    {formatApiDate(p.updated_at)}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <div className="flex items-center justify-end gap-3">
                      <Link href={`/portfolios/${p.portfolio_id}`} className="text-xs font-medium text-[var(--teal)] hover:underline">
                        View
                      </Link>
                      {confirmId === p.portfolio_id ? (
                        <span className="flex items-center gap-1.5">
                          <button
                            onClick={() => deleteMutation.mutate(p.portfolio_id)}
                            disabled={deleteMutation.isPending}
                            className="text-xs font-semibold text-white bg-[var(--coral)] rounded px-2 py-0.5 hover:opacity-90 disabled:opacity-50"
                          >
                            {deleteMutation.isPending ? "..." : "Confirm"}
                          </button>
                          {deleteMutation.isError && (
                            <span className="text-[10px] font-medium text-[var(--coral)]">failed</span>
                          )}
                          <button
                            onClick={() => setConfirmId(null)}
                            className="text-xs font-medium text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                          >
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <button
                          onClick={() => setConfirmId(p.portfolio_id)}
                          className="text-xs font-medium text-[var(--coral)] hover:underline"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
    </div>
  );
}
