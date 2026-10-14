import { expect, type Page } from "@playwright/test";

/** Seeded by `backend/scripts/run_e2e_backend.py`. */
export const DEMO_PASSWORD = "E2ePassword123";
export const OWNER_EMAIL = "owner@e2e-digitaltwin.com";
export const INTRUDER_EMAIL = "intruder@e2e-digitaltwin.com";
export const OWNER_VEHICLE_MODEL = "Volvo XC60";

/** Sign in through the real UI (the httpOnly refresh cookie is set by Next). */
export async function login(
  page: Page,
  email: string,
  password = DEMO_PASSWORD,
): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** Log in as the owner and return the UUID of their seeded vehicle. */
export async function openOwnerVehicle(page: Page): Promise<string> {
  await login(page, OWNER_EMAIL);
  await expect(page).toHaveURL(/\/dashboard/);

  await page.goto("/vehicles");
  const openLink = page.getByRole("link", { name: /Open/ }).first();
  await expect(openLink).toBeVisible();
  await openLink.click();

  await expect(page).toHaveURL(/\/vehicles\/[0-9a-f-]{36}/);
  const match = page.url().match(/\/vehicles\/([0-9a-f-]{36})/);
  if (!match) throw new Error(`Could not read vehicle id from ${page.url()}`);
  return match[1];
}
