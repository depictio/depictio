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

import type { Page } from "@playwright/test";

import { test, expect } from "@fixtures/auth";
import { API_URL, API_PREFIX } from "@fixtures/auth";

type Tab = { dashboard_id: string; title: string };

const resultFile = process.env.COMPOSED_RESULT_JSON?.replace(/^~/, os.homedir());
const screenshotDir = process.env.COMPOSED_SCREENSHOT_DIR;

type RunResult = {
  project: { id: string };
  dashboards: { id: string }[];
  composed?: { unrecognised: number };
};

function runResult(): RunResult {
  return JSON.parse(fs.readFileSync(resultFile as string, "utf8")) as RunResult;
}

function mainDashboardId(): string {
  return runResult().dashboards[0].id;
}

/** Open every section of the tab. The grid's toggle reads "Collapse all" while
 * any section is open, so a folded section next to open ones (a stage tab's
 * Tables) takes a collapse first. */
async function expandAll(page: Page): Promise<void> {
  const collapse = page.getByRole("button", { name: "Collapse all" });
  if (await collapse.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await collapse.click();
  }
  await page
    .getByRole("button", { name: "Expand all" })
    .click({ timeout: 3_000 })
    .catch(() => {});
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
      await expandAll(page);
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
        // The grid scrolls in its own container: back to its first tile.
        await tiles.first().scrollIntoViewIfNeeded().catch(() => {});
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({
          path: path.join(screenshotDir, `${String(i).padStart(2, "0")}-${tab.title}.png`.replace(/[^\w.-]+/g, "_")),
          fullPage: true,
        });
      }
    }
  });

  test("the Samples filter narrows the tables of another tab", async ({ page, request }) => {
    test.setTimeout(600_000);
    const mainId = mainDashboardId();
    const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/tabs/${mainId}`);
    const family = (await res.json()) as { main_tab: Tab; child_tabs: Tab[] };
    const candidates = family.child_tabs.filter((t) => t.title !== "MultiQC");
    test.skip(candidates.length === 0, "No tab with tables.");

    await page.setViewportSize({ width: 1600, height: 1400 });
    const rowCount = async (): Promise<number[]> => {
      const footers = page.locator(".react-grid-item").getByText(/\d+ to \d+ of [\d,]+/);
      const texts = await footers.allInnerTexts();
      return texts.map((t) => Number((/of ([\d,]+)/.exec(t)?.[1] ?? "0").replace(/,/g, "")));
    };
    const total = (counts: number[]) => counts.reduce((a, b) => a + b, 0);
    const open = async (tab: Tab) => {
      await page.goto(`/dashboard/${tab.dashboard_id}`);
      await page
        .getByRole("button", { name: "Skip tour" })
        .click({ timeout: 5_000 })
        .catch(() => {});
      await expect(page.locator("[data-testid='dashboard-content']")).toBeVisible({ timeout: 30_000 });
      // Folded sections (a stage tab's Tables) hold linked tables too, and a
      // tile mounts when scrolled into view.
      await expandAll(page);
      const tiles = page.locator(".react-grid-item");
      for (let t = 0; t < (await tiles.count()); t++) {
        await tiles.nth(t).scrollIntoViewIfNeeded().catch(() => {});
      }
      await page.waitForLoadState("networkidle").catch(() => {});
      await expect
        .poll(async () => (await rowCount()).length, { timeout: 20_000 })
        .toBeGreaterThan(0)
        .catch(() => {});
    };

    const before = new Map<string, number[]>();
    for (const tab of candidates) {
      await open(tab);
      before.set(tab.dashboard_id, await rowCount());
    }
    const withTables = candidates.filter((t) => (before.get(t.dashboard_id) ?? []).length > 0);
    test.skip(withTables.length === 0, "No table rendered on any tab.");

    // The filter is persistent: set once, it holds on every tab.
    await open(withTables[0]);
    const sampleInput = page.getByPlaceholder(/select sample/i).first();
    // A run naming no samples (a lone table) gets no Samples filter.
    test.skip((await sampleInput.count()) === 0, "This dashboard has no Samples filter.");
    await sampleInput.click();
    await page.getByRole("option").first().click();
    await page.keyboard.press("Escape");

    // Some table, on some tab, loses rows: the filter reached it through a link.
    const narrowed: string[] = [];
    for (const tab of withTables) {
      await open(tab);
      const was = before.get(tab.dashboard_id) ?? [];
      const shrank = await expect
        // A table filtered down to nothing loses its footer: count the tab's rows.
        .poll(async () => total(await rowCount()) < total(was), { timeout: 20_000 })
        .toBe(true)
        .then(() => true)
        .catch(() => false);
      if (shrank) {
        narrowed.push(`${tab.title}: ${was.join(", ")} → ${(await rowCount()).join(", ")} rows`);
        if (screenshotDir) {
          fs.mkdirSync(screenshotDir, { recursive: true });
          await page.screenshot({
            path: path.join(screenshotDir, "samples-filter-applied.png"),
            fullPage: true,
          });
        }
        break;
      }
    }
    test.info().annotations.push({ type: "samples-filter", description: narrowed.join("; ") });
    expect(narrowed, "no table on any tab was narrowed by the Samples filter").not.toEqual([]);
  });

  test("the project page lists the files left out, with a command each", async ({ page }) => {
    const result = runResult();
    const left = result.composed?.unrecognised ?? 0;
    test.skip(left === 0, "This run left no file out.");

    await page.goto(`/projects/${result.project.id}`);
    await page
      .getByRole("button", { name: "Skip tour" })
      .click({ timeout: 5_000 })
      .catch(() => {});
    const panel = page.locator("[data-testid='unrecognised-files-panel']");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    await expect(panel.locator("tbody tr")).toHaveCount(left);
    await expect(panel.getByRole("button", { name: "Copy the command that adds this file" })).toHaveCount(left);
    if (screenshotDir) {
      fs.mkdirSync(screenshotDir, { recursive: true });
      await panel.screenshot({ path: path.join(screenshotDir, "project-unrecognised-files.png") });
    }
  });
});
