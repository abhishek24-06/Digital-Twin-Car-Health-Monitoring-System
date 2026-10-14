import { expect, test, type Page } from "@playwright/test";

import {
  INTRUDER_EMAIL,
  OWNER_EMAIL,
  openOwnerVehicle,
  login,
} from "./support";

/**
 * Phase D real-browser acceptance for the vehicle workspace.
 *
 * Every test drives the **real** Next.js app against the **real** isolated
 * backend started by `playwright.config.ts` (disposable DB, deterministic mock
 * LLM). Nothing here uses component mocks, so a pass means the wired product
 * works end to end in a browser.
 */

const TABS: ReadonlyArray<{ label: string; href: string; heading: string }> = [
  { label: "Overview", href: "", heading: "Latest values" },
  { label: "Live Health", href: "/health", heading: "Live current-session health" },
  { label: "Simulation", href: "/simulation", heading: "Live simulation status" },
  { label: "Analytics", href: "/analytics", heading: "Historical analytics" },
  { label: "Telemetry", href: "/telemetry", heading: "Telemetry" },
  { label: "AI Diagnosis", href: "/diagnosis", heading: "Ask about this vehicle" },
  { label: "History", href: "/history", heading: "Health snapshots" },
  { label: "Alerts", href: "/alerts", heading: "Alerts" },
];

function sectionsNav(page: Page) {
  return page.getByRole("navigation", { name: "Vehicle sections" });
}

/** Open every tab and assert it renders its own landmark in the live app. */
async function sweepTabs(page: Page, vehicleId: string): Promise<void> {
  const nav = sectionsNav(page);
  for (const tab of TABS) {
    const link = nav.getByRole("link", { name: tab.label, exact: true });
    await link.click();
    await expect(page).toHaveURL(
      new RegExp(`/vehicles/${vehicleId}${tab.href}$`),
    );
    await expect(link).toHaveAttribute("aria-current", "page");
    await expect(
      page.getByRole("heading", { name: tab.heading, exact: true }).first(),
    ).toBeVisible();
  }
}

test("unauthenticated visitors are redirected to sign in", async ({ page }) => {
  await page.goto("/vehicles");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("a wrong password is rejected in place", async ({ page }) => {
  await login(page, OWNER_EMAIL, "definitely-not-the-password");
  await expect(page).toHaveURL(/\/login/);
  await expect(
    page.getByText(/invalid|incorrect|credentials|unauthori[sz]ed/i).first(),
  ).toBeVisible();
  await expect(page).not.toHaveURL(/\/dashboard/);
});

test("all eight vehicle tabs render against the live backend", async ({ page }) => {
  const vehicleId = await openOwnerVehicle(page);
  await sweepTabs(page, vehicleId);
});

test("the deterministic agent produces a diagnosis in the browser", async ({ page }) => {
  const vehicleId = await openOwnerVehicle(page);
  await page.goto(`/vehicles/${vehicleId}/diagnosis`);

  await page
    .getByLabel("Question about this vehicle")
    .fill("Is anything wrong with my car right now?");
  await page.getByRole("button", { name: "Ask the agent" }).click();

  // The agent graph runs server-side with the mock provider and returns a
  // grounded diagnosis card.
  await expect(
    page.getByRole("heading", { name: "Summary", exact: true }),
  ).toBeVisible({ timeout: 60_000 });
});

test("another account cannot open someone else's vehicle", async ({ browser }) => {
  const ownerContext = await browser.newContext();
  const ownerPage = await ownerContext.newPage();
  const vehicleId = await openOwnerVehicle(ownerPage);
  await ownerContext.close();

  const intruderContext = await browser.newContext();
  const intruderPage = await intruderContext.newPage();
  const statuses: number[] = [];
  intruderPage.on("response", (response) => {
    if (response.url().endsWith(`/vehicles/${vehicleId}`)) {
      statuses.push(response.status());
    }
  });

  await login(intruderPage, INTRUDER_EMAIL);
  await expect(intruderPage).toHaveURL(/\/dashboard/);

  await intruderPage.goto(`/vehicles/${vehicleId}`);
  await expect(
    intruderPage.getByText(/belongs to another account/i),
  ).toBeVisible();
  expect(statuses.some((status) => status === 403 || status === 404)).toBe(true);

  await intruderContext.close();
});

test("the vehicle workspace has no horizontal overflow on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const vehicleId = await openOwnerVehicle(page);

  for (const route of ["", "/health", "/telemetry", "/analytics", "/diagnosis"]) {
    await page.goto(`/vehicles/${vehicleId}${route}`);
    await expect(sectionsNav(page)).toBeVisible();
    const overflow = await page.evaluate(() => {
      const el = document.documentElement;
      return el.scrollWidth - el.clientWidth;
    });
    expect(overflow, `horizontal overflow at ${route || "/"} (+${overflow}px)`).toBeLessThanOrEqual(1);
  }
});

test("browsing every tab logs no uncaught errors or failed API calls", async ({ page }) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const failedRequests: string[] = [];
  const serverErrors: string[] = [];

  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const location = message.location();
    consoleErrors.push(`${message.text()} @ ${location.url}:${location.lineNumber}`);
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    const failure = request.failure()?.errorText ?? "";
    if (failure.includes("ERR_ABORTED")) return; // navigation cancels SSE
    if (request.url().includes("/stream")) return;
    failedRequests.push(`${failure} ${request.url()}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 500 && response.url().includes("/api/")) {
      serverErrors.push(`${response.status()} ${response.url()}`);
    }
  });

  const vehicleId = await openOwnerVehicle(page);
  await sweepTabs(page, vehicleId);

  // The anonymous session-probe route answers 401 by design (that is how the
  // app learns "not signed in"); favicon misses are Next dev noise. Everything
  // else must be clean.
  const realConsoleErrors = consoleErrors.filter(
    (entry) =>
      !/favicon|Download the React DevTools/i.test(entry) &&
      !/\/api\/session(?!\/)/.test(entry),
  );

  expect(failedRequests, "failed network requests").toEqual([]);
  expect(serverErrors, "5xx API responses").toEqual([]);
  expect(pageErrors, "uncaught page errors").toEqual([]);
  expect(realConsoleErrors, "console errors").toEqual([]);
});
