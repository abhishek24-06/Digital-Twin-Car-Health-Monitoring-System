import {
  ApiError,
  apiErrorFromResponse,
  toApiError,
} from "@/lib/api-error";
import { useSessionStore, isAccessTokenExpired } from "@/lib/session-store";
import type { UserResponse } from "@/types/api";

/**
 * The single place where HTTP happens.
 *
 * Everything the browser requests goes to `NEXT_PUBLIC_API_URL` with a bearer
 * token; the only exception is the session lifecycle, which is proxied through
 * the Next.js server (`/api/session/*`) so the refresh token can stay in an
 * httpOnly cookie.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ??
  "http://localhost:8000/api/v1";

/** Routes that manage the session; handled server-side, never bearer-authed. */
const SESSION_ROUTES = ["/api/session", "/api/session/login", "/api/session/register", "/api/session/logout"];

export type QueryValue = string | number | boolean | null | undefined;

/** Build a query string, dropping empty values so the backend sees clean params. */
export function buildQuery(params?: Record<string, QueryValue>): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** When false the Authorization header is omitted (login, register). */
  auth?: boolean;
  signal?: AbortSignal;
  query?: Record<string, QueryValue>;
  /** Send a multipart FormData body instead of JSON. */
  formData?: FormData;
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }
  const text = await response.text();
  return text || null;
}

/* ------------------------------------------------------------------ */
/* Silent session renewal (single flight)                              */
/* ------------------------------------------------------------------ */

let renewalInFlight: Promise<boolean> | null = null;

/**
 * Ask the session proxy for a valid access token. The proxy refreshes using the
 * httpOnly refresh cookie when needed. Concurrent 401s share one request.
 *
 * Returns `false` only when the session is genuinely gone (401/403). A backend
 * outage propagates as an error so a network blip never signs the user out.
 */
export async function renewSession(): Promise<boolean> {
  if (!renewalInFlight) {
    renewalInFlight = (async () => {
      let response: Response;
      try {
        response = await fetch("/api/session", {
          method: "GET",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
      } catch {
        throw new ApiError(
          0,
          "Cannot reach the Digital Twin API. Check that the backend is running.",
        );
      }

      if (response.status === 401 || response.status === 403) return false;
      if (!response.ok) {
        throw new ApiError(
          response.status,
          "The session service is temporarily unavailable.",
        );
      }

      const payload = (await response.json()) as {
        authenticated: boolean;
        access_token?: string;
        expires_at?: string;
        user?: UserResponse;
      };
      if (!payload.authenticated || !payload.access_token || !payload.user) {
        return false;
      }
      useSessionStore.getState().setSession({
        access_token: payload.access_token,
        expires_at: payload.expires_at ?? null,
        user: payload.user,
      });
      return true;
    })().finally(() => {
      renewalInFlight = null;
    });
  }
  return renewalInFlight;
}

/* ------------------------------------------------------------------ */
/* Core request                                                        */
/* ------------------------------------------------------------------ */

async function perform<T>(path: string, options: RequestOptions): Promise<T> {
  const {
    method = "GET",
    body,
    auth = true,
    signal,
    query,
    formData,
  } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined && !formData) headers["Content-Type"] = "application/json";

  if (auth && !SESSION_ROUTES.includes(path)) {
    const token = useSessionStore.getState().accessToken;
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  if (formData || isFormData) {
    // Let the browser set the multipart boundary.
    delete headers["Content-Type"];
  }

  const response = await fetch(`${API_BASE_URL}${path}${buildQuery(query)}`, {
    method,
    headers,
    ...(formData ? { body: formData } : body !== undefined ? { body: JSON.stringify(body) } : {}),
    ...(auth ? { credentials: "omit" } : {}),
    ...(signal ? { signal } : {}),
  });

  const parsed = await parseBody(response);

  if (!response.ok) {
    throw apiErrorFromResponse(response.status, parsed);
  }

  return parsed as T;
}

/**
 * Public entry point.
 *
 * On a 401 the session is renewed once and the request replayed once; a second
 * 401 drops the session so the app can route the user to `/login`.
 */
export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const useAuth = options.auth ?? true;
  const isSessionRoute = SESSION_ROUTES.includes(path);

  // Proactive renewal: when the token's expiry is known and has passed, rotate
  // before spending a round trip on a request that would 401.
  if (useAuth && !isSessionRoute && isAccessTokenExpired(useSessionStore.getState())) {
    try {
      await renewSession();
    } catch {
      // Renewal failed for a non-auth reason; the request below will surface it.
    }
  }

  try {
    return await perform<T>(path, options);
  } catch (error) {
    const apiError = toApiError(error);

    if (apiError.status === 401 && useAuth && !isSessionRoute) {
      const renewed = await renewSession();
      if (renewed) {
        return perform<T>(path, options);
      }
      useSessionStore.getState().setAnonymous();
    }

    throw apiError;
  }
}

/** Convenience wrappers so services read as plain endpoint calls. */
export const api = {
  get: <T>(path: string, options: Omit<RequestOptions, "method" | "body"> = {}) =>
    apiRequest<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options: Omit<RequestOptions, "method" | "body"> = {}) =>
    apiRequest<T>(path, { ...options, method: "POST", body }),
  postForm: <T>(path: string, formData: FormData, options: Omit<RequestOptions, "method" | "body" | "formData"> = {}) =>
    apiRequest<T>(path, { ...options, method: "POST", formData }),
  patch: <T>(path: string, body?: unknown, options: Omit<RequestOptions, "method" | "body"> = {}) =>
    apiRequest<T>(path, { ...options, method: "PATCH", body }),
  delete: <T>(path: string, options: Omit<RequestOptions, "method" | "body"> = {}) =>
    apiRequest<T>(path, { ...options, method: "DELETE" }),
};

export { ApiError };