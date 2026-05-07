"use client";

import React, { createContext, useContext, useMemo, useState } from "react";

export type PresentationMode = "guided" | "pro";

type PresentationModeContextValue = {
  mode: PresentationMode;
  setMode: (next: PresentationMode) => void;
  isGuided: boolean;
  isPro: boolean;
};

const PRESENTATION_MODE_STORAGE_KEY = "qsight.presentation_mode";

const PresentationModeContext = createContext<PresentationModeContextValue | null>(null);

export function PresentationModeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<PresentationMode>(() => {
    if (typeof window === "undefined") return "guided";
    try {
      const raw = window.localStorage.getItem(PRESENTATION_MODE_STORAGE_KEY);
      return raw === "guided" || raw === "pro" ? raw : "guided";
    } catch {
      return "guided";
    }
  });

  const setMode = (next: PresentationMode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(PRESENTATION_MODE_STORAGE_KEY, next);
    } catch {
      // Ignore localStorage write failures.
    }
  };

  const value = useMemo<PresentationModeContextValue>(
    () => ({
      mode,
      setMode,
      isGuided: mode === "guided",
      isPro: mode === "pro",
    }),
    [mode],
  );

  return (
    <PresentationModeContext.Provider value={value}>
      {children}
    </PresentationModeContext.Provider>
  );
}

export function usePresentationMode() {
  const ctx = useContext(PresentationModeContext);
  if (!ctx) {
    throw new Error("usePresentationMode must be used within PresentationModeProvider");
  }
  return ctx;
}
