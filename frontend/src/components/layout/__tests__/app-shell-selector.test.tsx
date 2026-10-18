import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/app-shell";
import { useSessionStore } from "@/lib/session-store";
import { vehiclesApi } from "@/services/vehicles";
import { ThemeProvider } from "@/stores/theme-provider";
import { createTestQueryClient, TEST_USER, TEST_VEHICLE } from "@/test/utils";

const pathnameRef = vi.hoisted(() => ({ current: "/dashboard" }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => pathnameRef.current,
  useParams: () => ({}),
}));

vi.mock("@/services/vehicles", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/vehicles")>();
  return {
    ...actual,
    vehiclesApi: { ...actual.vehiclesApi, list: vi.fn() },
  };
});

function renderShell() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <ThemeProvider>
        <AppShell>
          <div>page content</div>
        </AppShell>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

describe("AppShell vehicle selector visibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(vehiclesApi.list).mockResolvedValue({
      items: [TEST_VEHICLE],
      page: 1,
      page_size: 100,
      total: 1,
    });
    useSessionStore.getState().setSession({
      access_token: "test-token",
      expires_at: null,
      user: TEST_USER,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    useSessionStore.setState({ status: "loading" });
  });

  it("hides the single-vehicle selector on the fleet-level dashboard", async () => {
    pathnameRef.current = "/dashboard";
    renderShell();

    await screen.findByText("page content");
    // The selector would surface the vehicle's name; it must not on the overview.
    expect(screen.queryByText("Honda Civic")).toBeNull();
  });

  it("keeps the single-vehicle selector on vehicle-scoped pages", async () => {
    pathnameRef.current = "/vehicles";
    renderShell();

    expect(await screen.findAllByText("Honda Civic")).not.toHaveLength(0);
  });
});
