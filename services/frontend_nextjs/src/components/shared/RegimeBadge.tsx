"use client";

type Props = {
  regime: string;
  size?: "sm" | "md";
};

const REGIME_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  Normal: { bg: "bg-[#E6F5F0]", text: "text-[#0A6B54]", label: "Normal" },
  High_Fragility: { bg: "bg-[#FDECEC]", text: "text-[#B03A1A]", label: "High Fragility" },
  High_Vol: { bg: "bg-[#FDECEC]", text: "text-[#B03A1A]", label: "High Volatility" },
  Drawdown: { bg: "bg-[#FFF1E6]", text: "text-[#B5560B]", label: "Drawdown" },
  Low_Vol: { bg: "bg-[#EAF2FB]", text: "text-[#1D5EA0]", label: "Low Vol Stable" },
  Low_Vol_Stable: { bg: "bg-[#EAF2FB]", text: "text-[#1D5EA0]", label: "Low Vol Stable" },
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
