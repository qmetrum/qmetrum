"use client";

import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  ErrorBar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
  ReferenceLine,
  Legend,
} from "recharts";
import type { MonthlyReturns } from "@/lib/api";

type ReturnsChartProps = {
  /** Daily prices (historical) */
  historyPrices: number[];
  historyDates: string[];
  /** Optional backend-computed monthly series with historical + forecast bands. */
  backendSeries?: MonthlyReturns;
  height?: number;
};

function computeMonthlyReturns(
  prices: number[],
  dates: string[],
): { month: string; return_pct: number }[] {
  const byMonth: Record<string, number[]> = {};
  for (let i = 0; i < prices.length; i++) {
    const key = dates[i]?.slice(0, 7);
    if (!key) continue;
    if (!byMonth[key]) byMonth[key] = [];
    byMonth[key].push(prices[i]);
  }
  const months = Object.keys(byMonth).sort();
  const recent = months.slice(-12);
  return recent.map((m) => {
    const vals = byMonth[m];
    const ret = vals.length >= 2 ? vals[vals.length - 1] / vals[0] - 1 : 0;
    const d = new Date(m + "-01");
    return {
      month: d.toLocaleString("default", { month: "short", year: "2-digit" }),
      return_pct: +(ret * 100).toFixed(2),
    };
  });
}

type Row = {
  month: string;
  return_pct: number;
  /** Forecast-only fields */
  isForecast?: boolean;
  errorDown?: number;
  errorUp?: number;
  partial?: boolean;
  lower_pct?: number;
  upper_pct?: number;
};

function formatMonthKey(yyyymm: string): string {
  const d = new Date(yyyymm + "-01");
  if (isNaN(d.getTime())) return yyyymm;
  return d.toLocaleString("default", { month: "short", year: "2-digit" });
}

export function ReturnsChart({
  historyPrices,
  historyDates,
  backendSeries,
  height = 220,
}: ReturnsChartProps) {
  let data: Row[] = [];
  let hasForecast = false;

  const useBackend =
    backendSeries &&
    ((backendSeries.historical && backendSeries.historical.length > 0) ||
      (backendSeries.forecast && backendSeries.forecast.length > 0));

  if (useBackend) {
    const hist = (backendSeries!.historical ?? []).slice(-12);
    for (const row of hist) {
      data.push({
        month: formatMonthKey(row.month),
        return_pct: +(row.return * 100).toFixed(2),
        isForecast: false,
      });
    }
    for (const row of backendSeries!.forecast ?? []) {
      hasForecast = true;
      const ret = +(row.return * 100).toFixed(2);
      const loPct = typeof row.lower === "number" ? +(row.lower * 100).toFixed(2) : undefined;
      const upPct = typeof row.upper === "number" ? +(row.upper * 100).toFixed(2) : undefined;
      const errorDown = loPct !== undefined ? Math.max(0, ret - loPct) : undefined;
      const errorUp = upPct !== undefined ? Math.max(0, upPct - ret) : undefined;
      data.push({
        month: formatMonthKey(row.month),
        return_pct: ret,
        isForecast: true,
        errorDown,
        errorUp,
        lower_pct: loPct,
        upper_pct: upPct,
        partial: !!row.partial,
      });
    }
  } else {
    data = computeMonthlyReturns(historyPrices, historyDates).map((r) => ({
      ...r,
      isForecast: false,
    }));
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

  const firstForecastIdx = hasForecast ? data.findIndex((r) => r.isForecast) : -1;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F3" vertical={false} />
        <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#8B95A2" }} />
        <YAxis tick={{ fontSize: 10, fill: "#8B95A2" }} tickFormatter={(v) => `${v}%`} label={{ value: "Monthly return", angle: -90, position: "insideLeft", fontSize: 11, fill: "#8B95A2" }} />
        <Tooltip
          contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
          // @ts-expect-error recharts Formatter typing quirk (matches existing ForecastChart pattern)
          formatter={(value: number) => [`${Number(value ?? 0).toFixed(2)}%`, "Monthly return"]}
          labelFormatter={(label: string, items: ReadonlyArray<{ payload?: Row }> | undefined) => {
            const p = items?.[0]?.payload;
            if (!p?.isForecast) return label;
            const band =
              p.lower_pct !== undefined && p.upper_pct !== undefined
                ? `  [CI ${p.lower_pct}% to ${p.upper_pct}%]`
                : "";
            const partial = p.partial ? " (partial)" : "";
            return `${label}  forecast${partial}${band}`;
          }}
        />
        {hasForecast && <Legend wrapperStyle={{ fontSize: 11 }} iconType="square" />}
        <ReferenceLine y={0} stroke="#8B95A2" strokeWidth={1} />

        {firstForecastIdx > 0 && (
          <ReferenceLine
            x={data[firstForecastIdx].month}
            stroke="#8B95A2"
            strokeDasharray="2 3"
            strokeWidth={1}
            label={{ value: "forecast →", position: "insideTopRight", fontSize: 10, fill: "#8B95A2" }}
          />
        )}

        <Bar dataKey="return_pct" radius={[3, 3, 0, 0]} isAnimationActive={false} name="Monthly return">
          {data.map((entry, i) => {
            const positive = entry.return_pct >= 0;
            const fill = entry.isForecast
              ? positive
                ? "#0F8B6E80"
                : "#D85A3080"
              : positive
                ? "#0F8B6E"
                : "#D85A30";
            return (
              <Cell
                key={i}
                fill={fill}
                stroke={entry.isForecast ? (positive ? "#0F8B6E" : "#D85A30") : undefined}
                strokeDasharray={entry.isForecast ? "3 2" : undefined}
                strokeWidth={entry.isForecast ? 1 : 0}
              />
            );
          })}
          {hasForecast && (
            <ErrorBar
              dataKey={(row: Row) => [row.errorDown ?? 0, row.errorUp ?? 0]}
              width={4}
              strokeWidth={1}
              stroke="#8B95A2"
            />
          )}
        </Bar>
      </ComposedChart>
    </ResponsiveContainer>
  );
}
