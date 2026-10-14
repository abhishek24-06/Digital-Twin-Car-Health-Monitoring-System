import { expect, test, type Page } from "@playwright/test";

import { OWNER_EMAIL, login } from "./support";

/**
 * Real-browser acceptance for the Workflow Monitor filter toolbar.
 *
 * Drives the real app against the isolated backend started by
 * `playwright.config.ts` (disposable DB, deterministic seed). It verifies the
 * dropdowns are anchored beneath their own trigger, layered above the dashboard
 * content, limited to one open menu, and dismissible — at desktop and narrow
 * viewport widths.
 */

const trigger = (page: Page, label: string) =>
  page.getByRole("button", { name: `Filter by ${label}` });

async function openWorkflowMonitor(page: Page): Promise<void> {
  await login(page, OWNER_EMAIL);
  await expect(page).toHaveURL(/\/dashboard/);
  await page.goto("/workflow");
  await expect(
    page.getByRole("heading", { name: "System Workflow" }),
  ).toBeVisible();
}

test.describe("Workflow Monitor filter toolbar (desktop)", () => {
  test.beforeEach(async ({ page }) => {
    await openWorkflowMonitor(page);
  });

  test("anchors each menu beneath its own trigger", async ({ page }) => {
    const workflow = trigger(page, "Workflow");
    await workflow.click();

    const menu = page.getByTestId("filter-menu");
    await expect(menu).toBeVisible();

    const triggerBox = await workflow.boundingBox();
    const menuBox = await menu.boundingBox();
    expect(triggerBox).not.toBeNull();
    expect(menuBox).not.toBeNull();

    // Directly below the trigger and left-aligned with it.
    expect(menuBox!.y).toBeGreaterThanOrEqual(triggerBox!.y + triggerBox!.height);
    expect(Math.abs(menuBox!.x - triggerBox!.x)).toBeLessThanOrEqual(2);
  });

  test("renders the open menu above the dashboard content", async ({ page }) => {
    await trigger(page, "Workflow").click();
    const menu = page.getByTestId("filter-menu");
    await expect(menu).toBeVisible();

    // The topmost paint at a point inside the menu must belong to the menu,
    // i.e. no dashboard card is stacked above it.
    const isTopmost = await menu.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + 8);
      return hit !== null && element.contains(hit);
    });
    expect(isTopmost).toBe(true);
  });

  test("allows only one open menu at a time", async ({ page }) => {
    await trigger(page, "Workflow").click();
    await expect(page.getByRole("button", { name: "All workflows" })).toBeVisible();

    await trigger(page, "Status").click();
    await expect(page.getByRole("button", { name: "All workflows" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "All statuses" })).toBeVisible();
    await expect(page.getByTestId("filter-menu")).toHaveCount(1);
  });

  test("dismisses on Escape and on an outside click", async ({ page }) => {
    await trigger(page, "Workflow").click();
    await expect(page.getByTestId("filter-menu")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("filter-menu")).toHaveCount(0);

    await trigger(page, "Vehicle").click();
    await expect(page.getByTestId("filter-menu")).toBeVisible();
    await page.getByRole("heading", { name: "System Workflow" }).click();
    await expect(page.getByTestId("filter-menu")).toHaveCount(0);
  });
});

test.describe("Workflow Monitor filter toolbar (narrow viewport)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test.beforeEach(async ({ page }) => {
    await openWorkflowMonitor(page);
  });

  test("wraps cleanly without colliding with the page title or overflowing", async ({
    page,
  }) => {
    const bar = page.getByTestId("filter-bar");
    await expect(bar).toBeVisible();

    const titleBox = await page
      .getByRole("heading", { name: "System Workflow" })
      .boundingBox();
    const barBox = await bar.boundingBox();
    expect(titleBox).not.toBeNull();
    expect(barBox).not.toBeNull();

    // The toolbar sits below the title and inside the viewport.
    expect(titleBox!.y + titleBox!.height).toBeLessThanOrEqual(barBox!.y + 1);
    expect(barBox!.x).toBeGreaterThanOrEqual(0);
    expect(barBox!.x + barBox!.width).toBeLessThanOrEqual(390 + 1);

    // An open menu also stays within the viewport on the narrow layout.
    await trigger(page, "Workflow").click();
    const menuBox = await page.getByTestId("filter-menu").boundingBox();
    expect(menuBox).not.toBeNull();
    expect(menuBox!.x).toBeGreaterThanOrEqual(0);
    expect(menuBox!.x + menuBox!.width).toBeLessThanOrEqual(390 + 1);
  });
});
