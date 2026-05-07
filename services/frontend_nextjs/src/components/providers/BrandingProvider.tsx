"use client";

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";

export type Theme = "light" | "dark";

export type BrandingSettings = {
  firmName: string;
  advisorName: string;
  logoDataUrl: string | null;
  fragilityThreshold: string;
  rebalanceDrift: string;
  theme: Theme;
};

const DEFAULTS: BrandingSettings = {
  firmName: "Advisory Firm",
  advisorName: "Financial Advisor",
  logoDataUrl: null,
  fragilityThreshold: "1.5",
  rebalanceDrift: "5",
  theme: "light",
};

const STORAGE_KEY = "qsight-settings";

type BrandingContextValue = BrandingSettings & {
  update: (partial: Partial<BrandingSettings>) => void;
};

const BrandingContext = createContext<BrandingContextValue>({
  ...DEFAULTS,
  update: () => {},
});

export function BrandingProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<BrandingSettings>(DEFAULTS);

  // Load from localStorage on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        setSettings((prev) => ({ ...prev, ...parsed }));
      }
    } catch {
      // ignore corrupted storage
    }
  }, []);

  // Apply theme class to <html> element
  useEffect(() => {
    const root = document.documentElement;
    if (settings.theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [settings.theme]);

  const update = useCallback((partial: Partial<BrandingSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...partial };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // storage full — ignore
      }
      return next;
    });
  }, []);

  return (
    <BrandingContext.Provider value={{ ...settings, update }}>
      {children}
    </BrandingContext.Provider>
  );
}

export function useBranding() {
  return useContext(BrandingContext);
}
