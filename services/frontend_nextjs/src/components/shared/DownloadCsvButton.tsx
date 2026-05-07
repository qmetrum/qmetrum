"use client";

import { downloadCsv, type CsvCell } from "@/lib/csv";

type Props = {
  filename: string;
  // Lazy so we don't serialize the dataset on every render.
  build: () => { headers: string[]; rows: CsvCell[][] };
  disabled?: boolean;
  label?: string;
  className?: string;
};

export function DownloadCsvButton({
  filename,
  build,
  disabled,
  label = "CSV",
  className,
}: Props) {
  const handleClick = () => {
    const { headers, rows } = build();
    if (!rows.length) return;
    downloadCsv(filename, headers, rows);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      title="Download CSV"
      className={
        className ??
        "inline-flex items-center gap-1 text-xs font-medium text-[var(--text-muted)] hover:text-[var(--navy)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      }
    >
      <svg
        className="h-3.5 w-3.5"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
      {label}
    </button>
  );
}
