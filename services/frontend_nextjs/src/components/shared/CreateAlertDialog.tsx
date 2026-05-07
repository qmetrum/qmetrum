"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { alertApi } from "@/lib/api";

type Props = {
  open: boolean;
  onClose: () => void;
  tickers: string[];
  defaultTicker?: string;
  currentPrice?: number | null;
};

export function CreateAlertDialog({
  open,
  onClose,
  tickers,
  defaultTicker,
  currentPrice,
}: Props) {
  const queryClient = useQueryClient();

  const initialTicker = (defaultTicker ?? tickers[0] ?? "").toUpperCase();
  const [ticker, setTicker] = useState(initialTicker);
  const [direction, setDirection] = useState<"above" | "below">("above");
  const [threshold, setThreshold] = useState<string>(
    currentPrice != null ? String(Number(currentPrice).toFixed(2)) : "",
  );
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setTicker(initialTicker);
      setDirection("above");
      setThreshold(currentPrice != null ? String(Number(currentPrice).toFixed(2)) : "");
      setName("");
      setError(null);
    }
  }, [open, initialTicker, currentPrice]);

  const createMutation = useMutation({
    mutationFn: async () => {
      const thresholdNum = parseFloat(threshold);
      const t = ticker.trim().toUpperCase();
      const autoName = `${t} ${direction} ${thresholdNum}`;
      const rule = await alertApi.create({
        name: name.trim() || autoName,
        ticker: t,
        alert_type: "price_threshold",
        direction,
        threshold_value: thresholdNum,
        is_active: true,
      });
      // Evaluate immediately so an AlertEvent row exists (and the Dashboard
      // feed reflects it if the threshold is already crossed).
      await alertApi.evaluate({ active_only: true, persist: true });
      return rule;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alert-events"] });
      queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
      onClose();
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Failed to create alert";
      setError(msg);
    },
  });

  const handleSubmit = () => {
    setError(null);
    const thresholdNum = parseFloat(threshold);
    if (!ticker.trim()) {
      setError("Ticker is required");
      return;
    }
    if (!isFinite(thresholdNum) || thresholdNum <= 0) {
      setError("Threshold must be a positive number");
      return;
    }
    createMutation.mutate();
  };

  if (!open) return null;

  const singleTicker = tickers.length === 1;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="q-card w-full max-w-md p-6 space-y-4">
        <h2 className="text-lg font-semibold text-[var(--text-primary)]">
          Create Alert
        </h2>

        <div>
          <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
            Ticker
          </label>
          {singleTicker ? (
            <div className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm font-semibold text-[var(--navy)]">
              {ticker}
            </div>
          ) : (
            <select
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm text-[var(--text-primary)]"
            >
              {tickers.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
              Direction
            </label>
            <select
              value={direction}
              onChange={(e) => setDirection(e.target.value as "above" | "below")}
              className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm text-[var(--text-primary)]"
            >
              <option value="above">Above</option>
              <option value="below">Below</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
              Threshold ($)
            </label>
            <input
              type="number"
              step="0.01"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm text-[var(--text-primary)]"
            />
          </div>
        </div>

        <div>
          <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
            Name (optional)
          </label>
          <input
            type="text"
            placeholder={`${ticker} ${direction} ${threshold || "…"}`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm text-[var(--text-primary)]"
          />
        </div>

        {error && (
          <p className="text-xs text-[var(--coral)]">{error}</p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="text-sm font-medium text-[var(--text-muted)] px-4 py-2 hover:underline"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={createMutation.isPending}
            className="text-sm font-medium bg-[var(--teal)] text-white px-4 py-2 rounded-lg hover:opacity-90 disabled:opacity-50"
          >
            {createMutation.isPending ? "Creating..." : "Create Alert"}
          </button>
        </div>
      </div>
    </div>
  );
}
