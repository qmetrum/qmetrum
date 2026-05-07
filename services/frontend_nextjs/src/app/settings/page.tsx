"use client";

import { useState, useRef } from "react";
import { useBranding } from "@/components/providers/BrandingProvider";

export default function SettingsPage() {
  const branding = useBranding();
  const [saved, setSaved] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function handleSave() {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  function handleLogoUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 500_000) {
      alert("Logo must be under 500 KB");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      branding.update({ logoDataUrl: reader.result as string });
    };
    reader.readAsDataURL(file);
  }

  function removeLogo() {
    branding.update({ logoDataUrl: null });
  }

  const inputCls =
    "w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--teal)]";

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-[var(--navy)]">Settings</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Configure firm branding, alert thresholds, and preferences
        </p>
      </div>

      {/* Firm Branding */}
      <div className="q-card p-5 space-y-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">Firm Branding</h2>
        <p className="text-xs text-[var(--text-muted)]">
          Used for white-label PDF reports and displayed in the app header
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Firm Name</label>
            <input
              value={branding.firmName}
              onChange={(e) => branding.update({ firmName: e.target.value })}
              className={inputCls}
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Advisor Name</label>
            <input
              value={branding.advisorName}
              onChange={(e) => branding.update({ advisorName: e.target.value })}
              className={inputCls}
            />
          </div>
        </div>

        {/* Logo upload */}
        <div>
          <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Firm Logo</label>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/svg+xml"
            onChange={handleLogoUpload}
            className="hidden"
          />
          {branding.logoDataUrl ? (
            <div className="flex items-center gap-4">
              <div className="flex h-16 w-40 items-center justify-center rounded-lg border border-[var(--border)] bg-white p-2">
                <img
                  src={branding.logoDataUrl}
                  alt="Firm logo"
                  className="max-h-full max-w-full object-contain"
                />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => fileRef.current?.click()}
                  className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] hover:bg-[var(--content-bg)]"
                >
                  Replace
                </button>
                <button
                  onClick={removeLogo}
                  className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--coral)] hover:bg-[var(--content-bg)]"
                >
                  Remove
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => fileRef.current?.click()}
              className="flex h-24 w-full items-center justify-center rounded-lg border-2 border-dashed border-[var(--border)] bg-[var(--content-bg)] text-sm text-[var(--text-muted)] hover:border-[var(--teal)] hover:text-[var(--teal)] transition-colors cursor-pointer"
            >
              Click to upload logo (PNG, JPG, SVG &mdash; max 500 KB)
            </button>
          )}
        </div>
      </div>

      {/* Alert Thresholds */}
      <div className="q-card p-5 space-y-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">Alert Thresholds</h2>
        <p className="text-xs text-[var(--text-muted)]">
          Configure when alerts trigger for portfolio monitoring
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">
              Fragility Score Trigger
            </label>
            <input
              value={branding.fragilityThreshold}
              onChange={(e) => branding.update({ fragilityThreshold: e.target.value })}
              type="number"
              step="0.1"
              className={inputCls}
            />
            <p className="mt-1 text-[10px] text-[var(--text-muted)]">
              Alert when fragility exceeds this value (default: 1.5)
            </p>
          </div>
          <div>
            <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">
              Rebalance Drift (%)
            </label>
            <input
              value={branding.rebalanceDrift}
              onChange={(e) => branding.update({ rebalanceDrift: e.target.value })}
              type="number"
              step="0.5"
              className={inputCls}
            />
            <p className="mt-1 text-[10px] text-[var(--text-muted)]">
              Alert when allocation drifts by this percentage
            </p>
          </div>
        </div>
      </div>

      {/* Preferences */}
      <div className="q-card p-5 space-y-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">Preferences</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="text-xs font-semibold text-[var(--text-muted)] block mb-1">Theme</label>
            <div className="flex gap-2">
              <button
                onClick={() => branding.update({ theme: "light" })}
                className={`flex-1 rounded-lg border px-4 py-3 text-sm font-medium transition-all ${
                  branding.theme === "light"
                    ? "border-[var(--teal)] bg-[var(--teal-light)] text-[var(--teal)]"
                    : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--text-muted)]"
                }`}
              >
                <div className="flex items-center gap-2">
                  <div className="h-4 w-4 rounded-full bg-white border border-[#DDE1E6]" />
                  Light
                </div>
              </button>
              <button
                onClick={() => branding.update({ theme: "dark" })}
                className={`flex-1 rounded-lg border px-4 py-3 text-sm font-medium transition-all ${
                  branding.theme === "dark"
                    ? "border-[var(--teal)] bg-[var(--teal-light)] text-[var(--teal)]"
                    : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--text-muted)]"
                }`}
              >
                <div className="flex items-center gap-2">
                  <div className="h-4 w-4 rounded-full bg-[#0E1320] border border-[#2A3548]" />
                  Dark
                </div>
              </button>
            </div>
          </div>
          <div className="rounded-lg bg-[var(--content-bg)] px-4 py-3">
            <span className="text-xs font-semibold text-[var(--text-muted)]">Default Horizon</span>
            <p className="text-sm font-medium text-[var(--text-primary)]">90 days</p>
          </div>
        </div>
      </div>

      <button
        onClick={handleSave}
        className="rounded-lg bg-[var(--teal)] px-6 py-2.5 text-sm font-semibold text-white hover:opacity-90 transition-opacity"
      >
        {saved ? "Saved!" : "Save Settings"}
      </button>
    </div>
  );
}
