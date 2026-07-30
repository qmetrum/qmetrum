"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { assetApi, type AssetSearchResult } from "@/lib/api";
import { useSavedAssets } from "@/lib/savedAssets";

export default function AssetsPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AssetSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const { saved, unsave } = useSavedAssets();

  const doSearch = async () => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setSearched(true);
    try {
      const res = await assetApi.search(q, 20);
      setResults(res.items ?? []);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  const goToAsset = (symbol: string) => {
    router.push(`/assets/${encodeURIComponent(symbol)}`);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--navy)]">Assets</h1>
        <p className="text-sm text-[var(--text-secondary)] mt-1">
          Search for a ticker or company name to view detailed analytics
        </p>
      </div>

      {/* Search bar */}
      <div className="flex gap-2 max-w-xl">
        <input
          type="text"
          placeholder="Search by ticker or name (e.g. AAPL, Microsoft)..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && doSearch()}
          className="flex-1 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-4 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-[var(--teal)] focus:outline-none"
        />
        <button
          onClick={doSearch}
          disabled={searching || !query.trim()}
          className="text-sm font-medium bg-[var(--btn-navy)] text-white px-5 py-2.5 rounded-lg hover:opacity-90 disabled:opacity-50"
        >
          {searching ? "Searching..." : "Search"}
        </button>
      </div>

      {/* Saved assets */}
      {saved.length > 0 && (
        <div className="q-card overflow-hidden max-w-2xl">
          <div className="border-b border-[var(--card-border)] px-5 py-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">Saved Assets</h2>
            <span className="text-xs text-[var(--text-muted)]">{saved.length} saved</span>
          </div>
          <div className="divide-y divide-[var(--card-border)]">
            {saved.map((sym) => (
              <div
                key={sym}
                className="flex items-center justify-between px-5 py-3 hover:bg-[var(--content-bg)] transition-colors"
              >
                <button
                  onClick={() => goToAsset(sym)}
                  className="flex-1 text-left font-semibold text-[var(--navy)]"
                >
                  {sym}
                </button>
                <button
                  onClick={() => unsave(sym)}
                  className="text-xs text-[var(--text-muted)] hover:text-[var(--coral)] transition-colors"
                  title="Remove from saved"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Quick access — direct ticker entry */}
      <div className="flex items-center gap-2 max-w-xl">
        <span className="text-xs text-[var(--text-muted)]">Quick access:</span>
        <input
          type="text"
          placeholder="Enter ticker directly..."
          className="w-32 rounded border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-1 text-sm text-[var(--text-primary)] uppercase"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.target as HTMLInputElement).value.trim()) {
              goToAsset((e.target as HTMLInputElement).value.trim().toUpperCase());
            }
          }}
        />
      </div>

      {/* Results */}
      {searched && (
        <div className="q-card overflow-hidden max-w-2xl">
          {results.length === 0 ? (
            <div className="px-5 py-8 text-center text-[var(--text-muted)]">
              {searching ? "Searching..." : "No results found"}
            </div>
          ) : (
            <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-[var(--card-border)] bg-[var(--content-bg)]">
                  <th className="px-5 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Symbol</th>
                  <th className="px-5 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Name</th>
                  <th className="px-5 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Type</th>
                  <th className="px-5 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Exchange</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--card-border)]">
                {results.map((r) => (
                  <tr
                    key={r.symbol}
                    onClick={() => goToAsset(r.symbol)}
                    className="hover:bg-[var(--content-bg)] cursor-pointer transition-colors"
                  >
                    <td className="px-5 py-3 font-semibold text-[var(--navy)]">{r.symbol}</td>
                    <td className="px-5 py-3 text-[var(--text-secondary)]">{r.name ?? "\u2014"}</td>
                    <td className="px-5 py-3 text-[var(--text-muted)] capitalize">{r.asset_type ?? "\u2014"}</td>
                    <td className="px-5 py-3 text-[var(--text-muted)]">{r.exchange ?? "\u2014"}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
        </div>
      )}
    </div>
  );
}
