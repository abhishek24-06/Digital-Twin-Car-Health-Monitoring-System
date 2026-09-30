import { api } from "@/lib/api-client";
import { apiErrorFromResponse, toApiError } from "@/lib/api-error";
import type {
  LoginRequest,
  RegisterRequest,
  SessionResponse,
  UserResponse,
} from "@/types/api";

/**
 * Session endpoints go through the Next.js proxy so the refresh token stays in an
 * httpOnly cookie and never reaches JavaScript. Everything else uses `api`
 * directly with the in-memory bearer token.
 */

async function proxyRequest<T>(
  path: string,
  init: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
      },
    });
  } catch {
    // A throw here means Next.js itself is unreachable.
    throw toApiError(new TypeError("network"));
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    // FastAPI's error envelope is preserved, so login/register forms can show
    // per-field validation messages instead of a generic failure.
    throw apiErrorFromResponse(response.status, payload);
  }
  return payload as T;
}

export const authApi = {
  /** Restore an existing session (also performs silent refresh when needed). */
  session: () =>
    proxyRequest<SessionResponse>("/api/session", { method: "GET" }),

  login: (credentials: LoginRequest) =>
    proxyRequest<SessionResponse>("/api/session/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    }),

  /** Returns the created user and an already-established session. */
  register: (details: RegisterRequest) =>
    proxyRequest<SessionResponse>("/api/session/register", {
      method: "POST",
      body: JSON.stringify(details),
    }),

  /**
   * Revoke the refresh token server-side and clear cookies. Never throws — a
   * failed sign-out must still clear the client session.
   */
  logout: async () => {
    try {
      await fetch("/api/session/login", {
        method: "DELETE",
        credentials: "same-origin",
      });
    } catch {
      /* cookies are cleared client-side regardless */
    }
  },

  /** Current user straight from the backend (bearer-authed, no proxy hop). */
  me: () => api.get<UserResponse>("/auth/me"),

  /**
   * Profile update goes to the real endpoint with the bearer token; no proxy hop
   * is needed because it does not touch the refresh token.
   */
  updateProfile: (fullName: string | null) =>
    api.patch<UserResponse>("/users/me", { full_name: fullName }),
};
