"use client";

type Props = {
  regime: string;
  size?: "sm" | "md";
};

// Theme-aware: these palette vars adapt in dark mode (see globals.css html.dark).
const REGIME_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  Normal: { bg: "bg-[var(--teal-light)]", text: "text-[var(--teal-muted)]", label: "Normal" },
  High_Fragility: { bg: "bg-[var(--coral-light)]", text: "text-[var(--coral)]", label: "High Fragility" },
  High_Vol: { bg: "bg-[var(--coral-light)]", text: "text-[var(--coral)]", label: "High Volatility" },
  Drawdown: { bg: "bg-[var(--amber-light)]", text: "text-[var(--amber)]", label: "Drawdown" },
  Low_Vol: { bg: "bg-[var(--blue-light)]", text: "text-[var(--blue)]", label: "Low Vol Stable" },
  Low_Vol_Stable: { bg: "bg-[var(--blue-light)]", text: "text-[var(--blue)]", label: "Low Vol Stable" },
};

export function RegimeBadge({ regime, size = "md" }: Props) {
  const style = REGIME_STYLES[regime] ?? REGIME_STYLES["Normal"];
  const padding = size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-3 py-1 text-xs";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-semibold ${style.bg} ${style.text} ${padding}`}
    >
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${
        regime === "Normal" ? "bg-[var(--teal)]" :
        regime === "Drawdown" ? "bg-[var(--amber)]" :
        regime.includes("High") ? "bg-[var(--coral)]" : "bg-[var(--blue)]"
      }`} />
      {style.label}
    </span>
  );
}
