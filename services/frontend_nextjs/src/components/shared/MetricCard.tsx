"use client";

type Props = {
  label: string;
  value: string;
  sub?: string;
  trend?: "up" | "down" | "neutral";
  color?: "navy" | "teal" | "coral" | "amber" | "blue" | "slate";
};

const COLOR_MAP: Record<string, string> = {
  navy: "text-[var(--navy)]",
  teal: "text-[var(--teal)]",
  coral: "text-[var(--coral)]",
  amber: "text-[var(--amber)]",
  blue: "text-[var(--blue)]",
  slate: "text-[var(--slate)]",
};

const TREND_ARROW: Record<string, string> = {
  up: "\u25B2",
  down: "\u25BC",
  neutral: "\u2014",
};

export function MetricCard({ label, value, sub, trend, color = "navy" }: Props) {
  return (
    <div className="q-card flex flex-col gap-1 px-5 py-4">
      <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <div className="flex items-baseline gap-2">
        <span className={`text-2xl font-bold ${COLOR_MAP[color]}`}>{value}</span>
        {trend && (
          <span
            className={`text-xs font-semibold ${
              trend === "up" ? "text-[var(--positive)]" : trend === "down" ? "text-[var(--negative)]" : "text-[var(--text-muted)]"
            }`}
          >
            {TREND_ARROW[trend]}
          </span>
        )}
      </div>
      {sub && (
        <span className="text-xs text-[var(--text-secondary)]">{sub}</span>
      )}
    </div>
  );
}
