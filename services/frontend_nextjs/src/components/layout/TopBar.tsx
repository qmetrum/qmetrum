"use client";

import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "react-oidc-context";
import { assetApi, type AssetSearchResult } from "@/lib/api";
import { useBranding } from "@/components/providers/BrandingProvider";
import { cognitoLogoutUrl } from "@/lib/auth";
import { NotificationBell } from "@/components/layout/NotificationBell";

export function TopBar({ onOpenMobileNav }: { onOpenMobileNav: () => void }) {
  const router = useRouter();
  const branding = useBranding();
  const auth = useAuth();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AssetSearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const ref = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function onSearch(q: string) {
    setQuery(q);
    if (timer.current) clearTimeout(timer.current);
    if (q.trim().length < 1) { setResults([]); setOpen(false); setActiveIndex(-1); return; }
    timer.current = setTimeout(async () => {
      try {
        const res = await assetApi.search(q.trim(), 6);
        setResults(res.items ?? []);
        setActiveIndex(-1);
        setOpen(true);
      } catch { setResults([]); }
    }, 200);
  }

  function pick(symbol: string) {
    setOpen(false);
    setQuery("");
    router.push(`/assets/${symbol}`);
  }

  function onSearchKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActiveIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      pick(results[activeIndex].symbol);
    } else if (e.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b border-[var(--border)] bg-white px-4 sm:px-6">
      <button
        onClick={onOpenMobileNav}
        aria-label="Open navigation"
        className="-ml-1 rounded-lg p-2 text-[var(--text-secondary)] transition-colors hover:bg-[var(--content-bg)] lg:hidden"
      >
        <MenuIcon className="h-5 w-5" />
      </button>
      {/* Search */}
      <div ref={ref} className="relative w-full max-w-md">
        <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--content-bg)] px-3 py-1.5">
          <SearchIcon className="h-4 w-4 text-[var(--text-muted)]" />
          <input
            value={query}
            onChange={(e) => onSearch(e.target.value)}
            onKeyDown={onSearchKeyDown}
            placeholder="Search assets..."
            aria-label="Search assets"
            role="combobox"
            aria-expanded={open && results.length > 0}
            aria-controls="asset-search-listbox"
            aria-autocomplete="list"
            aria-activedescendant={activeIndex >= 0 ? `asset-opt-${activeIndex}` : undefined}
            className="w-full bg-transparent text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none"
          />
        </div>
        {open && results.length > 0 && (
          <ul
            id="asset-search-listbox"
            role="listbox"
            aria-label="Asset search results"
            className="absolute top-full left-0 mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--card-bg)] shadow-lg overflow-hidden"
          >
            {results.map((r, i) => (
              <li key={r.symbol} id={`asset-opt-${i}`} role="option" aria-selected={i === activeIndex}>
                <button
                  onClick={() => pick(r.symbol)}
                  onMouseEnter={() => setActiveIndex(i)}
                  className={`flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition-colors ${
                    i === activeIndex ? "bg-[var(--content-bg)]" : "hover:bg-[var(--content-bg)]"
                  }`}
                >
                  <span className="font-semibold text-[var(--navy)]">{r.symbol}</span>
                  <span className="truncate text-[var(--text-secondary)]">{r.name}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="ml-auto flex items-center gap-3">
        {/* Notification bell — live triggered alerts */}
        <NotificationBell enabled={auth.isAuthenticated} />

        {/* User / auth */}
        {auth.isAuthenticated ? (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-1.5">
              <div className="h-6 w-6 rounded-full bg-[var(--btn-navy)] flex items-center justify-center">
                <span className="text-xs font-semibold text-white">
                  {(
                    (auth.user?.profile.name as string | undefined) ??
                    (auth.user?.profile.email as string | undefined) ??
                    branding.advisorName ??
                    "A"
                  )?.[0]?.toUpperCase() ?? "A"}
                </span>
              </div>
              <span className="text-sm font-medium text-[var(--text-primary)]">
                {(auth.user?.profile.name as string | undefined) ??
                  (auth.user?.profile.email as string | undefined) ??
                  branding.advisorName ??
                  "Advisor"}
              </span>
            </div>
            <button
              onClick={() => {
                auth.removeUser();
                window.location.href = cognitoLogoutUrl();
              }}
              className="text-xs font-medium text-[var(--text-muted)] hover:text-[var(--coral)] transition-colors px-2"
              title="Sign out"
            >
              Sign out
            </button>
          </div>
        ) : (
          <button
            onClick={() => auth.signinRedirect()}
            disabled={auth.isLoading}
            className="rounded-lg bg-[var(--teal)] px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {auth.isLoading ? "..." : "Sign in"}
          </button>
        )}
      </div>
    </header>
  );
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

function MenuIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}

