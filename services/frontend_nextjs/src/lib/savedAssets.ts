"use client";

import { useCallback, useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { savedAssetsApi } from "@/lib/api";

const CACHE_KEY = "qsight.saved-assets";
const QUERY_KEY = ["saved-assets"] as const;

function readCache(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function writeCache(list: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(list));
  } catch {
    // ignore quota errors
  }
}

export function useSavedAssets() {
  const queryClient = useQueryClient();

  // Defer any client-only state (localStorage, fetched list) until after
  // mount so server-rendered HTML — which has no access to localStorage or
  // the authenticated API — matches the first client render. Without this
  // the cached list on the client differs from the empty list on the server
  // and Next.js throws a hydration mismatch.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  const { data } = useQuery<string[]>({
    queryKey: QUERY_KEY,
    queryFn: async () => {
      const res = await savedAssetsApi.list();
      const list = res.tickers ?? [];
      writeCache(list);
      return list;
    },
    enabled: mounted,
    // Seed from localStorage so the list doesn't flash empty before the fetch
    // resolves. placeholderData (unlike initialData) doesn't mark the data as
    // fresh, so the queryFn still runs and gets the authoritative list.
    placeholderData: mounted ? readCache() : [],
    staleTime: 60_000,
  });

  const saved = mounted ? (data ?? []) : [];

  const addMutation = useMutation({
    mutationFn: (symbol: string) => savedAssetsApi.add(symbol.toUpperCase()),
    onMutate: async (symbol) => {
      await queryClient.cancelQueries({ queryKey: QUERY_KEY });
      const prev = queryClient.getQueryData<string[]>(QUERY_KEY) ?? [];
      const s = symbol.toUpperCase();
      const next = prev.includes(s) ? prev : [...prev, s];
      queryClient.setQueryData<string[]>(QUERY_KEY, next);
      writeCache(next);
      return { prev };
    },
    onError: (_err, _sym, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData<string[]>(QUERY_KEY, ctx.prev);
        writeCache(ctx.prev);
      }
    },
    onSuccess: (res) => {
      queryClient.setQueryData<string[]>(QUERY_KEY, res.tickers ?? []);
      writeCache(res.tickers ?? []);
    },
  });

  const removeMutation = useMutation({
    mutationFn: (symbol: string) => savedAssetsApi.remove(symbol.toUpperCase()),
    onMutate: async (symbol) => {
      await queryClient.cancelQueries({ queryKey: QUERY_KEY });
      const prev = queryClient.getQueryData<string[]>(QUERY_KEY) ?? [];
      const s = symbol.toUpperCase();
      const next = prev.filter((x) => x !== s);
      queryClient.setQueryData<string[]>(QUERY_KEY, next);
      writeCache(next);
      return { prev };
    },
    onError: (_err, _sym, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData<string[]>(QUERY_KEY, ctx.prev);
        writeCache(ctx.prev);
      }
    },
    onSuccess: (res) => {
      queryClient.setQueryData<string[]>(QUERY_KEY, res.tickers ?? []);
      writeCache(res.tickers ?? []);
    },
  });

  const isSaved = useCallback(
    (symbol: string) => saved.includes(symbol.toUpperCase()),
    [saved],
  );

  const save = useCallback((symbol: string) => addMutation.mutate(symbol), [addMutation]);
  const unsave = useCallback((symbol: string) => removeMutation.mutate(symbol), [removeMutation]);
  const toggle = useCallback(
    (symbol: string) => {
      const s = symbol.toUpperCase();
      if (saved.includes(s)) removeMutation.mutate(s);
      else addMutation.mutate(s);
    },
    [saved, addMutation, removeMutation],
  );

  return { saved, isSaved, save, unsave, toggle };
}
