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

type VolatilityChartProps = {
  /** Daily prices (historical) — volatility is computed client-side */
  historyPrices: number[];
  historyDates: string[];
  /** Optional GARCH forecast volatility (annualized, as decimals) */
  forecastVol?: number[];
  /** Optional GARCH forecast cone bounds (annualized, as decimals) */
  forecastVolLower?: number[];
  forecastVolUpper?: number[];
  forecastDates?: string[];
  /** Rolling window for realized vol (trading days) */
  window?: number;
  height?: number;
};

function rollingVol(prices: number[], window: number): number[] {
  const returns: number[] = [];
  for (let i = 1; i < prices.length; i++) {
    returns.push(Math.log(prices[i] / prices[i - 1]));
  }
  const vol: number[] = [0]; // pad first
  for (let i = 0; i < returns.length; i++) {
    if (i < window - 1) {
      vol.push(0);
      continue;
    }
    const slice = returns.slice(i - window + 1, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / slice.length;
    const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / (slice.length - 1);
    vol.push(Math.sqrt(variance) * Math.sqrt(252) * 100);
  }
  return vol;
}

export function VolatilityChart({
  historyPrices,
  historyDates,
  forecastVol,
  forecastVolLower,
  forecastVolUpper,
  forecastDates,
  window = 21,
  height = 260,
}: VolatilityChartProps) {
  const histLen = Math.min(historyPrices.length, historyDates.length);
  const vol = rollingVol(historyPrices.slice(-180), window);
  const dates = historyDates.slice(-(vol.length));

  const startIdx = vol.findIndex((v) => v > 0);
  const data: Record<string, number | string | null>[] = [];

  for (let i = Math.max(startIdx, 0); i < vol.length; i++) {
    data.push({
      date: dates[i],
      realizedVol: vol[i] > 0 ? +vol[i].toFixed(2) : null,
      forecastVol: null,
      coneBandFloor: 0,
      coneBandWidth: 0,
    });
  }

  const hasCone =
    forecastVolLower && forecastVolUpper &&
    forecastVolLower.length > 0 && forecastVolUpper.length > 0;

  // Append forecast vol + cone
  if (forecastVol && forecastDates) {
    // Overlap point: connect realized vol to forecast
    if (data.length > 0 && forecastVol.length > 0) {
      const lo = hasCone ? +(forecastVolLower![0] * 100).toFixed(2) : 0;
      const hi = hasCone ? +(forecastVolUpper![0] * 100).toFixed(2) : 0;
      data[data.length - 1] = {
        ...data[data.length - 1],
        forecastVol: +(forecastVol[0] * 100).toFixed(2),
        coneBandFloor: lo,
        coneBandWidth: Math.max(0, hi - lo),
      };
    }
    for (let i = 0; i < forecastVol.length; i++) {
      const lo = hasCone && i < forecastVolLower!.length ? +(forecastVolLower![i] * 100).toFixed(2) : 0;
      const hi = hasCone && i < forecastVolUpper!.length ? +(forecastVolUpper![i] * 100).toFixed(2) : 0;
      data.push({
        date: forecastDates[i],
        realizedVol: null,
        forecastVol: +(forecastVol[i] * 100).toFixed(2),
        coneBandFloor: lo,
        coneBandWidth: Math.max(0, hi - lo),
      });
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
        <YAxis
          tick={{ fontSize: 10, fill: "#8B95A2" }}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip
          contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
          labelFormatter={(v) => new Date(v as string).toLocaleDateString()}
          // @ts-expect-error recharts Formatter typing quirk
          formatter={(value: number, name: string) => {
            if (name === "coneBandFloor" || name === "coneBandWidth") return [null, null];
            const labels: Record<string, string> = { realizedVol: "Realized Vol", forecastVol: "GARCH Forecast" };
            return [`${value?.toFixed(1)}%`, labels[name] ?? name];
          }}
        />

        {/* Forecast vol cone band (stacked area: transparent floor + shaded width) */}
        <Area
          dataKey="coneBandFloor"
          stackId="volCone"
          stroke="none"
          fill="none"
          isAnimationActive={false}
          legendType="none"
          activeDot={false}
        />
        <Area
          dataKey="coneBandWidth"
          stackId="volCone"
          type="monotone"
          stroke="none"
          fill="#D4920B"
          fillOpacity={0.12}
          isAnimationActive={false}
          name="GARCH cone"
        />

        {/* Realized vol (solid dark line) */}
        <Line dataKey="realizedVol" stroke="#2D3E50" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls={false} name="Realized Vol" />

        {/* GARCH forecast representative path (dashed amber, full visibility).
            Uses a simulated GARCH vol path with realistic day-to-day variation,
            not the flat analytical mean. */}
        <Line dataKey="forecastVol" stroke="#D4920B" strokeWidth={2} strokeDasharray="4 3" dot={false} isAnimationActive={false} connectNulls={false} name="GARCH Forecast" />

        {todayDate && (
          <ReferenceLine x={todayDate} stroke="#8B95A2" strokeWidth={1} strokeDasharray="4 3" />
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
