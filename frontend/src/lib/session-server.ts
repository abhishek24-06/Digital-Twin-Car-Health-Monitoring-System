/**
 * Server-side session helpers.
 *
 * The backend speaks bearer tokens only: it hands back an access token **and** a
 * rotating refresh token, and it never sets cookies of its own. To keep the
 * refresh token out of JavaScript, this Next.js server is the only place it
 * lives:
 *
 * - `dt_at` — access token, httpOnly, path `/`, short TTL.
 * - `dt_rt` — refresh token, httpOnly, path `/api/session` (so it is only ever
 *   transmitted to the session routes), long TTL.
 *
 * The browser receives the access token in memory (never in localStorage) and
 * uses it as a bearer token for data requests. This module is server-only.
 */

import { cookies } from "next/headers";

export const ACCESS_COOKIE = "dt_at";
export const REFRESH_COOKIE = "dt_rt";

const ACCESS_PATH = "/";
/** Scoped so the refresh token is only sent to session endpoints. */
const REFRESH_PATH = "/api/session";

const ACCESS_TTL_SECONDS = 60 * 60 * 12;
const REFRESH_TTL_SECONDS = 60 * 60 * 24 * 30;

/** Server-side base URL. Falls back to the public one for local dev parity. */
export function backendBaseUrl(): string {
  const url =
    process.env.BACKEND_API_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    "http://localhost:8000/api/v1";
  return url.replace(/\/+$/, "");
}

export async function backendFetch<T>(
  path: string,
  init: RequestInit & { accessToken?: string | null } = {},
): Promise<{ status: number; ok: boolean; body: T | null }> {
  const { accessToken, headers, ...rest } = init;
  const response = await fetch(`${backendBaseUrl()}${path}`, {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(headers as Record<string, string> | undefined),
    },
    cache: "no-store",
  });

  let body: T | null = null;
  if (response.status !== 204) {
    const text = await response.text();
    if (text) {
      try {
        body = JSON.parse(text) as T;
      } catch {
        body = null;
      }
    }
  }
  return { status: response.status, ok: response.ok, body };
}

/**
 * Read the `exp` claim from a JWT so the client knows when to renew.
 *
 * The signature is deliberately NOT verified: this value is only used to decide
 * when to ask the session proxy for a fresh token. Every real authorisation
 * decision is made by the backend from the bearer token itself.
 */
export function accessTokenExpiresAt(token: string, now = Date.now()): string {
  const fallback = now + 15 * 60 * 1000;
  const parts = token.split(".");
  if (parts.length !== 3) return new Date(fallback).toISOString();
  try {
    const payload = JSON.parse(
      Buffer.from(parts[1], "base64url").toString("utf8"),
    ) as { exp?: number };
    if (typeof payload.exp !== "number" || !Number.isFinite(payload.exp)) {
      return new Date(fallback).toISOString();
    }
    return new Date(payload.exp * 1000).toISOString();
  } catch {
    return new Date(fallback).toISOString();
  }
}

export async function readAccessToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(ACCESS_COOKIE)?.value ?? null;
}

export async function readRefreshToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(REFRESH_COOKIE)?.value ?? null;
}

export async function writeSessionCookies(accessToken: string, refreshToken: string): Promise<void> {
  const store = await cookies();
  store.set(ACCESS_COOKIE, accessToken, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: ACCESS_PATH,
    maxAge: ACCESS_TTL_SECONDS,
  });
  store.set(REFRESH_COOKIE, refreshToken, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: REFRESH_PATH,
    maxAge: REFRESH_TTL_SECONDS,
  });
}

export async function clearSessionCookies(): Promise<void> {
  const store = await cookies();
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
}