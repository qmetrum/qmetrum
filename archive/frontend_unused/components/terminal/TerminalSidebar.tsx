"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import type React from "react";
import {
  BellRing,
  CandlestickChart,
  Compass,
  LayoutGrid,
  ListChecks,
  Settings,
  SlidersHorizontal,
  Wallet,
} from "lucide-react";

type NavItem = {
  label: string;
  href: string;
  icon: React.ComponentType<{ size?: number; strokeWidth?: number }>;
};

const NAV_ITEMS: NavItem[] = [
  { label: "Markets", href: "/markets", icon: LayoutGrid },
  { label: "Watchlists", href: "/watchlist", icon: ListChecks },
  { label: "Portfolio", href: "/portfolio/main", icon: Wallet },
  { label: "Screener", href: "/screener", icon: SlidersHorizontal },
  { label: "Forecast Lab", href: "/forecast-lab", icon: CandlestickChart },
  { label: "Alerts", href: "/alerts", icon: BellRing },
  { label: "Settings", href: "/settings", icon: Settings },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function TerminalSidebar() {
  const pathname = usePathname();

  return (
    <aside className="terminal-sidebar fixed left-0 top-0 z-50 flex h-screen w-[76px] flex-col border-r border-[var(--terminal-border)] bg-[var(--terminal-bg)] md:w-[250px]">
      <div className="border-b border-[var(--terminal-border)] px-3 py-4 md:px-5">
        <Link href="/asset/AAPL" className="flex items-center gap-2 md:gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md border border-[var(--terminal-border)] bg-[var(--terminal-panel)] text-sm font-semibold text-white">
            Q
          </div>
          <div className="hidden md:block">
            <div className="font-semibold tracking-[0.18em] text-white">QMETRUM</div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--terminal-muted)]">Terminal</div>
          </div>
        </Link>
      </div>

      <nav className="flex-1 space-y-1 px-2 py-3 md:px-3">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = isActive(pathname, item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "flex items-center gap-3 rounded-md border px-2 py-2 text-sm transition-colors md:px-3",
                active
                  ? "border-blue-500/40 bg-blue-500/10 text-blue-200"
                  : "border-transparent text-slate-300 hover:border-[var(--terminal-border)] hover:bg-[var(--terminal-panel)] hover:text-white",
              )}
            >
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-[var(--terminal-border)] bg-[var(--terminal-panel)]">
                <Icon size={16} strokeWidth={2.1} />
              </span>
              <span className="hidden truncate md:block">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-[var(--terminal-border)] p-3 text-[11px] text-[var(--terminal-muted)] md:px-4">
        <div className="hidden items-center gap-2 md:flex">
          <Compass size={14} />
          Asset-centric intelligence
        </div>
      </div>
    </aside>
  );
}
