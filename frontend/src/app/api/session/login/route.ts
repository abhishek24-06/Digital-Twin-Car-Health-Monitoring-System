import { NextResponse } from "next/server";
import {
  backendFetch,
  clearSessionCookies,
  readRefreshToken,
  writeSessionCookies,
} from "@/lib/session-server";
import type { LoginRequest, TokenResponse, UserResponse } from "@/types/api";

export const dynamic = "force-dynamic";

/**
 * `POST /api/session/login`
 *
 * Exchanges credentials with the backend, stores both tokens in httpOnly
 * cookies and returns only the short-lived access token to the browser (kept in
 * memory) plus the user. The refresh token never crosses back to the client.
 */
export async function POST(request: Request): Promise<NextResponse> {
  let payload: LoginRequest;
  try {
    payload = (await request.json()) as LoginRequest;
  } catch {
    return NextResponse.json(
      { detail: "Malformed request body." },
      { status: 400 },
    );
  }

  const login = await backendFetch<TokenResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: payload.email, password: payload.password }),
  });

  if (!login.ok || !login.body) {
    const detail =
      (login.body as { detail?: string } | null)?.detail ??
      (login.status === 401
        ? "Invalid email or password."
        : "Sign-in failed. Please try again.");
    return NextResponse.json({ detail }, { status: login.status });
  }

  await writeSessionCookies(login.body.access_token, login.body.refresh_token);

  return NextResponse.json({
    authenticated: true,
    access_token: login.body.access_token,
    expires_at: new Date(Date.now() + login.body.expires_in * 1000).toISOString(),
    expires_in: login.body.expires_in,
    user: login.body.user,
  });
}

/** Revoke the refresh token server-side, then drop both cookies. */
export async function DELETE(): Promise<NextResponse> {
  const refreshToken = await readRefreshToken();
  if (refreshToken) {
    await backendFetch<null>("/auth/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  }
  await clearSessionCookies();
  return NextResponse.json({ authenticated: false });
}

export type { UserResponse };