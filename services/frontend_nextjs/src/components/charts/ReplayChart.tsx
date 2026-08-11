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
import type { ReplayPoint } from "@/lib/api";

const fmtYear = (v: string) => new Date(v).getFullYear().toString();

// Rolling stock-bond correlation (left axis) overlaid on the 60/40 drawdown
// (right axis). When the correlation line rises above zero AND the drawdown
// deepens together, the diversification stopped working — the whole point.
export function ReplayChart({ points, height = 300 }: { points: ReplayPoint[]; height?: number }) {
  if (!points || points.length === 0) {
    return (
      <div className="flex items-center justify-center text-sm text-[var(--text-muted)]" style={{ height }}>
        No history
      </div>
    );
  }
  return (
    <div role="img" aria-label="Rolling stock-bond correlation over two decades, overlaid on the 60/40 portfolio drawdown.">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={points} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={fmtYear}
            tick={{ fontSize: 10, fill: "#8B95A2" }}
            minTickGap={40}
          />
          <YAxis
            yAxisId="corr"
            domain={[-1, 1]}
            ticks={[-1, -0.5, 0, 0.5, 1]}
            tick={{ fontSize: 10, fill: "#8B95A2" }}
            tickFormatter={(v) => (v as number).toFixed(1)}
            width={30}
          />
          <YAxis
            yAxisId="dd"
            orientation="right"
            domain={["auto", 0]}
            tick={{ fontSize: 10, fill: "#8B95A2" }}
            tickFormatter={(v) => `${v}%`}
            width={38}
          />
          <ReferenceLine yAxisId="corr" y={0} stroke="#B8C0CC" strokeWidth={1} />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
            labelFormatter={(v) => new Date(v as string).toLocaleDateString()}
            // @ts-expect-error recharts Formatter typing quirk
            formatter={(value: number, name: string) => {
              if (name === "60/40 drawdown") return [`${Number(value ?? 0).toFixed(1)}%`, name];
              return [Number(value ?? 0).toFixed(2), "Stock-bond correlation"];
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} iconType="plainline" />
          <Area
            yAxisId="dd"
            dataKey="dd"
            name="60/40 drawdown"
            stroke="#D85A30"
            strokeWidth={1}
            fill="#D85A30"
            fillOpacity={0.12}
            isAnimationActive={false}
          />
          <Line
            yAxisId="corr"
            dataKey="corr"
            name="Stock-bond correlation"
            stroke="#0F8B6E"
            strokeWidth={1.6}
            dot={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
