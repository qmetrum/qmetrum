"use client";

import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { useMemo, useState } from "react";
import type { ScenarioFan } from "@/lib/api";

type ScenarioSpec = {
  name: string;
  color: string;
};

type ScenarioPathsChartProps = {
  /** Per-scenario fan object, keyed by scenario name. Audit keys prefixed with "_" are skipped. */
  fans: Record<string, ScenarioFan | unknown>;
  /** Forecast dates aligned with each fan path. */
  dates: string[];
  /** Scenario display metadata (name + colour). Unknown-name entries fall back to a default colour. */
  scenarios: ScenarioSpec[];
  height?: number;
};

export const DEFAULT_COLOR = "#7C5CBF";
export const ADVERSARIAL_COLOR = "#B91C1C"; // distinct red for the discovered worst-case

export const DISPLAY_NAMES: Record<string, string> = {
  worst_case_cvar: "Adversarial worst-case",
  base: "Base",
  bull_10: "Bull +10%",
  bear_10: "Bear -10%",
  high_vol_regime: "High vol",
  low_vol_regime: "Low vol",
};

/** Server built-in calibration scenarios (one knob at a time). The user can
 *  exclude/re-include these per run via include_builtin_scenarios. */
export const BUILTIN_SCENARIO_INFO: Record<string, string> = {
  bull_10: "Built-in: pure +10% starting-price shock — volatility and drift unchanged",
  bear_10: "Built-in: pure −10% starting-price shock — volatility and drift unchanged",
  high_vol_regime: "Built-in: volatility ×1.25, no price shock",
  low_vol_regime: "Built-in: volatility ×0.75, no price shock",
};

/** Always-generated server scenarios (not toggleable). */
export const AUTO_SCENARIO_INFO: Record<string, string> = {
  base: "Reference: no shock, no vol change — the baseline the other scenarios compare against",
  worst_case_cvar:
    "Auto-discovered: gradient search over correlated asset shocks that maximises tail loss (CVaR)",
};

/** Origin label for a scenario name; null for the user's own scenarios. */
export function scenarioOrigin(name: string): "Built-in" | "Reference" | "Auto-discovered" | null {
  if (name in BUILTIN_SCENARIO_INFO) return "Built-in";
  if (name === "base") return "Reference";
  if (name === "worst_case_cvar") return "Auto-discovered";
  return null;
}

function fanHas1s(f: ScenarioFan): boolean {
  return Array.isArray(f.lower_1s) && Array.isArray(f.upper_1s) && f.lower_1s.length > 0;
}

function fanHas2s(f: ScenarioFan): boolean {
  return Array.isArray(f.lower_2s) && Array.isArray(f.upper_2s) && f.lower_2s.length > 0;
}

