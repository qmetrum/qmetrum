"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { useAuth } from "react-oidc-context";

/**
 * Auth gate around the app shell.
 *
 * - Unauthenticated visitors are auto-redirected to the Cognito Hosted UI
 *   (which has both Sign in and Create account tabs).
 * - The OIDC `/auth/callback` route is exempt — react-oidc-context is
 *   mid-token-exchange there and handles its own redirect.
 * - On error, shows a small retry screen instead of looping.
 */
const PUBLIC_PATHS = new Set(["/auth/callback", "/correlations"]);

export function AuthGate({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const pathname = usePathname() ?? "/";
  const isPublic = PUBLIC_PATHS.has(pathname);

  useEffect(() => {
    if (isPublic) return;
    if (auth.isLoading) return;
    if (auth.error) return;
    if (auth.activeNavigator) return; // a sign-in/sign-out is already in flight
    if (!auth.isAuthenticated) {
      auth.signinRedirect();
    }
  }, [
    isPublic,
    auth.isLoading,
    auth.error,
    auth.isAuthenticated,
    auth.activeNavigator,
    auth,
  ]);

  if (isPublic) {
    return <>{children}</>;
  }

  if (auth.error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--content-bg)] p-8">
        <div className="max-w-md text-center space-y-3">
          <h1 className="text-lg font-semibold text-[var(--coral)]">Sign-in error</h1>
          <p className="text-sm text-[var(--text-muted)]">{auth.error.message}</p>
          <button
            onClick={() => auth.signinRedirect()}
            className="rounded-lg bg-[var(--teal)] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--content-bg)]">
        <div className="flex items-center gap-3 text-sm text-[var(--text-muted)]">
          <span className="inline-block h-2 w-2 rounded-full bg-[var(--teal)] animate-pulse" />
          Redirecting to sign-in…
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
