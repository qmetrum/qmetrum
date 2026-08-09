"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { RouteAnnouncer } from "@/components/layout/RouteAnnouncer";

// Public, no-login pages (e.g. the Cross-Asset Correlation Monitor) render bare,
// without the advisor workstation chrome.
const BARE_PREFIXES = ["/correlations"];

// Owns the app chrome state so the content offset reflows with the sidebar
// (fixes the collapse dead-gap) and a mobile off-canvas drawer works below lg.
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  if (BARE_PREFIXES.some((p) => pathname.startsWith(p))) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      {/* Full width on mobile (sidebar is an off-canvas drawer); offset by the
          sidebar on lg+, reflowing when collapsed. */}
      <div
        className={`flex min-h-screen min-w-0 flex-1 flex-col transition-[margin] duration-200 ${
          collapsed ? "lg:ml-[68px]" : "lg:ml-[240px]"
        }`}
      >
        <TopBar onOpenMobileNav={() => setMobileOpen(true)} />
        <main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">{children}</main>
      </div>
      <RouteAnnouncer />
    </div>
  );
}
