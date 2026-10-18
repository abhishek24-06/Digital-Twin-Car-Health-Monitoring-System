import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HeaderNav, SECTION_ITEMS, isNavActive } from "@/components/layout/nav-items";

const pathnameRef = vi.hoisted(() => ({ current: "/dashboard" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameRef.current,
}));

function nav() {
  return screen.getByRole("navigation", { name: "Main sections" });
}

function activeTabs() {
  return within(nav())
    .getAllByRole("link")
    .filter((link) => link.getAttribute("aria-current") === "page");
}

afterEach(() => {
  vi.restoreAllMocks();
  pathnameRef.current = "/dashboard";
});

describe("HeaderNav", () => {
  it("renders the four sections in order, each linked to its existing route", () => {
    render(<HeaderNav />);

    const links = within(nav()).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Fleet",
      "Simulation Control",
      "Workflow Monitor",
      "Knowledge Search",
    ]);
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/dashboard",
      "/simulations",
      "/workflow",
      "/rag",
    ]);
  });

  it.each([
    ["/dashboard", "Fleet"],
    ["/simulations", "Simulation Control"],
    ["/workflow", "Workflow Monitor"],
    ["/rag", "Knowledge Search"],
  ])("marks %s as the single active tab", (pathname, label) => {
    pathnameRef.current = pathname;
    render(<HeaderNav />);

    const active = activeTabs();
    expect(active).toHaveLength(1);
    expect(active[0].textContent).toBe(label);
  });

  it("derives the active tab from the route, so a direct load/refresh is correct", () => {
    // Rendering with the path already set is exactly a hard refresh: there is no
    // separate active-tab state that could drift from the URL.
    pathnameRef.current = "/workflow";
    render(<HeaderNav />);

    expect(activeTabs()[0].textContent).toBe("Workflow Monitor");
    expect(
      within(nav()).getByRole("link", { name: "Fleet" }).getAttribute("aria-current"),
    ).toBeNull();
  });

  it("keeps no tab active on a route that is not one of the sections", () => {
    pathnameRef.current = "/vehicles/22222222-2222-4222-8222-222222222222/health";
    render(<HeaderNav />);

    expect(activeTabs()).toHaveLength(0);
  });

  it("does not mistake the admin corpus page for Knowledge Search", () => {
    pathnameRef.current = "/admin/rag";
    render(<HeaderNav />);

    expect(activeTabs()).toHaveLength(0);
  });

  it("exposes the full label to assistive tech even when the text is icon-only", () => {
    render(<HeaderNav />);

    // `aria-label` is the accessible name regardless of the responsive label.
    expect(
      within(nav()).getByRole("link", { name: "Simulation Control" }),
    ).toBeTruthy();
  });

  it("fires onNavigate when a tab is activated (used to close the mobile drawer)", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(<HeaderNav orientation="vertical" onNavigate={onNavigate} />);

    await user.click(within(nav()).getByRole("link", { name: "Knowledge Search" }));

    expect(onNavigate).toHaveBeenCalledTimes(1);
  });

  it("lists every section in the vertical (drawer) layout", () => {
    render(<HeaderNav orientation="vertical" />);

    expect(within(nav()).getAllByRole("link")).toHaveLength(SECTION_ITEMS.length);
  });
});

describe("isNavActive", () => {
  it("returns false without a pathname", () => {
    expect(isNavActive(null, "/dashboard")).toBe(false);
  });

  it("keeps a parent section active for its nested routes", () => {
    expect(isNavActive("/vehicles/abc/health", "/vehicles")).toBe(true);
  });

  it("keeps the fleet overview active only on its exact route", () => {
    expect(isNavActive("/dashboard", "/dashboard")).toBe(true);
    expect(isNavActive("/dashboard/anything", "/dashboard")).toBe(false);
  });
});
