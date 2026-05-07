"use client";

import { WebStorageStateStore, type User } from "oidc-client-ts";

/**
 * OIDC config for our Cognito user pool. Values are read from
 * NEXT_PUBLIC_COGNITO_* env vars at build time.
 */
const AUTHORITY =
  process.env.NEXT_PUBLIC_COGNITO_AUTHORITY?.trim() ||
  "https://cognito-idp.eu-north-1.amazonaws.com/eu-north-1_ghOcVAcf7";

const CLIENT_ID =
  process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID?.trim() ||
  "2b21fuelj56p9k3c1kdkbtc1k0";

const REDIRECT_URI =
  process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI?.trim() ||
  (typeof window !== "undefined"
    ? `${window.location.origin}/auth/callback`
    : "http://localhost:3000/auth/callback");

const POST_LOGOUT_REDIRECT_URI =
  process.env.NEXT_PUBLIC_COGNITO_LOGOUT_URI?.trim() ||
  (typeof window !== "undefined" ? `${window.location.origin}/` : "http://localhost:3000/");

export const COGNITO_DOMAIN =
  process.env.NEXT_PUBLIC_COGNITO_DOMAIN?.trim() ||
  "https://eu-north-1ghocvacf7.auth.eu-north-1.amazoncognito.com";

export const oidcConfig = {
  authority: AUTHORITY,
  client_id: CLIENT_ID,
  redirect_uri: REDIRECT_URI,
  post_logout_redirect_uri: POST_LOGOUT_REDIRECT_URI,
  response_type: "code",
  scope: "openid email",
  automaticSilentRenew: true,
  // Persist the OIDC user across page refreshes
  userStore:
    typeof window !== "undefined"
      ? new WebStorageStateStore({ store: window.localStorage })
      : undefined,
  // Strip the ?code=... query param after a successful callback
  onSigninCallback: (_user: User | void) => {
    if (typeof window !== "undefined") {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  },
};

/**
 * Build the Cognito Hosted UI logout URL. react-oidc-context's
 * `removeUser()` only clears local storage; to fully sign out of Cognito
 * and the IdP, we must redirect to this URL.
 */
export function cognitoLogoutUrl(): string {
  const u = new URL(`${COGNITO_DOMAIN.replace(/\/$/, "")}/logout`);
  u.searchParams.set("client_id", CLIENT_ID);
  u.searchParams.set("logout_uri", POST_LOGOUT_REDIRECT_URI);
  return u.toString();
}
