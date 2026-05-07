"use client";

import React, { createContext, useContext, useMemo, useState } from "react";

export const HORIZON_OPTIONS = [30, 90, 180, 365] as const;
export const MODEL_OPTIONS = [
  "Hybrid AI",
  "LSTM",
  "XGBoost Ensemble",
  "Prophet",
] as const;

export type ForecastModel = (typeof MODEL_OPTIONS)[number];

type TerminalControlsContextValue = {
  horizon: number;
  setHorizon: (next: number) => void;
  model: ForecastModel;
  setModel: (next: ForecastModel) => void;
};

const TerminalControlsContext = createContext<TerminalControlsContextValue | null>(null);

export function TerminalControlsProvider({ children }: { children: React.ReactNode }) {
  const [horizon, setHorizon] = useState<number>(90);
  const [model, setModel] = useState<ForecastModel>("Hybrid AI");

  const value = useMemo<TerminalControlsContextValue>(
    () => ({
      horizon,
      setHorizon,
      model,
      setModel,
    }),
    [horizon, model],
  );

  return (
    <TerminalControlsContext.Provider value={value}>
      {children}
    </TerminalControlsContext.Provider>
  );
}

export function useTerminalControls() {
  const ctx = useContext(TerminalControlsContext);
  if (!ctx) {
    throw new Error("useTerminalControls must be used within TerminalControlsProvider");
  }
  return ctx;
}
