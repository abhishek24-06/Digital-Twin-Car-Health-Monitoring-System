"use client";

import { create } from "zustand";
import type { UserResponse } from "@/types/api";

/**
 * Session state.
 *
 * Token handling follows the safest practical architecture for this backend
 * (which only speaks bearer tokens + refresh rotation, no cookies of its own):
 *
 * - The **refresh token never enters JavaScript**. It lives in an httpOnly
 *   cookie managed by the Next.js session proxy (`/api/session/*`).
 * - The **access token is kept in memory only** (this store, never persisted),
 *   so it disappears on tab close and cannot be read from localStorage.
 * - A 401 on any request triggers exactly one silent session renewal, then the
 *   request is replayed once.
 */

export type SessionStatus = "loading" | "authenticated" | "anonymous";

export interface SessionPayload {
  access_token: string;
  /** ISO timestamp of access-token expiry; null means "unknown, renew on 401". */
  expires_at?: string | null;
  user: UserResponse;
}

function parseExpiry(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

interface SessionState {
  status: SessionStatus;
  user: UserResponse | null;
  accessToken: string | null;
  expiresAt: number | null;
  /** Set when a silent renewal failed while an authenticated session existed. */
  expiredNotice: boolean;
  setSession: (payload: SessionPayload) => void;
  /** Replaces the cached user after a profile update, keeping the token. */
  setUser: (user: UserResponse) => void;
  setAccessToken: (token: string, expiresAt: number | null) => void;
  setAnonymous: () => void;
  setLoading: () => void;
  clearExpiredNotice: () => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  status: "loading",
  user: null,
  accessToken: null,
  expiresAt: null,
  expiredNotice: false,
  setSession: ({ access_token, expires_at, user }) =>
    set({
      status: "authenticated",
      user,
      accessToken: access_token,
      expiresAt: parseExpiry(expires_at),
      expiredNotice: false,
    }),
  setUser: (user) => set({ user }),
  setAccessToken: (token, expiresAt) =>
    set({ accessToken: token, expiresAt }),
  setAnonymous: () =>
    set({
      status: "anonymous",
      user: null,
      accessToken: null,
      expiresAt: null,
    }),
  setLoading: () => set({ status: "loading" }),
  clearExpiredNotice: () => set({ expiredNotice: false }),
}));

/** True when the access token is known to be expired (or nearly so). */
export function isAccessTokenExpired(state: SessionState, skewMs = 15_000): boolean {
  if (!state.accessToken) return true;
  if (state.expiresAt === null) return false;
  return state.expiresAt - skewMs <= Date.now();
}

export const selectUser = (state: SessionState) => state.user;
export const selectIsAdmin = (state: SessionState) => state.user?.role === "admin";
export const selectIsAuthenticated = (state: SessionState) =>
  state.status === "authenticated";