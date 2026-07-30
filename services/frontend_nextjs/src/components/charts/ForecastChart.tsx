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
} from "recharts";

type ForecastChartProps = {
  historyPrices: number[];
  historyDates: string[];
  forecastPrices: number[];
  forecastDates: string[];
  lowerBound?: number[];
  upperBound?: number[];
  height?: number;
};

export function ForecastChart({
  historyPrices,
  historyDates,
  forecastPrices,
  forecastDates,
  lowerBound,
  upperBound,
  height = 340,
}: ForecastChartProps) {
  // Build unified chart data: history + forecast
  const histLen = Math.min(historyPrices.length, historyDates.length);
  const fcLen = Math.min(forecastPrices.length, forecastDates.length);

  // Show last 120 trading days of history + full forecast
  const histStart = Math.max(0, histLen - 120);

  const data: Record<string, unknown>[] = [];

  // Historical segment
  for (let i = histStart; i < histLen; i++) {
    data.push({
      date: historyDates[i],
      history: historyPrices[i],
      forecast: null,
      lower: null,
      upper: null,
    });
  }

  // Overlap point: last history = first forecast anchor
  if (histLen > 0 && fcLen > 0) {
    data[data.length - 1] = {
      ...data[data.length - 1],
      forecast: historyPrices[histLen - 1],
    };
  }

  // Forecast segment
  for (let i = 0; i < fcLen; i++) {
    const lo = lowerBound?.[i] ?? null;
    const up = upperBound?.[i] ?? null;
    data.push({
      date: forecastDates[i],
      history: null,
      forecast: forecastPrices[i],
      lower: lo,
      upper: up,
      band: lo != null && up != null ? [lo, up] : null,   // range area (no white mask)
    });
  }

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center text-sm text-[var(--text-muted)]" style={{ height }}>
        No data available
      </div>
    );
  }

  // Find the "today" boundary date
  const todayDate = histLen > 0 ? historyDates[histLen - 1] : null;

  const fmtDate = (v: string) => {
    const d = new Date(v);
    return `${d.toLocaleString("default", { month: "short" })} ${d.getDate()}`;
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 5, right: 10, left: 24, bottom: 5 }}>
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
          domain={["auto", "auto"]}
          label={{ value: "Price ($)", angle: -90, position: "insideLeft", fontSize: 11, fill: "#8B95A2" }}
        />
        <Tooltip
          contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
          labelFormatter={(v) => new Date(v as string).toLocaleDateString()}
          formatter={(value, name) => {
            const key = String(name ?? "");
            if (key === "band" && Array.isArray(value)) {
              const [lo, up] = value as number[];
              return [`${Number(lo).toFixed(2)} – ${Number(up).toFixed(2)}`, "95% CI"];
            }
            const labels: Record<string, string> = { history: "Historical", forecast: "Forecast" };
            const formatted = typeof value === "number" ? value.toFixed(2) : String(value ?? "");
            return [formatted, labels[key] ?? key];
          }}
        />

        {/* 95% confidence band: a single range area between lower and upper.
            No white-mask trick, so it renders correctly on dark backgrounds. */}
        <Area
          dataKey="band"
          stroke="none"
          fill="#0F8B6E"
          fillOpacity={0.15}
          isAnimationActive={false}
          connectNulls={false}
        />

        {/* Historical line (dark) */}
        <Line
          dataKey="history"
          stroke="#2D3E50"
          strokeWidth={1.8}
          dot={false}
          isAnimationActive={false}
          connectNulls={false}
        />

        {/* Forecast line (teal) */}
        <Line
          dataKey="forecast"
          stroke="#0F8B6E"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
          connectNulls={false}
        />

        {/* "Today" marker */}
        {todayDate && (
          <ReferenceLine
            x={todayDate}
            stroke="#8B95A2"
            strokeWidth={1}
            strokeDasharray="4 3"
            label={{
              value: "Today",
              position: "top",
              fill: "#8B95A2",
              fontSize: 10,
            }}
          />
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
