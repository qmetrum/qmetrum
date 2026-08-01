"use client";

import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  Legend,
} from "recharts";
import type { DrawdownSeries } from "@/lib/api";

type DrawdownChartProps = {
  historyPrices: number[];
  historyDates: string[];
  /** Optional backend-computed series; when present, renders history + forecast
   *  with running-peak continuity and CI band on the forecast portion. */
  backendSeries?: DrawdownSeries;
  height?: number;
};

function computeDrawdown(prices: number[]): number[] {
  const dd: number[] = [];
  let peak = prices[0] ?? 1;
  for (const p of prices) {
    if (p > peak) peak = p;
    dd.push(((p / peak) - 1) * 100);
  }
  return dd;
}

const fmtDate = (v: string) => {
  const d = new Date(v);
  return `${d.toLocaleString("default", { month: "short" })} ${d.getDate()}`;
};

type Row = {
  date: string;
  historical?: number;
  forecast?: number;
  forecastLower?: number;
  forecastUpper?: number;
  /** Range-array [lower, upper] for a single sign-safe recharts band Area. */
  band?: number[];
};

export function DrawdownChart({
  historyPrices,
  historyDates,
  backendSeries,
  height = 200,
}: DrawdownChartProps) {
  // Backend-provided path (preferred): render continuous history + forecast with CI band.
  const hv = backendSeries?.historical?.values;
  const hd = backendSeries?.historical?.dates ?? historyDates;
  const fv = backendSeries?.forecast?.values;
  const fd = backendSeries?.forecast?.dates;
  const fLo = backendSeries?.forecast?.lower;
  const fUp = backendSeries?.forecast?.upper;

  const useBackend = Array.isArray(hv) && Array.isArray(fv) && hv.length > 0 && fv.length > 0;

  let data: Row[] = [];
  let cutoffDate: string | null = null;

  if (useBackend) {
    const histN = Math.min(hv!.length, Math.min(hd?.length ?? hv!.length, 252));
    const histValues = hv!.slice(-histN);
    const histDates = (hd ?? []).slice(-histN);
    const fcDates = fd ?? [];

    for (let i = 0; i < histN; i++) {
      data.push({
        date: histDates[i] ?? `h-${i}`,
        historical: +(histValues[i] * 100).toFixed(2),
      });
    }
    cutoffDate = histDates[histDates.length - 1] ?? null;

    for (let i = 0; i < fv!.length; i++) {
      const lo = fLo?.[i];
      const up = fUp?.[i];
      const bandFloor = typeof lo === "number" ? +(lo * 100).toFixed(2) : undefined;
      const bandTop = typeof up === "number" ? +(up * 100).toFixed(2) : undefined;
      data.push({
        date: fcDates[i] ?? `f-${i}`,
        forecast: +(fv![i] * 100).toFixed(2),
        forecastLower: bandFloor,
        forecastUpper: bandTop,
        // Single range-array band [lower, upper]; sign-safe for negative drawdowns.
        band: bandFloor !== undefined && bandTop !== undefined ? [bandFloor, bandTop] : undefined,
      });
    }
  } else {
    // Back-compat: compute from historyPrices alone.
    const n = Math.min(historyPrices.length, historyDates.length, 252);
    const prices = historyPrices.slice(-n);
    const dates = historyDates.slice(-n);
    const dd = computeDrawdown(prices);
    data = dates.map((d, i) => ({ date: d, historical: +dd[i].toFixed(2) }));
  }

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-[var(--text-muted)]"
        style={{ height }}
      >
        Insufficient data
      </div>
    );
  }

  return (
    <div role="img" aria-label="Portfolio drawdown over time.">
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart accessibilityLayer data={data} margin={{ top: 5, right: 10, left: 24, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F3" />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 10, fill: "#8B95A2" }}
          tickFormatter={fmtDate}
          interval="preserveStartEnd"
          minTickGap={50}
        />
        <YAxis
          tick={{ fontSize: 10, fill: "#8B95A2" }}
          tickFormatter={(v) => `${v}%`}
          domain={["auto", 0]}
          label={{ value: "Drawdown", angle: -90, position: "insideLeft", fontSize: 11, fill: "#8B95A2" }}
        />
        <Tooltip
          contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
          labelFormatter={(v) => new Date(v as string).toLocaleDateString()}
          // @ts-expect-error recharts Formatter typing quirk
          formatter={(value: number | number[], name: string) => {
            if (Array.isArray(value)) return [`${value[0].toFixed(1)}% to ${value[1].toFixed(1)}%`, "Forecast CI"];
            const label = name === "historical" ? "Drawdown" : name === "forecast" ? "Forecast" : "";
            return [`${Number(value ?? 0).toFixed(2)}%`, label];
          }}
        />
        {useBackend && <Legend wrapperStyle={{ fontSize: 11 }} iconType="line" />}

        {/* Forecast uncertainty band: a single range-array Area (sign-safe). */}
        {useBackend && (
          <Area
            dataKey="band"
            stroke="none"
            fill="#C0392B"
            fillOpacity={0.12}
            isAnimationActive={false}
            name="Forecast CI"
            connectNulls={false}
          />
        )}

        {/* Historical line (filled area) */}
        <Area
          dataKey="historical"
          stroke="#C0392B"
          strokeWidth={1.2}
          fill="#C0392B"
          fillOpacity={0.18}
          isAnimationActive={false}
          name="Historical"
          connectNulls={false}
        />

        {/* Forecast median line (dashed, no fill) */}
        {useBackend && (
          <Line
            dataKey="forecast"
            stroke="#C0392B"
            strokeWidth={1.2}
            strokeDasharray="4 3"
            dot={false}
            isAnimationActive={false}
            name="Forecast"
            connectNulls={false}
          />
        )}

        {useBackend && cutoffDate && (
          <ReferenceLine
            x={cutoffDate}
            stroke="#8B95A2"
            strokeDasharray="2 3"
            strokeWidth={1}
            label={{ value: "forecast →", position: "insideTopRight", fontSize: 10, fill: "#8B95A2" }}
          />
        )}
      </ComposedChart>
    </ResponsiveContainer>
    </div>
  );
}
