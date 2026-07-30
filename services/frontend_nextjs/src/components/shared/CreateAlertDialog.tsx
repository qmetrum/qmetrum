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
  const [alertType, setAlertType] = useState<"price_threshold" | "anomaly">("price_threshold");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setTicker(initialTicker);
      setDirection("above");
      setThreshold(currentPrice != null ? String(Number(currentPrice).toFixed(2)) : "");
      setName("");
      setAlertType("price_threshold");
      setError(null);
    }
  }, [open, initialTicker, currentPrice]);

  const isAnomaly = alertType === "anomaly";

  const createMutation = useMutation({
    mutationFn: async () => {
      const t = ticker.trim().toUpperCase();

      if (isAnomaly) {
        // detector: "qpulse" hands ownership of this rule to POST /qpulse/ingest.
        // Without it the built-in z-score evaluates the same rule every 300s,
        // consuming the shared cooldown and suppressing real Qpulse alerts.
        return alertApi.create({
          name: name.trim() || `${t} anomaly (Qpulse)`,
          ticker: t,
          alert_type: "anomaly",
          is_active: true,
          extra_config: { detector: "qpulse" },
        });
      }

      const thresholdNum = parseFloat(threshold);
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
    if (!ticker.trim()) {
      setError("Ticker is required");
      return;
    }
    if (!isAnomaly) {
      const thresholdNum = parseFloat(threshold);
      if (!isFinite(thresholdNum) || thresholdNum <= 0) {
        setError("Threshold must be a positive number");
        return;
      }
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
          <label htmlFor="alert-ticker" className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
            Ticker
          </label>
          {singleTicker ? (
            <div className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm font-semibold text-[var(--navy)]">
              {ticker}
            </div>
          ) : (
            <select
              id="alert-ticker"
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

        <div>
          <label htmlFor="alert-type" className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
            Alert Type
          </label>
          <select
            id="alert-type"
            value={alertType}
            onChange={(e) => setAlertType(e.target.value as "price_threshold" | "anomaly")}
            className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm text-[var(--text-primary)]"
          >
            <option value="price_threshold">Price threshold</option>
            <option value="anomaly">Anomaly (Qpulse)</option>
          </select>
          {isAnomaly && (
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">
              Alerts arrive from the Qpulse detector, which runs on demand rather than
              continuously. Nothing appears here until you start it.
            </p>
          )}
        </div>

        <div className={`grid grid-cols-2 gap-3 ${isAnomaly ? "hidden" : ""}`}>
          <div>
            <label htmlFor="alert-direction" className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
              Direction
            </label>
            <select
              id="alert-direction"
              value={direction}
              onChange={(e) => setDirection(e.target.value as "above" | "below")}
              className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm text-[var(--text-primary)]"
            >
              <option value="above">Above</option>
              <option value="below">Below</option>
            </select>
          </div>
          <div>
            <label htmlFor="alert-threshold" className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
              Threshold ($)
            </label>
            <input
              id="alert-threshold"
              type="number"
              step="0.01"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              className="w-full rounded border border-[var(--card-border)] bg-[var(--content-bg)] px-3 py-2 text-sm text-[var(--text-primary)]"
            />
          </div>
        </div>

        <div>
          <label htmlFor="alert-name" className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1">
            Name (optional)
          </label>
          <input
            id="alert-name"
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
