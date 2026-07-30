import Link from "next/link";

// Branded 404 for bad routes / unknown portfolio or asset ids, instead of the
// default Next.js not-found page.
export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="text-3xl font-bold text-[var(--navy)]">404</div>
      <p className="max-w-md text-sm text-[var(--text-secondary)]">
        This page could not be found. It may have been moved, or the link is incorrect.
      </p>
      <Link
        href="/dashboard"
        className="rounded-lg bg-[var(--teal)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
      >
        Back to dashboard
      </Link>
    </div>
  );
}
