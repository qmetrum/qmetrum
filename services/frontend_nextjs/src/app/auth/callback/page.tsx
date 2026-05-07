"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "react-oidc-context";

/**
 * OIDC redirect target. After Cognito redirects back here with `?code=...`,
 * react-oidc-context completes the token exchange in the background; this
 * page only needs to wait for `auth.isAuthenticated` and then bounce the
 * user to the app shell.
 */
export default function AuthCallbackPage() {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (auth.isLoading) return;
    if (auth.error) return;
    if (auth.isAuthenticated) {
      router.replace("/dashboard");
    }
  }, [auth.isLoading, auth.error, auth.isAuthenticated, router]);

  if (auth.error) {
    return (
      <div className="p-8 text-sm">
        <h1 className="text-lg font-semibold mb-2 text-[var(--coral)]">Sign-in failed</h1>
        <p>{auth.error.message}</p>
        <button
          onClick={() => auth.signinRedirect()}
          className="mt-4 rounded-lg bg-[var(--teal)] px-4 py-2 text-white text-sm font-medium hover:opacity-90"
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="p-8 text-sm text-[var(--text-muted)]">
      Completing sign-in…
    </div>
  );
}
