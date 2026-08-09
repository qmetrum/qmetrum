"use client";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import type { CorrelationSeriesPoint } from "@/lib/api";

type Props = {
  series: CorrelationSeriesPoint[];
  /** Line color (defaults to teal). */
  color?: string;
  label?: string;
  height?: number;
};

const fmtDate = (v: string) => {
  const d = new Date(v);
  return `${d.toLocaleString("default", { month: "short" })} '${String(d.getFullYear()).slice(2)}`;
};

/** Rolling realized correlation over time, bounded to [-1, 1] with a zero line. */
export function CorrelationChart({ series, color = "#0F8B6E", label, height = 180 }: Props) {
  if (!series || series.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-[var(--text-muted)]"
        style={{ height }}
      >
        Insufficient history
      </div>
    );
  }
  const data = series.map((p) => ({ date: p.date, corr: p.corr }));

  return (
    <div role="img" aria-label={`Rolling realized correlation over time${label ? `: ${label}` : ""}.`}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart accessibilityLayer data={data} margin={{ top: 6, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F3" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: "#8B95A2" }}
            tickFormatter={fmtDate}
            interval="preserveStartEnd"
            minTickGap={48}
          />
          <YAxis
            domain={[-1, 1]}
            ticks={[-1, -0.5, 0, 0.5, 1]}
            tick={{ fontSize: 10, fill: "#8B95A2" }}
            tickFormatter={(v) => (v as number).toFixed(1)}
            width={30}
          />
          <ReferenceLine y={0} stroke="#B8C0CC" strokeWidth={1} />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
            labelFormatter={(v) => new Date(v as string).toLocaleDateString()}
            // @ts-expect-error recharts Formatter typing quirk
            formatter={(value: number) => [Number(value ?? 0).toFixed(2), "Correlation"]}
          />
          <Line
            dataKey="corr"
            stroke={color}
            strokeWidth={1.6}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
