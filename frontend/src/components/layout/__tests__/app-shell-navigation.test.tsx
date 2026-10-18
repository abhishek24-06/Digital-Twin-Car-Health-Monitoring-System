import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

function headerNav() {
  return screen.getByRole("navigation", { name: "Main sections" });
}

function sidebarNav() {
  return screen.getByRole("navigation", { name: "Primary" });
}

describe("AppShell header section navigation", () => {
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

  it("shows the four section tabs in the top header", async () => {
    renderShell();
    await screen.findByText("page content");

    const links = within(headerNav()).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Fleet",
      "Simulation Control",
      "Workflow Monitor",
      "Knowledge Search",
    ]);
  });

  it("highlights the tab matching the current route", async () => {
    pathnameRef.current = "/simulations";
    renderShell();
    await screen.findByText("page content");

    expect(
      within(headerNav()).getByRole("link", { name: "Simulation Control" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("does not duplicate the promoted sections in the sidebar", async () => {
    renderShell();
    await screen.findByText("page content");

    // The four header destinations are listed exactly once (in the header).
    for (const label of [
      "Fleet",
      "Simulation Control",
      "Workflow Monitor",
      "Knowledge Search",
    ]) {
      expect(screen.getAllByRole("link", { name: label })).toHaveLength(1);
    }
    // The old sidebar "Overview" entry is gone; Fleet replaces it.
    expect(screen.queryByRole("link", { name: "Overview" })).toBeNull();
  });

  it("keeps the account-scoped sidebar destinations", async () => {
    renderShell();
    await screen.findByText("page content");

    expect(within(sidebarNav()).getByRole("link", { name: "My Vehicles" })).toBeTruthy();
    expect(within(sidebarNav()).getByRole("link", { name: "Profile" })).toBeTruthy();
  });

  it("keeps the Admin corpus entry in the sidebar for administrators only", async () => {
    useSessionStore.getState().setSession({
      access_token: "test-token",
      expires_at: null,
      user: { ...TEST_USER, role: "admin" },
    });
    renderShell();
    await screen.findByText("page content");

    const items = within(sidebarNav()).getAllByRole("link");
    expect(items.some((link) => /RAG corpus/i.test(link.textContent ?? ""))).toBe(true);
  });

  it("keeps the Admin corpus entry hidden from non-admins", async () => {
    renderShell();
    await screen.findByText("page content");

    const items = within(sidebarNav()).getAllByRole("link");
    expect(items.some((link) => /RAG corpus/i.test(link.textContent ?? ""))).toBe(false);
  });

  it("promotes the section tabs into the mobile drawer so they stay reachable", async () => {
    const user = userEvent.setup();
    renderShell();
    await screen.findByText("page content");

    await user.click(screen.getByRole("button", { name: /open navigation/i }));

    const drawer = await screen.findByRole("dialog", { name: "Navigation" });
    expect(within(drawer).getByRole("link", { name: "Workflow Monitor" })).toBeTruthy();
  });

  it("keeps the Admin profile menu working", async () => {
    const user = userEvent.setup();
    renderShell();
    await screen.findByText("page content");

    await user.click(screen.getByRole("button", { name: /account menu/i }));

    expect(
      await screen.findByRole("menuitem", { name: /profile settings/i }),
    ).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /sign out/i })).toBeTruthy();
  });
});
