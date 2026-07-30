"use client";

// Route-level error boundary: catches render/data throws in any page and shows
// a branded, recoverable fallback instead of the raw Next.js error overlay.
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="text-2xl font-bold text-[var(--navy)]">Something went wrong</div>
      <p className="max-w-md text-sm text-[var(--text-secondary)]">
        An unexpected error occurred while loading this view. Your saved data is not affected.
      </p>
      {error?.digest && (
        <p className="text-[11px] text-[var(--text-muted)]">Reference: {error.digest}</p>
      )}
      <button
        onClick={() => reset()}
        className="rounded-lg bg-[var(--teal)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
      >
        Try again
      </button>
    </div>
  );
}
