"use client";

import React, { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Bell, ChevronDown, Search, UserRound } from "lucide-react";
import { assetApi, type AssetSearchResult } from "@/lib/api";
import {
  HORIZON_OPTIONS,
  MODEL_OPTIONS,
  type ForecastModel,
  useTerminalControls,
} from "@/components/terminal/TerminalControlsContext";

function parseSymbolFromPath(pathname: string): string {
  if (!pathname.startsWith("/asset/")) return "";
  const raw = pathname.replace("/asset/", "").split("/")[0] ?? "";
  return decodeURIComponent(raw).toUpperCase();
}

export function TerminalTopBar() {
  const router = useRouter();
  const pathname = usePathname();
  const { horizon, setHorizon, model, setModel } = useTerminalControls();

  const symbolInPath = useMemo(() => parseSymbolFromPath(pathname), [pathname]);
  const [search, setSearch] = useState(symbolInPath || "AAPL");
  const [results, setResults] = useState<AssetSearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (symbolInPath) {
      setSearch(symbolInPath);
      return;
    }
    if (!search) {
      setSearch("AAPL");
    }
  }, [symbolInPath, search]);

  useEffect(() => {
    const q = search.trim();
    if (!q) {
      setResults([]);
      setLoading(false);
      return;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await assetApi.search(q, 8);
        if (!cancelled) {
          setResults(res.items ?? []);
          setOpen(true);
        }
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 180);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [search]);

  const navigateToSymbol = (ticker: string) => {
    const symbol = ticker.trim().toUpperCase();
    if (!symbol) return;
    setSearch(symbol);
    setOpen(false);
    router.push(`/asset/${encodeURIComponent(symbol)}`);
  };

  return (
    <header className="terminal-topbar sticky top-0 z-40 border-b border-[var(--terminal-border)] bg-[var(--terminal-bg)]/95 px-3 py-3 backdrop-blur-md md:px-6">
      <div className="flex flex-wrap items-center gap-2 md:gap-3">
        <div className="relative min-w-[220px] flex-1 md:max-w-[460px]">
          <div className="flex items-center rounded-md border border-[var(--terminal-border)] bg-[var(--terminal-panel)] px-3">
            <Search size={14} className="text-[var(--terminal-muted)]" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onFocus={() => {
                if (results.length) setOpen(true);
              }}
              onBlur={() => {
                setTimeout(() => setOpen(false), 120);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") navigateToSymbol(search);
              }}
              placeholder="Search ticker (AAPL, NVDA, BTC-USD)"
              className="h-9 w-full bg-transparent px-2 text-sm text-white outline-none placeholder:text-[var(--terminal-muted)]"
            />
          </div>

          {open ? (
            <div className="absolute z-30 mt-2 max-h-80 w-full overflow-y-auto rounded-md border border-[var(--terminal-border)] bg-[var(--terminal-panel)] shadow-2xl">
              {loading ? (
                <div className="px-3 py-2 text-xs text-[var(--terminal-muted)]">Searching...</div>
              ) : results.length ? (
                results.map((item) => (
                  <button
                    key={`${item.symbol}-${item.exchange ?? ""}`}
                    type="button"
                    onMouseDown={(event) => {
                      event.preventDefault();
                      navigateToSymbol(item.symbol);
                    }}
                    className="flex w-full items-center justify-between border-b border-[var(--terminal-border)] px-3 py-2 text-left text-sm last:border-b-0 hover:bg-[#1f2630]"
                  >
                    <div className="min-w-0">
                      <div className="font-medium text-white">{item.symbol}</div>
                      <div className="truncate text-xs text-[var(--terminal-muted)]">{item.name ?? "Unknown"}</div>
                    </div>
                    <div className="ml-3 rounded border border-[var(--terminal-border)] px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-[var(--terminal-muted)]">
                      {item.asset_type ?? "asset"}
                    </div>
                  </button>
                ))
              ) : (
                <div className="px-3 py-2 text-xs text-[var(--terminal-muted)]">No matches</div>
              )}
            </div>
          ) : null}
        </div>

        <label className="flex items-center gap-2 rounded-md border border-[var(--terminal-border)] bg-[var(--terminal-panel)] px-2 py-1.5">
          <span className="hidden text-xs text-[var(--terminal-muted)] md:inline">Horizon</span>
          <select
            value={horizon}
            onChange={(event) => setHorizon(Number(event.target.value))}
            className="bg-transparent text-xs text-white outline-none"
          >
            {HORIZON_OPTIONS.map((option) => (
              <option key={option} value={option} className="bg-[#161B22] text-white">
                {option}d
              </option>
            ))}
          </select>
          <ChevronDown size={14} className="text-[var(--terminal-muted)]" />
        </label>

        <label className="flex items-center gap-2 rounded-md border border-[var(--terminal-border)] bg-[var(--terminal-panel)] px-2 py-1.5">
          <span className="hidden text-xs text-[var(--terminal-muted)] md:inline">Model</span>
          <select
            value={model}
            onChange={(event) => setModel(event.target.value as ForecastModel)}
            className="bg-transparent text-xs text-white outline-none"
          >
            {MODEL_OPTIONS.map((option) => (
              <option key={option} value={option} className="bg-[#161B22] text-white">
                {option}
              </option>
            ))}
          </select>
          <ChevronDown size={14} className="text-[var(--terminal-muted)]" />
        </label>

        <button
          type="button"
          className="relative inline-flex h-9 w-9 items-center justify-center rounded-md border border-[var(--terminal-border)] bg-[var(--terminal-panel)] text-[var(--terminal-muted)] hover:text-white"
          aria-label="Notifications"
        >
          <Bell size={15} />
          <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-blue-500" />
        </button>

        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-md border border-[var(--terminal-border)] bg-[var(--terminal-panel)] px-2.5 py-2 text-xs text-slate-200"
        >
          <UserRound size={14} />
          <span className="hidden md:inline">Analyst</span>
        </button>
      </div>
    </header>
  );
}
