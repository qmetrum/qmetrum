import type { Metadata } from "next";

// Server component so this public marketing page gets its own <title>/OG tags
// for the shareable link (the page itself is a client component and can't
// export metadata directly).
export const metadata: Metadata = {
  title: "Is the 60/40 still diversified? — Cross-Asset Correlation Monitor by Qmetrum",
  description:
    "A free, daily measurement of realized stock–bond and cross-asset correlations. See whether the diversification your allocation assumes still holds. Measurement, not prediction — every number reproducible.",
  openGraph: {
    title: "Is the 60/40 still diversified?",
    description:
      "Free daily realized cross-asset correlations. Measurement, not prediction.",
    type: "website",
  },
};

export default function CorrelationsLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
