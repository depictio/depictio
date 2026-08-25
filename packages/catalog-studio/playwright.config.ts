import { defineConfig, devices } from '@playwright/test';

// The app is served under Vite base '/depictio-catalog-studio/'. Driven via `vite preview`
// against a fresh build so e2e matches what Pages ships.
const PORT = 4188;
const BASE = `http://127.0.0.1:${PORT}/depictio-catalog-studio/`;

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: 'line',
  use: {
    baseURL: BASE,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Allow pointing at a preinstalled Chromium (e.g. sandboxes that ship
        // one at a pinned path) via PW_CHROMIUM_PATH; CI installs browsers the
        // normal way (`playwright install --with-deps chromium`) and leaves it unset.
        ...(process.env.PW_CHROMIUM_PATH
          ? { launchOptions: { executablePath: process.env.PW_CHROMIUM_PATH } }
          : {}),
      },
    },
  ],
  webServer: {
    // Drive the PRODUCTION bundle, not the dev server: base-path handling,
    // tree-shaking and the pyodide/monaco dynamic chunks only exist after a
    // real build, so a build-only breakage used to pass e2e and still ship.
    // PW_DEV_SERVER=1 swaps in the dev server for fast local iteration.
    // (Invoke vite directly — `pnpm run dev -- …` makes vite ignore the flags
    // and bind the default port.)
    command: process.env.PW_DEV_SERVER
      ? `pnpm exec vite --port ${PORT} --strictPort --host 127.0.0.1`
      : `pnpm run build && pnpm exec vite preview --port ${PORT} --strictPort --host 127.0.0.1`,
    // Build with OAuth "configured" so the one-click PR path exists to test.
    // The values are inert: the e2e routes both github.com and the worker, and
    // the client id is public by design.
    env: {
      VITE_GH_CLIENT_ID: 'e2e-client-id',
      VITE_GH_OAUTH_WORKER_URL: 'https://oauth-worker.test/exchange',
    },
    url: BASE,
    reuseExistingServer: !process.env.CI,
    // The build is part of the command, so allow for it.
    timeout: 300_000,
  },
});
