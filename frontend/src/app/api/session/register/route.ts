import { NextResponse } from "next/server";
import { backendFetch, writeSessionCookies } from "@/lib/session-server";
import type {
  LoginRequest,
  RegisterRequest,
  TokenResponse,
  UserResponse,
} from "@/types/api";

export const dynamic = "force-dynamic";

/**
 * `POST /api/session/register`
 *
 * The backend's register endpoint returns **201 with the created user, not a
 * token pair** (verified against the live API). So registration is followed
 * immediately by a server-side login, and the resulting session is stored in
 * the same httpOnly cookies as the normal sign-in path. The browser is
 * therefore already signed in when it lands on the dashboard.
 */
export async function POST(request: Request): Promise<NextResponse> {
  let payload: RegisterRequest;
  try {
    payload = (await request.json()) as RegisterRequest;
  } catch {
    return NextResponse.json(
      { detail: "Malformed request body." },
      { status: 400 },
    );
  }

  const body: Record<string, unknown> = {
    email: payload.email,
    password: payload.password,
  };
  if (payload.full_name) body.full_name = payload.full_name;

  const registration = await backendFetch<UserResponse>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!registration.ok || !registration.body) {
    const detail =
      (registration.body as { detail?: unknown } | null)?.detail ??
      "Registration failed. Please try again.";
    return NextResponse.json({ detail }, { status: registration.status });
  }

  const loginBody: LoginRequest = {
    email: payload.email,
    password: payload.password,
  };
  const login = await backendFetch<TokenResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(loginBody),
  });

  if (!login.ok || !login.body) {
    return NextResponse.json(
      {
        user: registration.body,
        detail:
          "Account created, but automatic sign-in failed. Please sign in with your new credentials.",
      },
      { status: 201 },
    );
  }

  await writeSessionCookies(login.body.access_token, login.body.refresh_token);

  return NextResponse.json(
    {
      authenticated: true,
      user: login.body.user,
      access_token: login.body.access_token,
      expires_at: new Date(
        Date.now() + login.body.expires_in * 1000,
      ).toISOString(),
    },
    { status: 201 },
  );
}