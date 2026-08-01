"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

// A single visually-hidden aria-live region that announces route changes, so
// navigation isn't silent for screen-reader users (the app is client-routed).
const NAMES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/assets": "Assets",
  "/portfolios": "Portfolios",
  "/scenarios": "Scenarios",
  "/clients": "Clients",
  "/reports": "Reports",
  "/alerts": "Alerts",
  "/settings": "Settings",
};

function pageName(path: string): string {
  if (NAMES[path]) return NAMES[path];
  const seg = "/" + (path.split("/")[1] ?? "");
  return NAMES[seg] ?? "Page";
}

export function RouteAnnouncer() {
  const pathname = usePathname();
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (!pathname) return;
    const name = pageName(pathname);
    setMsg(`${name} loaded`);
    // Per-route browser tab title (pages are client components and can't export
    // metadata) — replaces the single static title on every route.
    document.title = `${name} · Qsight`;
  }, [pathname]);
  return (
    <div role="status" aria-live="polite" className="sr-only">
      {msg}
    </div>
  );
}
