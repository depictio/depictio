import { defineConfig, devices } from "@playwright/test";

// Default target: depictio-viewer-dev on :5601 (the real Depictio UI).
// Set PLAYWRIGHT_BASE_URL=http://localhost:5701 to run against the minimal
// react-frontend scaffold instead.
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5601";
const API_URL = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8101";
const IS_CI = !!process.env.CI;
// Slow down every browser operation by N ms so headed runs are watchable:
//   PLAYWRIGHT_SLOWMO=500 npx playwright test --headed --workers=1
const SLOW_MO = Number(process.env.PLAYWRIGHT_SLOWMO ?? 0);

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: IS_CI,
  retries: IS_CI ? 2 : 0,
  // Limit local workers to 2 to avoid bursting the login rate-limiter.
  workers: IS_CI ? 2 : 2,
  timeout: 60_000,
  expect: { timeout: 10_000 },

  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],

  use: {
    baseURL: BASE_URL,
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
    viewport: { width: 1920, height: 1080 },
    launchOptions: { slowMo: SLOW_MO },
    // Always record traces locally so every run is inspectable in the trace
    // viewer / UI mode timeline (CI keeps the cheaper retain-on-failure).
    trace: IS_CI ? "retain-on-failure" : "on",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    extraHTTPHeaders: {
      Accept: "application/json",
    },
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    // Uncomment to add cross-browser coverage:
    // { name: "firefox",  use: { ...devices["Desktop Firefox"] } },
    // { name: "webkit",   use: { ...devices["Desktop Safari"] } },
  ],

  // The Cypress suite assumes the docker-compose stack is already up.
  // Mirror that contract — no webServer is started here.
});

export const ENV = { BASE_URL, API_URL };
