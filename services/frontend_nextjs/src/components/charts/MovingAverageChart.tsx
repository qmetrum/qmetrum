"use client";

import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import { simpleMovingAverage } from "@/lib/finance";

type MovingAverageChartProps = {
  historyPrices: number[];
  historyDates: string[];
  forecastPrices?: number[];
  forecastDates?: string[];
  height?: number;
};

export function MovingAverageChart({
  historyPrices,
  historyDates,
  forecastPrices,
  forecastDates,
  height = 280,
}: MovingAverageChartProps) {
  // Combine history + forecast for MA continuation
  const allPrices = [...historyPrices, ...(forecastPrices ?? [])];
  const allDates = [...historyDates, ...(forecastDates ?? [])];

  const ma50 = simpleMovingAverage(allPrices, 50);
  const ma200 = simpleMovingAverage(allPrices, 200);

  // Show last 180 history days + forecast
  const histLen = historyPrices.length;
  const showStart = Math.max(0, histLen - 180);

  const data: Record<string, unknown>[] = [];
  for (let i = showStart; i < allPrices.length; i++) {
    const isForecast = i >= histLen;
    data.push({
      date: allDates[i],
      price: isForecast ? null : allPrices[i],
      forecast: isForecast ? allPrices[i] : null,
      ma50: ma50[i],
      ma200: ma200[i],
    });
  }

  // Overlap anchor
  if (histLen > 0 && forecastPrices && forecastPrices.length > 0) {
    const overlapIdx = histLen - showStart;
    if (overlapIdx >= 0 && overlapIdx < data.length) {
      data[overlapIdx] = { ...data[overlapIdx], forecast: historyPrices[histLen - 1] };
    }
  }

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center text-sm text-[var(--text-muted)]" style={{ height }}>
        Insufficient data
      </div>
    );
  }

  const todayDate = histLen > 0 ? historyDates[histLen - 1] : null;
  const fmtDate = (v: string) => {
    const d = new Date(v);
    return `${d.toLocaleString("default", { month: "short" })} ${d.getDate()}`;
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F3" />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 10, fill: "#8B95A2" }}
          tickFormatter={fmtDate}
          interval="preserveStartEnd"
          minTickGap={50}
        />
        <YAxis tick={{ fontSize: 10, fill: "#8B95A2" }} domain={["auto", "auto"]} />
        <Tooltip
          contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
          labelFormatter={(v) => new Date(v as string).toLocaleDateString()}
          formatter={(value: number | null, name: string) => {
            if (value == null) return [null, null];
            const labels: Record<string, string> = {
              price: "Price",
              forecast: "Forecast",
              ma50: "MA(50)",
              ma200: "MA(200)",
            };
            return [value.toFixed(2), labels[name] ?? name];
          }}
        />
        <Line dataKey="price" stroke="#2D3E50" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls={false} />
        <Line dataKey="forecast" stroke="#0F8B6E" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
        <Line dataKey="ma50" stroke="#D4920B" strokeWidth={1.2} dot={false} isAnimationActive={false} connectNulls={false} />
        <Line dataKey="ma200" stroke="#8B5CF6" strokeWidth={1.2} dot={false} isAnimationActive={false} connectNulls={false} />
        {todayDate && (
          <ReferenceLine x={todayDate} stroke="#8B95A2" strokeWidth={1} strokeDasharray="4 3" />
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
