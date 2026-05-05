"use client";

import React from "react";
import { clsx } from "clsx";
import { usePresentationMode } from "@/components/presentation/PresentationModeProvider";

export type MetricCopyKey =
  | "var95"
  | "cvar95"
  | "cvar99"
  | "sharpe"
  | "sortino"
  | "calmar"
  | "maxDrawdown"
  | "hitRate"
  | "rsi14"
  | "macdHistogram"
  | "atr14"
  | "sigmaLatest";

const METRIC_COPY: Record<
  MetricCopyKey,
  { technical: string; guided: string; glossary: string }
> = {
  var95: {
    technical: "VaR (95%)",
    guided: "Estimated bad-day loss",
    glossary: "Expected one-day loss threshold at 95% confidence.",
  },
  cvar95: {
    technical: "CVaR (95%)",
    guided: "Average loss in bad days",
    glossary: "Average loss when outcomes are worse than VaR 95%.",
  },
  cvar99: {
    technical: "CVaR (99%)",
    guided: "Average loss in worst days",
    glossary: "Average loss in the most extreme 1% of outcomes.",
  },
  sharpe: {
    technical: "Sharpe",
    guided: "Return per unit of risk",
    glossary: "Risk-adjusted return using total volatility.",
  },
  sortino: {
    technical: "Sortino",
    guided: "Return per downside risk",
    glossary: "Risk-adjusted return using downside volatility only.",
  },
  calmar: {
    technical: "Calmar",
    guided: "Return vs worst drawdown",
    glossary: "Annualized return divided by absolute max drawdown.",
  },
  maxDrawdown: {
    technical: "Max Drawdown",
    guided: "Worst peak-to-trough drop",
    glossary: "Largest decline from a peak to a later trough.",
  },
  hitRate: {
    technical: "Hit Rate",
    guided: "Win frequency",
    glossary: "Share of periods with positive returns.",
  },
  rsi14: {
    technical: "RSI (14)",
    guided: "Momentum heat",
    glossary: "Momentum oscillator; above 70 is often overbought and below 30 oversold.",
  },
  macdHistogram: {
    technical: "MACD Histogram",
    guided: "Trend momentum gap",
    glossary: "Difference between MACD and signal lines.",
  },
  atr14: {
    technical: "ATR (14)",
    guided: "Typical daily range",
    glossary: "Average True Range over 14 periods, a realized range proxy.",
  },
  sigmaLatest: {
    technical: "Sigma (Latest)",
    guided: "Current volatility estimate",
    glossary: "Latest annualized volatility estimate in the model path.",
  },
};

export function MetricLabel({
  metric,
  className,
}: {
  metric: MetricCopyKey;
  className?: string;
}) {
  const { mode } = usePresentationMode();
  const copy = METRIC_COPY[metric];
  const text = mode === "guided" ? copy.guided : copy.technical;
  return (
    <span
      title={copy.glossary}
      className={clsx("cursor-help decoration-dotted underline underline-offset-2", className)}
    >
      {text}
    </span>
  );
}

