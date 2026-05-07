"use client";

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "react-oidc-context";
import { setAuthToken } from "@/lib/api";

/**
 * Mounted once near the root of the tree.
 * - Mirrors the OIDC user's id_token into the axios module so every
 *   subsequent API call carries the bearer.
 * - On sign-in / sign-out, clears the React Query cache so we never serve
 *   data fetched under a different user identity.
 * - Also clears the localStorage cache for saved-assets (which pins to a
 *   specific user) so it gets re-fetched against the new tenant.
 */
export function AuthSync() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const previousSub = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    if (auth.isAuthenticated && auth.user?.id_token) {
      setAuthToken(auth.user.id_token);
    } else {
      setAuthToken(null);
    }
  }, [auth.isAuthenticated, auth.user?.id_token]);

  useEffect(() => {
    const sub = auth.user?.profile.sub ?? null;
    // Detect transitions: signed-out → signed-in, or different user
    if (previousSub.current !== undefined && previousSub.current !== sub) {
      queryClient.clear();
      try {
        window.localStorage.removeItem("qsight.saved-assets");
      } catch {
        // ignore
      }
    }
    previousSub.current = sub;
  }, [auth.user?.profile.sub, queryClient]);

  return null;
}
