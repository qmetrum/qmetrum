"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";

type ToastKind = "success" | "error" | "info";
type ToastItem = { id: number; message: string; kind: ToastKind };
type ToastCtx = { toast: (message: string, kind?: ToastKind) => void };

const Ctx = createContext<ToastCtx | null>(null);

// Safe outside a provider (returns a no-op) so components can always call it.
export function useToast(): ToastCtx {
  return useContext(Ctx) ?? { toast: () => {} };
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const toast = useCallback((message: string, kind: ToastKind = "info") => {
    const id = ++idRef.current;
    setItems((t) => [...t, { id, message, kind }]);
    setTimeout(() => setItems((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);

  return (
    <Ctx.Provider value={{ toast }}>
      {children}
      {/* Accessible toast host: announces success/error to screen readers. */}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-[60] flex max-w-[90vw] flex-col gap-2"
        aria-live="polite"
        role="status"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto rounded-lg border px-4 py-2.5 text-sm font-medium shadow-lg ${
              t.kind === "success"
                ? "border-[var(--teal)]/30 bg-[var(--teal-light)] text-[var(--teal-muted)]"
                : t.kind === "error"
                  ? "border-[var(--coral)]/30 bg-[var(--coral-light)] text-[var(--coral)]"
                  : "border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--text-primary)]"
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
