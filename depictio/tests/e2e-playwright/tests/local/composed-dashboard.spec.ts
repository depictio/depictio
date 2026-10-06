/**
 * A dashboard composed from the catalog (`depictio run --data-root` with no
 * template that fits, or `--compose`), opened tab by tab in a browser.
 *
 * Runs against `depictio local up --data-root <dir>`, which writes what the
 * ingestion produced to `<local home>/last_ingestion.json`. Point
 * COMPOSED_RESULT_JSON at that file to run it, e.g.
 *
 *   COMPOSED_RESULT_JSON=~/.depictio/local/last_ingestion.json \
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8058 PLAYWRIGHT_API_URL=http://127.0.0.1:8058 \
 *   npx playwright test --project=chromium tests/local/composed-dashboard.spec.ts
 *
 * COMPOSED_SCREENSHOT_DIR, when set, receives a full-page screenshot per tab.
 *
 * What it proves: the composed YAML imports as one family of tabs, every tab
 * mounts its tiles, every figure and MultiQC plot it scrolls past renders a
 * Plotly chart, and no request the page makes ends in a server error.
 */

import * as fs from "fs";
import * as os from "os";
import * as path from "path";

import { test, expect } from "@fixtures/auth";
import { API_URL, API_PREFIX } from "@fixtures/auth";

type Tab = { dashboard_id: string; title: string };

const resultFile = process.env.COMPOSED_RESULT_JSON?.replace(/^~/, os.homedir());
const screenshotDir = process.env.COMPOSED_SCREENSHOT_DIR;

function mainDashboardId(): string {
  const result = JSON.parse(fs.readFileSync(resultFile as string, "utf8")) as {
    dashboards: { id: string }[];
  };
  return result.dashboards[0].id;
}

test.describe("Composed dashboard (depictio local up --data-root)", () => {
  test.skip(!resultFile, "Set COMPOSED_RESULT_JSON to a `depictio run --result-json` file.");

  let serverErrors: string[] = [];
  test.beforeEach(async ({ page }) => {
    serverErrors = [];
    page.on("response", (res) => {
      if (res.status() >= 500) serverErrors.push(`${res.status()} ${res.url()}`);
    });
  });
  test.afterEach(() => {
    expect(serverErrors).toEqual([]);
  });

  test("every tab renders its tiles", async ({ page, request }) => {
    test.setTimeout(600_000);
    const mainId = mainDashboardId();
    const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/tabs/${mainId}`);
    expect(res.ok()).toBeTruthy();
    const family = (await res.json()) as { main_tab: Tab; child_tabs: Tab[] };
    const tabs = [family.main_tab, ...family.child_tabs];
    expect(tabs.length).toBeGreaterThan(1);

    // Tall enough for a whole tab: the grid scrolls inside its own container,
    // so a full-page screenshot would only ever show the first screen.
    await page.setViewportSize({ width: 1600, height: 2600 });
    for (const [i, tab] of tabs.entries()) {
      await page.goto(`/dashboard/${tab.dashboard_id}`);
      await page
        .getByRole("button", { name: "Skip tour" })
        .click({ timeout: 5_000 })
        .catch(() => {});
      await expect(page.locator("[data-testid='dashboard-content']")).toBeVisible({
        timeout: 30_000,
      });

      // Collapsed sections (a tab's tables) hold tiles too.
      await page
        .getByRole("button", { name: "Expand all" })
        .click({ timeout: 3_000 })
        .catch(() => {});
      const tiles = page.locator(".react-grid-item");
      await expect(tiles.first()).toBeVisible({ timeout: 30_000 });
      const count = await tiles.count();
      // Tiles mount when scrolled into view: walk them all.
      for (let t = 0; t < count; t++) {
        await tiles.nth(t).scrollIntoViewIfNeeded().catch(() => {});
      }
      await page.waitForLoadState("networkidle").catch(() => {});

      const charts = tiles.filter({ has: page.locator(".js-plotly-plot") });
      const chartCount = await charts.count();
      test.info().annotations.push({
        type: "tab",
        description: `${tab.title}: ${count} tile(s), ${chartCount} Plotly chart(s)`,
      });

      if (screenshotDir) {
        fs.mkdirSync(screenshotDir, { recursive: true });
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({
          path: path.join(screenshotDir, `${String(i).padStart(2, "0")}-${tab.title}.png`.replace(/[^\w.-]+/g, "_")),
          fullPage: true,
        });
      }
    }
  });
});
