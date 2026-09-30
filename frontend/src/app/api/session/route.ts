import { NextResponse } from "next/server";
import {
  accessTokenExpiresAt,
  backendFetch,
  clearSessionCookies,
  readAccessToken,
  readRefreshToken,
  writeSessionCookies,
} from "@/lib/session-server";
import type { TokenResponse, UserResponse } from "@/types/api";

/**
 * `GET /api/session` — the browser's session probe.
 *
 * Returns `{ authenticated: false }` when there is no usable session. When the
 * access token has expired but the refresh cookie is still valid, the refresh
 * token is rotated here and a fresh pair is returned, so the app can restore
 * itself transparently after a reload.
 */
export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  try {
    return await probe();
  } catch {
    // The backend is unreachable. Report it as such (not as "signed out") so the
    // client keeps the current session and shows a retryable network error.
    return NextResponse.json(
      { authenticated: false, detail: "Backend unavailable" },
      { status: 503 },
    );
  }
}

async function probe(): Promise<NextResponse> {
  const accessToken = await readAccessToken();
  const refreshToken = await readRefreshToken();

  if (!accessToken && !refreshToken) {
    return NextResponse.json({ authenticated: false }, { status: 401 });
  }

  if (accessToken) {
    const me = await backendFetch<UserResponse>("/auth/me", { accessToken });
    if (me.ok && me.body) {
      return NextResponse.json({
        authenticated: true,
        access_token: accessToken,
        expires_at: accessTokenExpiresAt(accessToken),
        user: me.body,
      });
    }
    if (me.status === 403) {
      // Account disabled/deleted: nothing to refresh into.
      await clearSessionCookies();
      return NextResponse.json({ authenticated: false }, { status: 401 });
    }
  }

  if (refreshToken) {
    const refreshed = await backendFetch<TokenResponse>("/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (refreshed.ok && refreshed.body?.access_token) {
      await writeSessionCookies(
        refreshed.body.access_token,
        refreshed.body.refresh_token,
      );
      return NextResponse.json({
        authenticated: true,
        access_token: refreshed.body.access_token,
        expires_at: new Date(
          Date.now() + refreshed.body.expires_in * 1000,
        ).toISOString(),
        user: refreshed.body.user,
      });
    }
  }

  await clearSessionCookies();
  return NextResponse.json({ authenticated: false }, { status: 401 });
}