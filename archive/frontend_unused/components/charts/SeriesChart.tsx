"use client";

import React from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { format } from "date-fns";

type SeriesRow = {
  x: string;
  line?: number | null;
  lower?: number | null;
  upper?: number | null;
};

interface SeriesChartProps {
  rows: SeriesRow[];
  lineKeyLabel?: string;
  lineColor?: string;
  height?: number;
  yPrefix?: string;
  xIsDate?: boolean;
}

export function SeriesChart({
  rows,
  lineKeyLabel = "Series",
  lineColor = "#0080FF",
  height = 340,
  yPrefix = "",
  xIsDate = true,
}: SeriesChartProps) {
  if (!rows.length) {
    return (
      <div className="flex min-h-[240px] items-center justify-center rounded border border-dashed border-gray-700 text-sm text-gray-500">
        No data available
      </div>
    );
  }

  const chartData = rows.map((row) => ({
    ...row,
    range:
      row.lower != null && row.upper != null
        ? [row.lower, row.upper]
        : undefined,
  }));

  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="seriesCone" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={lineColor} stopOpacity={0.28} />
              <stop offset="95%" stopColor={lineColor} stopOpacity={0.04} />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis
            dataKey="x"
            stroke="rgba(255,255,255,0.18)"
            tick={{ fill: "rgba(255,255,255,0.52)", fontSize: 11 }}
            minTickGap={28}
            tickFormatter={(value) => {
              if (!xIsDate) return String(value);
              try {
                return format(new Date(value), "MMM d");
              } catch {
                return String(value);
              }
            }}
          />
          <YAxis
            stroke="rgba(255,255,255,0.18)"
            tick={{ fill: "rgba(255,255,255,0.52)", fontSize: 11 }}
            width={64}
            tickFormatter={(value: number) =>
              `${yPrefix}${Number.isFinite(value) ? value.toFixed(0) : value}`
            }
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#121212",
              borderColor: "rgba(255,255,255,0.1)",
              color: "#e5e7eb",
              fontSize: "12px",
              borderRadius: "10px",
              backdropFilter: "blur(6px)",
            }}
            labelStyle={{ color: "#d1d5db" }}
            formatter={(value: number | [number, number] | undefined, key?: string) => {
              const name = key ?? "";
              if (value == null) return ["—", name];
              if (Array.isArray(value)) {
                return [`${yPrefix}${value[0]?.toFixed?.(2)} - ${yPrefix}${value[1]?.toFixed?.(2)}`, "Range"];
              }
              return [
                typeof value === "number" ? `${yPrefix}${value.toFixed(2)}` : String(value),
                name === "line" ? lineKeyLabel : name,
              ];
            }}
          />

          {chartData.some((d) => d.range) ? (
            <Area type="monotone" dataKey="range" stroke="none" fill="url(#seriesCone)" />
          ) : null}

          <Line
            type="monotone"
            dataKey="line"
            stroke={lineColor}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
            name={lineKeyLabel}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
