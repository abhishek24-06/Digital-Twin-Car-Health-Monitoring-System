import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { apiRequest, buildQuery, renewSession } from "@/lib/api-client";
import { isAccessTokenExpired, useSessionStore } from "@/lib/session-store";
import type { UserResponse } from "@/types/api";

const USER: UserResponse = {
  id: "user-1",
  email: "driver@example.com",
  full_name: "Driver",
  role: "user",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function authedSession() {
  useSessionStore.getState().setSession({
    access_token: "token-1",
    expires_at: new Date(Date.now() + 300_000).toISOString(),
    user: USER,
  });
}

describe("buildQuery", () => {
  it("drops empty values so the backend never receives blank filters", () => {
    expect(
      buildQuery({ page: 1, page_size: 20, q: "", make: undefined, model: null }),
    ).toBe("?page=1&page_size=20");
  });

  it("returns an empty string when nothing survives", () => {
    expect(buildQuery()).toBe("");
    expect(buildQuery({ q: "" })).toBe("");
  });
});

describe("isAccessTokenExpired", () => {
  it("treats an unknown expiry as valid so the first request still works", () => {
    useSessionStore.getState().setSession({
      access_token: "token-1",
      expires_at: null,
      user: USER,
    });
    expect(isAccessTokenExpired(useSessionStore.getState())).toBe(false);
  });

  it("detects a past expiry", () => {
    useSessionStore
      .getState()
      .setAccessToken("token-1", new Date(Date.now() - 1_000).getTime());
    expect(isAccessTokenExpired(useSessionStore.getState())).toBe(true);
  });
});

describe("apiRequest", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    authedSession();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    useSessionStore.getState().setAnonymous();
  });

  it("attaches the bearer token and never sends credentials to the API", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0 }));

    await apiRequest("/vehicles");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/vehicles");
    expect(init.headers.Authorization).toBe("Bearer token-1");
    // The refresh cookie must stay on the Next.js origin only.
    expect(init.credentials).toBe("omit");
  });

  it("renews proactively when the access token has already expired", async () => {
    useSessionStore
      .getState()
      .setAccessToken("stale", new Date(Date.now() - 5_000).getTime());

    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          access_token: "token-2",
          expires_at: new Date(Date.now() + 300_000).toISOString(),
          user: USER,
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));

    await apiRequest("/vehicles");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/session");
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe("Bearer token-2");
  });

  it("replays the request once after a 401 and succeeds", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "Not authenticated" }, 401))
      .mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          access_token: "token-2",
          expires_at: new Date(Date.now() + 300_000).toISOString(),
          user: USER,
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ id: "v1" }));

    const result = await apiRequest<{ id: string }>("/vehicles/v1");

    expect(result).toEqual({ id: "v1" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("shares one renewal between concurrent 401s", async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/session") {
        return jsonResponse({
          authenticated: true,
          access_token: "token-2",
          expires_at: new Date(Date.now() + 300_000).toISOString(),
          user: USER,
        });
      }
      const authorized = (init?.headers as Record<string, string> | undefined)?.Authorization;
      if (authorized === "Bearer token-1") {
        return jsonResponse({ detail: "Not authenticated" }, 401);
      }
      return jsonResponse({ id: "v1" });
    });

    await Promise.all([
      apiRequest("/vehicles"),
      apiRequest("/telemetry"),
      apiRequest("/health"),
    ]);

    const renewals = fetchMock.mock.calls.filter(([url]) => String(url) === "/api/session");
    expect(renewals).toHaveLength(1);
  });

  it("clears the session when renewal reports it is gone", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "Not authenticated" }, 401))
      .mockResolvedValueOnce(jsonResponse({ authenticated: false }, 401));

    await expect(apiRequest("/vehicles")).rejects.toBeInstanceOf(ApiError);
    expect(useSessionStore.getState().accessToken).toBeNull();
    expect(useSessionStore.getState().status).toBe("anonymous");
  });

  it("does not sign the user out on a transient proxy outage", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "Not authenticated" }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: "backend down" }, 503));

    await expect(apiRequest("/vehicles")).rejects.toMatchObject({ status: 503 });
    // Still signed in: a backend blip must not destroy the session.
    expect(useSessionStore.getState().accessToken).toBe("token-1");
  });

  it("surfaces a 404 as an ApiError without renewing", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Not found" }, 404));

    await expect(apiRequest("/vehicles/v1/health/latest")).rejects.toMatchObject({
      status: 404,
      isNotFound: true,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("sends JSON bodies but lets the browser set multipart boundaries", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "ingested" }));

    const form = new FormData();
    form.append("file", new Blob(["hello"]), "manual.txt");
    await apiRequest("/admin/rag/documents", { method: "POST", formData: form });

    const init = fetchMock.mock.calls[0][1];
    expect(init.headers["Content-Type"]).toBeUndefined();
    expect(init.body).toBe(form);
  });

  it("skips the Authorization header for unauthenticated calls", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ access_token: "t" }));
    await apiRequest("/auth/login", { method: "POST", body: {}, auth: false });
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });
});

describe("renewSession", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("returns false when the proxy says the session is gone", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ authenticated: false }, 401));
    await expect(renewSession()).resolves.toBe(false);
  });

  it("propagates a 503 so the caller can retry instead of signing out", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "upstream unavailable" }, 503));
    await expect(renewSession()).rejects.toBeInstanceOf(ApiError);
  });
});
