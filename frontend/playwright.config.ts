import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

/**
 * Phase D acceptance config.
 *
 * Playwright boots two isolated servers:
 *
 * 1. the **real backend** (`backend/scripts/run_e2e_backend.py`) against a
 *    disposable local database, with deterministic mock LLM providers;
 * 2. the **real frontend** (`next dev`) pointed at that backend.
 *
 * Nothing here talks to the hosted database or the developer's running servers
 * unless `E2E_REUSE_SERVERS=1` is set deliberately.
 */

const BACKEND_PORT = process.env.E2E_BACKEND_PORT ?? "8010";
const FRONTEND_PORT = process.env.E2E_FRONTEND_PORT ?? "3010";

const backendOrigin = `http://127.0.0.1:${BACKEND_PORT}`;
const backendUrl = `${backendOrigin}/api/v1`;
const frontendOrigin = `http://127.0.0.1:${FRONTEND_PORT}`;

const e2eDatabaseUrl =
  process.env.E2E_DATABASE_URL ??
  "postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_browser_test";

const backendPython =
  process.platform === "win32"
    ? path.resolve(__dirname, "..", "backend", ".venv", "Scripts", "python.exe")
    : path.resolve(__dirname, "..", "backend", ".venv", "bin", "python");

const reuseExistingServer = process.env.E2E_REUSE_SERVERS === "1";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: frontendOrigin,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${backendPython}" -u scripts/run_e2e_backend.py`,
      cwd: path.resolve(__dirname, "..", "backend"),
      url: `${backendUrl}/health`,
      timeout: 120_000,
      reuseExistingServer,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        ...process.env,
        E2E_DATABASE_URL: e2eDatabaseUrl,
        E2E_BACKEND_PORT: BACKEND_PORT,
      },
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT} --hostname 127.0.0.1`,
      cwd: __dirname,
      url: `${frontendOrigin}/login`,
      timeout: 240_000,
      reuseExistingServer,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        ...process.env,
        NEXT_PUBLIC_API_URL: backendUrl,
        BACKEND_API_URL: backendUrl,
      },
    },
  ],
});
