"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { authApi } from "@/services/auth";
import { useSessionStore } from "@/lib/session-store";
import type { UserResponse } from "@/types/api";

/**
 * Bootstraps the session exactly once per page load by asking the Next.js
 * session proxy (`/api/session`), which restores or silently rotates the
 * session using the httpOnly refresh cookie.
 */
export function useSessionBootstrap(): void {
  const status = useSessionStore((state) => state.status);
  const setSession = useSessionStore((state) => state.setSession);
  const setAnonymous = useSessionStore((state) => state.setAnonymous);

  React.useEffect(() => {
    if (status !== "loading") return;
    let cancelled = false;

    authApi
      .session()
      .then((payload) => {
        if (cancelled) return;
        if (payload.authenticated && payload.access_token && payload.user) {
          setSession({
            access_token: payload.access_token,
            expires_at: payload.expires_at ?? "",
            user: payload.user,
          });
        } else {
          setAnonymous();
        }
      })
      .catch(() => {
        if (!cancelled) setAnonymous();
      });

    return () => {
      cancelled = true;
    };
  }, [status, setSession, setAnonymous]);
}

export interface AuthGuardResult {
  status: "loading" | "authenticated" | "anonymous";
  user: UserResponse | null;
  isAdmin: boolean;
}

/**
 * Client-side route protection.
 *
 * This is presentation only: every backend endpoint re-checks the bearer token
 * and the vehicle ownership/role rules, so hiding a route here never removes a
 * security boundary.
 */
export function useAuthGuard(options: { requireAdmin?: boolean } = {}): AuthGuardResult {
  const { requireAdmin = false } = options;
  const status = useSessionStore((state) => state.status);
  const user = useSessionStore((state) => state.user);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useSessionBootstrap();

  const isAuthenticated = status === "authenticated";
  const isAdmin = user?.role === "admin";

  React.useEffect(() => {
    if (status === "loading") return;
    if (!isAuthenticated) {
      const next = `${pathname}${searchParams.toString() ? `?${searchParams}` : ""}`;
      router.replace(`/login?next=${encodeURIComponent(next)}`);
      return;
    }
    if (requireAdmin && !isAdmin) {
      router.replace("/dashboard?denied=admin");
    }
  }, [status, isAuthenticated, requireAdmin, isAdmin, router, pathname, searchParams]);

  return { status, user, isAdmin };
}