"use client";

import { useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";

// Owns the app chrome state so the content offset reflows with the sidebar
// (fixes the collapse dead-gap) and a mobile off-canvas drawer works below lg.
export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

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
    </div>
  );
}
