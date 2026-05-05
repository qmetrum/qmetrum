"use client";

import React from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export function DistributionHistogram({
  rows,
  color = "#3b82f6",
  height = 240,
}: {
  rows: Array<{ bucket: string; count: number }>;
  color?: string;
  height?: number;
}) {
  if (!rows.length) {
    return (
      <div className="flex h-[200px] items-center justify-center rounded border border-dashed border-[var(--terminal-border)] text-sm text-[var(--terminal-muted)]">
        No distribution data available
      </div>
    );
  }

  if (typeof window === "undefined") {
    return <div style={{ height }} className="rounded border border-[var(--terminal-border)] bg-[#11161f]" />;
  }

  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={120}>
        <BarChart data={rows} margin={{ top: 10, right: 12, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
          <XAxis
            dataKey="bucket"
            tick={{ fill: "#94a3b8", fontSize: 10 }}
            angle={-20}
            textAnchor="end"
            interval="preserveStartEnd"
            height={48}
          />
          <YAxis tick={{ fill: "#94a3b8", fontSize: 10 }} width={40} allowDecimals={false} />
          <Tooltip
            contentStyle={{
              border: "1px solid #30363D",
              background: "#161B22",
              borderRadius: "8px",
              color: "#e6edf3",
              fontSize: "12px",
            }}
          />
          <Bar dataKey="count" fill={color} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
