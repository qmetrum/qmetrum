"use client";

type Props = {
  label?: string;
  data: unknown;
};

function isPrimitive(v: unknown): v is string | number | boolean | null {
  return v === null || typeof v === "string" || typeof v === "number" || typeof v === "boolean";
}

function formatPrimitive(v: string | number | boolean | null): string {
  if (v === null) return "—";
  if (typeof v === "number") {
    if (Math.abs(v) > 0 && Math.abs(v) < 0.01) return v.toExponential(2);
    return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/\.?0+$/, "");
  }
  return String(v);
}

function Row({ label, value, depth = 0 }: { label: string; value: unknown; depth?: number }) {
  if (isPrimitive(value)) {
    return (
      <div
        className="flex gap-3 py-0.5"
        style={{ paddingLeft: `${depth * 10}px` }}
      >
        <span className="text-[11px] font-medium text-[var(--text-muted)] min-w-[120px]">{label}</span>
        <span className="text-[11px] text-[var(--text-primary)] break-all">{formatPrimitive(value)}</span>
      </div>
    );
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <Row label={label} value={null} depth={depth} />;
    }
    if (value.every(isPrimitive)) {
      return (
        <Row
          label={label}
          value={value.map((v) => formatPrimitive(v as string | number | boolean | null)).join(", ")}
          depth={depth}
        />
      );
    }
    return (
      <div style={{ paddingLeft: `${depth * 10}px` }} className="py-0.5">
        <div className="text-[11px] font-medium text-[var(--text-muted)]">{label}</div>
        <div className="mt-0.5 space-y-0.5">
          {value.map((v, i) => (
            <div
              key={i}
              className="rounded border border-[var(--card-border)] bg-white px-2 py-1"
            >
              {typeof v === "object" && v !== null ? (
                <KeyValueTree data={v as Record<string, unknown>} depth={0} />
              ) : (
                <span className="text-[11px] text-[var(--text-primary)]">
                  {formatPrimitive(v as string | number | boolean | null)}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (typeof value === "object" && value !== null) {
    return (
      <div style={{ paddingLeft: `${depth * 10}px` }} className="py-0.5">
        <div className="text-[11px] font-medium text-[var(--text-muted)]">{label}</div>
        <div className="mt-0.5 border-l border-[var(--card-border)] pl-2">
          <KeyValueTree data={value as Record<string, unknown>} depth={depth + 1} />
        </div>
      </div>
    );
  }
  return null;
}

function KeyValueTree({ data, depth }: { data: Record<string, unknown>; depth: number }) {
  return (
    <>
      {Object.entries(data).map(([k, v]) => (
        <Row key={k} label={k} value={v} depth={depth} />
      ))}
    </>
  );
}

export function SourceDataPanel({ label = "View source data", data }: Props) {
  if (!data || (typeof data === "object" && !Array.isArray(data) && Object.keys(data as object).length === 0)) {
    return null;
  }
  return (
    <details className="mt-3 group">
      <summary className="cursor-pointer text-[11px] font-medium text-[var(--text-muted)] hover:text-[var(--navy)] select-none">
        {label}
      </summary>
      <div className="mt-2 rounded-lg bg-[var(--content-bg)] p-3">
        {typeof data === "object" && data !== null && !Array.isArray(data) ? (
          <KeyValueTree data={data as Record<string, unknown>} depth={0} />
        ) : (
          <pre className="text-[11px] whitespace-pre-wrap break-all text-[var(--text-primary)]">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </details>
  );
}
