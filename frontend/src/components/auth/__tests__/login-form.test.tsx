import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginForm } from "@/components/auth/login-form";
import { authApi } from "@/services/auth";
import { useSessionStore } from "@/lib/session-store";
import { TEST_USER } from "@/test/utils";

const replace = vi.fn();
const refresh = vi.fn();
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push, refresh }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/hooks/use-auth-guard", () => ({
  useAuthGuard: () => ({ status: "anonymous" }),
  useSessionBootstrap: () => {},
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("LoginForm", () => {
  beforeEach(() => {
    replace.mockReset();
    refresh.mockReset();
    useSessionStore.getState().setAnonymous();
  });

  afterEach(() => vi.restoreAllMocks());

  it("stores the token in memory and routes to the dashboard", async () => {
    const user = userEvent.setup();
    const login = vi
      .spyOn(authApi, "login")
      .mockResolvedValue({
        access_token: "token-1",
        expires_at: new Date(Date.now() + 300_000).toISOString(),
        user: TEST_USER,
      } as Awaited<ReturnType<typeof authApi.login>>);

    const { container } = await import("@testing-library/react").then(({ render }) =>
      render(<LoginForm />),
    );

    await user.type(screen.getByLabelText(/email/i), "driver@example.com");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    // The token lives in the store only; no document.cookie write.
    expect(useSessionStore.getState().accessToken).toBe("token-1");
    expect(useSessionStore.getState().user?.email).toBe(TEST_USER.email);
    expect(document.cookie).not.toContain("token-1");
    expect(login).toHaveBeenCalledWith({
      email: "driver@example.com",
      password: "correct-horse",
    });
    container.remove();
  });

  it("shows FastAPI 422 field errors against the offending inputs", async () => {
    const user = userEvent.setup();
    vi.spyOn(authApi, "login").mockRejectedValue(
      Object.assign(new Error("Password too short"), {
        name: "ApiError",
        status: 422,
        fieldErrors: { password: ["String should have at least 8 characters"] },
      }),
    );

    const { render } = await import("@testing-library/react");
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/email/i), "driver@example.com");
    await user.type(screen.getByLabelText(/password/i), "short");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/password too short/i);
    });
    expect(replace).not.toHaveBeenCalled();
    expect(useSessionStore.getState().status).toBe("anonymous");
  });

  it("surfaces a 401 as a credentials problem without signing in", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: "Incorrect email or password" }, 401),
      ),
    );

    const { render } = await import("@testing-library/react");
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/email/i), "driver@example.com");
    await user.type(screen.getByLabelText(/password/i), "wrong-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/incorrect email or password/i)).toBeTruthy();
    });
    expect(useSessionStore.getState().status).toBe("anonymous");
    vi.unstubAllGlobals();
  });
});
