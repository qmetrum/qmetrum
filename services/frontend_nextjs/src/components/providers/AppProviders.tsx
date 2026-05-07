"use client";

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "react-oidc-context";
import { BrandingProvider } from "@/components/providers/BrandingProvider";
import { AuthSync } from "@/components/auth/AuthSync";
import { AuthGate } from "@/components/auth/AuthGate";
import { oidcConfig } from "@/lib/auth";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
}

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(makeQueryClient);

  return (
    <AuthProvider {...oidcConfig}>
      <QueryClientProvider client={queryClient}>
        <AuthSync />
        <BrandingProvider>
          <AuthGate>{children}</AuthGate>
        </BrandingProvider>
      </QueryClientProvider>
    </AuthProvider>
  );
}
