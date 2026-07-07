import { defineConfig, devices } from '@playwright/test';

// The app is served under Vite base '/depictio/'. Drive it via `vite preview`
// against a fresh build so e2e matches what Pages ships.
const PORT = 4188;
const BASE = `http://127.0.0.1:${PORT}/depictio/`;

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
    // Invoke vite directly (NOT `pnpm run dev -- …`, whose `--` makes vite
    // ignore the flags and bind the default port). Serves at the Vite base with
    // no pre-build; committed public/kinds.json + catalog.schema.json are used.
    command: `pnpm exec vite --port ${PORT} --strictPort --host 127.0.0.1`,
    url: BASE,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
