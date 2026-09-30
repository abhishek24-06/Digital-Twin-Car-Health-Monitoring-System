import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useAuthGuard } from "@/hooks/use-auth-guard";
import { useSessionStore } from "@/lib/session-store";
import { TEST_USER } from "@/test/utils";
import type { UserResponse } from "@/types/api";

const ADMIN: UserResponse = { ...TEST_USER, role: "admin" };

const replace = vi.fn();
const pathname = { value: "/vehicles" };
const search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => pathname.value,
  useSearchParams: () => search,
}));

function session(user: UserResponse | null) {
  if (user) {
    useSessionStore.getState().setSession({
      access_token: "token-1",
      expires_at: new Date(Date.now() + 300_000).toISOString(),
      user,
    });
  } else {
    useSessionStore.getState().setAnonymous();
  }
}

describe("useAuthGuard", () => {
  beforeEach(() => {
    replace.mockReset();
    pathname.value = "/vehicles";
    useSessionStore.getState().setAnonymous();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    useSessionStore.getState().setAnonymous();
  });

  it("sends an anonymous visitor to login with the intended destination", async () => {
    session(null);
    const { result } = renderHook(() => useAuthGuard());

    await waitFor(() => expect(result.current.status).toBe("anonymous"));
    expect(replace).toHaveBeenCalledWith(
      "/login?next=%2Fvehicles",
    );
  });

  it("does not redirect a signed-in user", async () => {
    session(TEST_USER);
    const { result } = renderHook(() => useAuthGuard());

    await waitFor(() => expect(result.current.status).toBe("authenticated"));
    expect(result.current.isAdmin).toBe(false);
    expect(replace).not.toHaveBeenCalled();
  });

  it("bounces a non-admin away from an admin route", async () => {
    pathname.value = "/admin/rag";
    session(TEST_USER);
    const { result } = renderHook(() => useAuthGuard({ requireAdmin: true }));

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/dashboard?denied=admin"),
    );
    expect(result.current.isAdmin).toBe(false);
  });

  it("admits an admin to an admin route", async () => {
    pathname.value = "/admin/rag";
    session(ADMIN);
    const { result } = renderHook(() => useAuthGuard({ requireAdmin: true }));

    await waitFor(() => expect(result.current.status).toBe("authenticated"));
    expect(result.current.isAdmin).toBe(true);
    expect(replace).not.toHaveBeenCalled();
  });

  it("preserves query parameters in the redirect target", async () => {
    pathname.value = "/vehicles/abc/telemetry";
    search.set("range", "24h");
    session(null);

    renderHook(() => useAuthGuard());

    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(replace.mock.calls[0][0]).toBe(
      `/login?next=${encodeURIComponent("/vehicles/abc/telemetry?range=24h")}`,
    );
    search.delete("range");
  });
});
