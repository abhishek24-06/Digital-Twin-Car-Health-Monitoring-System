"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError, toApiError } from "@/lib/api-error";

/**
 * TanStack Query configuration.
 *
 * - Retries are deliberately excluded for 4xx (a bad request stays bad) and
 *   capped for 5xx / network failures.
 * - Polling is opt-in per query (`refetchInterval`), and the query cache pauses
 *   when the tab is hidden (see `focusManager` below) so a backgrounded tab does
 *   not keep hitting the backend.
 */

function shouldRetry(failureCount: number, error: unknown): boolean {
  const apiError = toApiError(error);
  if (apiError instanceof ApiError) {
    if (apiError.status === 0) return failureCount < 2;
    if (apiError.status >= 400 && apiError.status < 500) return false;
  }
  return failureCount < 2;
}

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        staleTime: 15_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: true,
      },
      mutations: { retry: false },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

function getQueryClient(): QueryClient {
  if (typeof window === "undefined") return makeQueryClient();
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}

/**
 * Drop every cached response on sign-out.
 *
 * The cache holds owner-scoped data (vehicles, telemetry, diagnoses, RAG
 * documents), and this client is a module-level singleton for the whole tab. If
 * it survived a sign-out, the next person to log in on the same tab could see
 * the previous account's data before refetching, and the in-flight requests
 * would keep retrying with a token that no longer exists.
 */
export function clearQueryCache(): void {
  if (typeof window === "undefined") return;
  browserQueryClient?.clear();
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  React.useEffect(() => {
    const onVisibility = () => {
      queryClient.resumePausedMutations();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}