export function ScenarioPathsChart({
  fans,
  dates,
  scenarios,
  height = 360,
}: ScenarioPathsChartProps) {
  // Build the canonical ordered list of scenario names from the blob,
  // skipping audit keys and any entries without a usable central path.
  const scenarioNames = useMemo(() => {
    return Object.entries(fans)
      .filter(([k, v]) => !k.startsWith("_") && v && typeof v === "object" && Array.isArray((v as ScenarioFan).central))
      .map(([k]) => k);
  }, [fans]);

  const colourFor = useMemo(() => {
    const map: Record<string, string> = {};
    for (const s of scenarios) map[s.name] = s.color;
    map["worst_case_cvar"] = ADVERSARIAL_COLOR;
    return (name: string) => map[name] ?? DEFAULT_COLOR;
  }, [scenarios]);

  const [selected, setSelected] = useState<string | null>(null);
  const effectiveSelected = selected && scenarioNames.includes(selected) ? selected : null;

  // Build chart row data. Band fields are always populated for every scenario
  // that has them; rendering visibility is controlled by fillOpacity, not by
  // mounting/unmounting <Area> components (recharts doesn't handle dynamic children well).
  const data = useMemo(() => {
    const nPoints = Math.min(
      dates.length,
      ...scenarioNames.map((n) => (fans[n] as ScenarioFan).central.length),
    );

    const rows: Record<string, number | string | undefined>[] = [];
    for (let i = 0; i < nPoints; i++) {
      const row: Record<string, number | string | undefined> = { date: dates[i] };
      for (const name of scenarioNames) {
        row[name] = (fans[name] as ScenarioFan).central[i];
      }
      // Pre-compute band fields for whichever scenario is selected (or none).
      // Default to 0/0 so the Areas always have numeric data.
      row.band1Floor = 0;
      row.band1Width = 0;
      row.band2Floor = 0;
      row.band2Width = 0;
      rows.push(row);
    }
    return rows;
  }, [dates, scenarioNames, fans]);

  // Patch band data into rows when selection changes (mutating is fine on derived data).
  const dataWithBands = useMemo(() => {
    const rows = data.map((r) => ({ ...r, band1Floor: 0, band1Width: 0, band2Floor: 0, band2Width: 0 }));
    if (!effectiveSelected) return rows;
    const selFan = fans[effectiveSelected] as ScenarioFan;
    const has1 = fanHas1s(selFan);
    const has2 = fanHas2s(selFan);
    for (let i = 0; i < rows.length; i++) {
      if (has2) {
        const lo = (selFan.lower_2s as number[])[i] ?? 0;
        const hi = (selFan.upper_2s as number[])[i] ?? 0;
        rows[i].band2Floor = lo;
        rows[i].band2Width = Math.max(0, hi - lo);
      }
      if (has1) {
        const lo = (selFan.lower_1s as number[])[i] ?? 0;
        const hi = (selFan.upper_1s as number[])[i] ?? 0;
        rows[i].band1Floor = lo;
        rows[i].band1Width = Math.max(0, hi - lo);
      }
    }
    return rows;
  }, [data, effectiveSelected, fans]);

  if (scenarioNames.length === 0 || dataWithBands.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-[var(--text-muted)]"
        style={{ height }}
      >
        No scenario paths to show
      </div>
    );
  }

  const fmtDate = (v: string) => {
    const d = new Date(v);
    return `${d.toLocaleString("default", { month: "short" })} ${d.getDate()}`;
  };

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Scenario focus
        </span>
        <button
          onClick={() => setSelected(null)}
          className={`rounded px-2 py-0.5 text-[11px] font-medium transition-colors ${
            effectiveSelected === null
              ? "bg-[var(--btn-navy)] text-white"
              : "border border-[var(--border)] bg-white text-[var(--text-primary)] hover:bg-[var(--content-bg)]"
          }`}
        >
          All
        </button>
        {scenarioNames.map((name) => {
          const active = effectiveSelected === name;
          return (
            <button
              key={name}
              onClick={() => setSelected(active ? null : name)}
              className={`rounded px-2 py-0.5 text-[11px] font-medium transition-colors ${
                active
                  ? "text-white"
                  : "border border-[var(--border)] bg-white text-[var(--text-primary)] hover:bg-[var(--content-bg)]"
              }`}
              style={active ? { backgroundColor: colourFor(name) } : { borderColor: colourFor(name) }}
            >
              <span
                className="mr-1 inline-block h-2 w-2 rounded-full align-middle"
                style={{ backgroundColor: colourFor(name) }}
              />
              {DISPLAY_NAMES[name] ?? name}
            </button>
          );
        })}
      </div>

      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={dataWithBands} margin={{ top: 5, right: 15, left: 24, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F3" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: "#8B95A2" }}
            tickFormatter={fmtDate}
            interval="preserveStartEnd"
            minTickGap={50}
          />
          <YAxis tick={{ fontSize: 10, fill: "#8B95A2" }} domain={["auto", "auto"]} label={{ value: "Portfolio value ($)", angle: -90, position: "insideLeft", fontSize: 11, fill: "#8B95A2" }} />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E2E6EB" }}
            labelFormatter={(v) => new Date(v as string).toLocaleDateString()}
            // @ts-expect-error recharts Formatter typing quirk (matches existing pattern)
            formatter={(value: number, name: string) => {
              if (value === undefined || value === null || Number.isNaN(value)) return ["-", name];
              // Hide the band-floor/band-width helper series from the tooltip
              if (name === "band1Floor" || name === "band1Width" || name === "band2Floor" || name === "band2Width") {
                return [null, null];
              }
              return [Number(value).toFixed(2), name];
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} iconType="line" />

          {/* Bands always mounted (recharts requires static children); visibility via opacity. */}
          <Area
            dataKey="band2Floor"
            stackId="band2"
            stroke="none"
            fill="none"
            isAnimationActive={false}
            legendType="none"
            activeDot={false}
          />
          <Area
            dataKey="band2Width"
            stackId="band2"
            type="monotone"
            stroke="none"
            fill={effectiveSelected ? colourFor(effectiveSelected) : "transparent"}
            fillOpacity={effectiveSelected ? 0.08 : 0}
            isAnimationActive={false}
            name="±2σ"
          />
          <Area
            dataKey="band1Floor"
            stackId="band1"
            stroke="none"
            fill="none"
            isAnimationActive={false}
            legendType="none"
            activeDot={false}
          />
          <Area
            dataKey="band1Width"
            stackId="band1"
            type="monotone"
            stroke="none"
            fill={effectiveSelected ? colourFor(effectiveSelected) : "transparent"}
            fillOpacity={effectiveSelected ? 0.18 : 0}
            isAnimationActive={false}
            name="±1σ"
          />

          {/* Central lines for every scenario. Non-selected ones fade when a selection is active. */}
          {scenarioNames.map((name) => {
            const isSelected = effectiveSelected === name;
            const isFaded = effectiveSelected !== null && !isSelected;
            return (
              <Line
                key={name}
                dataKey={name}
                type="monotone"
                stroke={colourFor(name)}
                strokeWidth={isSelected ? 2.4 : 1.4}
                strokeOpacity={isFaded ? 0.3 : 1}
                dot={false}
                isAnimationActive={false}
                name={name}
                connectNulls={false}
              />
            );
          })}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
