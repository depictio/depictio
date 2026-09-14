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
  // Two, to avoid bursting the login rate-limiter. Raising it means measuring
  // first: the backend runs a single uvicorn worker and shares the runner with
  // mongo, redis, minio and celery, so more browsers is not more throughput.
  workers: Number(process.env.PLAYWRIGHT_WORKERS ?? 2),
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
      // admin/backup-restore does a real destructive restore (wipe + reinsert
      // every collection, including deltatables) against the shared stack.
      // It runs in its own project below, gated to start only once every
      // other spec here has finished — otherwise its restore can silently
      // drop a data collection another spec is still relying on mid-run.
      testIgnore: [
        /admin\/backup-restore\.spec\.ts$/,
        /catalog\/catalog-modules-on-dashboard\.spec\.ts$/,
      ],
    },
    {
      // The catalog walk: one test, an hour long, adding every render the
      // catalog offers through the real picker. It gets its own project for two
      // reasons that the shared settings get wrong.
      //
      // retries: a deterministic walk cannot pass on a second attempt, so the
      // suite-wide 2 retries only ever tripled an already long failure — three
      // attempts, two of them guaranteed to fail the same way. One is affordable
      // now that a lane is a fraction of the old whole-catalog walk, and it
      // still buys tolerance for a genuinely flaky render.
      //
      // video: a 55-minute 1080p screencast, encoded next to a full docker
      // stack on a 4-vCPU runner, that nobody opens. Every failure is already a
      // labelled line in the walk's own report.
      name: "chromium-catalog-walk",
      use: { ...devices["Desktop Chrome"], video: "off" },
      testMatch: /catalog\/catalog-modules-on-dashboard\.spec\.ts$/,
      retries: 1,
    },
    {
      name: "chromium-destructive",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /admin\/backup-restore\.spec\.ts$/,
      // Both of the above, not just the first: the restore wipes every
      // collection, so it must not start while the walk is still adding to one.
      dependencies: ["chromium", "chromium-catalog-walk"],
    },
    // Uncomment to add cross-browser coverage:
    // { name: "firefox",  use: { ...devices["Desktop Firefox"] } },
    // { name: "webkit",   use: { ...devices["Desktop Safari"] } },
  ],

  // The Cypress suite assumes the docker-compose stack is already up.
  // Mirror that contract — no webServer is started here.
});

export const ENV = { BASE_URL, API_URL };
