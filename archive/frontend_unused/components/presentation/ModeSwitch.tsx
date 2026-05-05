"use client";

import React from "react";
import { clsx } from "clsx";
import { usePresentationMode } from "@/components/presentation/PresentationModeProvider";

export function ModeSwitch({ compact = false }: { compact?: boolean }) {
  const { mode, setMode } = usePresentationMode();

  if (compact) {
    return (
      <div className="w-full rounded-xl border border-white/10 bg-white/4 p-1">
        <div className="grid grid-cols-2 gap-1 text-[10px]">
          <button
            type="button"
            onClick={() => setMode("guided")}
            className={clsx(
              "rounded-lg px-2 py-1 font-semibold transition-colors",
              mode === "guided"
                ? "bg-[#095DB0]/30 text-[#9cccff]"
                : "text-[color:var(--text-muted)] hover:text-white",
            )}
            title="Guided mode"
          >
            G
          </button>
          <button
            type="button"
            onClick={() => setMode("pro")}
            className={clsx(
              "rounded-lg px-2 py-1 font-semibold transition-colors",
              mode === "pro"
                ? "bg-[#095DB0]/30 text-[#9cccff]"
                : "text-[color:var(--text-muted)] hover:text-white",
            )}
            title="Pro mode"
          >
            P
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-white/10 bg-white/4 p-1">
      <div className="px-1 pb-1 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
        Audience
      </div>
      <div className="grid grid-cols-2 gap-1">
        <button
          type="button"
          onClick={() => setMode("guided")}
          className={clsx(
            "rounded-lg px-2 py-1.5 text-xs font-medium transition-colors",
            mode === "guided"
              ? "bg-[#095DB0]/30 text-[#9cccff]"
              : "text-[color:var(--text-secondary)] hover:text-white",
          )}
        >
          Guided
        </button>
        <button
          type="button"
          onClick={() => setMode("pro")}
          className={clsx(
            "rounded-lg px-2 py-1.5 text-xs font-medium transition-colors",
            mode === "pro"
              ? "bg-[#095DB0]/30 text-[#9cccff]"
              : "text-[color:var(--text-secondary)] hover:text-white",
          )}
        >
          Pro
        </button>
      </div>
      <div className="mt-1 px-1 text-[10px] text-[color:var(--text-muted)]">
        Guided: summary-first · Pro: full detail
      </div>
    </div>
  );
}
