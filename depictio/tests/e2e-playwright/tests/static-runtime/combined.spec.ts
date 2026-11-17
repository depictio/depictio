/**
 * The combined file: the rendered report AND the interactive dashboard in one
 * HTML, behind a "Report | Dashboard" switch — from `file://`, no network.
 *
 * One runtime script and one manifest in the page. The report view mounts the
 * tiles in place (as the report host does); the dashboard view is the whole
 * App, in a same-origin iframe built on demand from that same script text.
 * Both views share one filter state. Reference numbers are the Polars ones of
 * filter-parity-cards.spec.ts:
 *   all rows: mean(body_mass_g) = 4201.7544
 *   Adelie:   mean(body_mass_g) = 3700.6623
 */
import { expect, test, type Frame, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  PENGUINS_MANIFEST,
  blockNetwork,
  combinedUrl,
  skipUnlessCombinedRuntimeBuilt,
} from "./helpers";

const manifest = JSON.parse(readFileSync(PENGUINS_MANIFEST, "utf-8"));
const TAB = manifest.dashboard.id as string;
const speciesDc = manifest.dashboard.doc.stored_metadata.find(
  (c: { index: string }) => c.index === "filter-species",
).dc_id;
const ADELIE = [
  {
    index: "filter-species",
    value: ["Adelie"],
    column_name: "species",
    interactive_component_type: "MultiSelect",
    metadata: { dc_id: speciesDc, column_name: "species", interactive_component_type: "MultiSelect" },
  },
];

const reportCard = (page: Page) => page.locator(`[data-depictio-tile~="${TAB}:card-body-mass"]`);

async function dashboardFrame(page: Page): Promise<Frame> {
  await expect(page.locator("iframe.dpx-dashboard-frame")).toBeAttached({ timeout: 30_000 });
  const frame = page.frames().find((f) => f !== page.mainFrame());
  if (!frame) throw new Error("no dashboard frame");
  await frame.waitForSelector(".react-grid-item", { timeout: 60_000 });
  return frame;
}

const dashboardCard = (frame: Frame) => frame.locator('[data-component-index="card-body-mass"]');

test.describe("combined file — report + dashboard", () => {
  test.beforeEach(() => skipUnlessCombinedRuntimeBuilt());

  test("one switch, two views, one filter state", async ({ page }) => {
    const attempts = await blockNetwork(page);
    await page.goto(combinedUrl(ADELIE));

    // The report view: tiles mounted in place, on the exported state.
    const sw = page.locator(".dpx-switch");
    await expect(sw).toBeVisible({ timeout: 30_000 });
    await expect(sw.locator("button[data-view=report]")).toHaveAttribute("aria-selected", "true");
    await expect(reportCard(page).getByText("3,700.6623")).toBeVisible({ timeout: 30_000 });
    // One runtime in the page: the dashboard is not a second copy.
    expect(await page.locator("script[data-depictio-runtime='js']").count()).toBe(1);
    expect(await page.locator("iframe").count()).toBe(0);

    // The dashboard view: the App, on the report's filters.
    await sw.locator("button[data-view=dashboard]").click();
    await expect(page).toHaveURL(new RegExp(`#dashboard/${TAB}$`));
    const frame = await dashboardFrame(page);
    await expect(dashboardCard(frame).getByText("3,700.6623")).toBeVisible({ timeout: 30_000 });
    // Its Plotly styles are its own document's.
    expect(
      await frame.evaluate(() => document.querySelectorAll(".js-plotly-plot .main-svg").length),
    ).toBeGreaterThan(0);

    // Drop the species pick in the dashboard: the report follows.
    await frame.locator(".mantine-MultiSelect-root .mantine-Pill-remove").first().click();
    await expect(dashboardCard(frame).getByText("4,201.7544")).toBeVisible({ timeout: 30_000 });
    await sw.locator("button[data-view=report]").click();
    await expect(reportCard(page).getByText("4,201.7544")).toBeVisible({ timeout: 30_000 });

    // "Back to the exported state" in the report: the dashboard follows.
    await page.locator("[data-testid='depictio-report-reset']").click();
    await expect(reportCard(page).getByText("3,700.6623")).toBeVisible({ timeout: 30_000 });
    await sw.locator("button[data-view=dashboard]").click();
    await expect(dashboardCard(frame).getByText("3,700.6623")).toBeVisible({ timeout: 30_000 });

    expect(attempts).toEqual([]);
  });

  test("cross-links between the views", async ({ page }) => {
    const attempts = await blockNetwork(page);
    await page.goto(combinedUrl());
    const tile = page.locator(`[data-depictio-tile~="${TAB}:scatter-mass-flipper"]`);
    await tile.locator(".dpx-tile-links button").click();
    const frame = await dashboardFrame(page);
    const target = frame.locator('[data-component-index="scatter-mass-flipper"]');
    await expect(target).toBeInViewport({ timeout: 30_000 });

    // "Show in report" on the tile under the pointer.
    await target.hover();
    const chip = frame.locator(".dpx-show-in-report");
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(page.locator(".dpx-switch button[data-view=report]")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(tile).toBeInViewport();
    await expect(page).toHaveURL(/#report\/tile-scatter-mass-flipper$/);
    expect(attempts).toEqual([]);
  });

  test("deep links, the export's default view, and print", async ({ page }) => {
    const attempts = await blockNetwork(page);
    // Opens on the dashboard when the export says so.
    await page.goto(combinedUrl([], "dashboard"));
    await dashboardFrame(page);
    await expect(page.locator(".dpx-switch button[data-view=dashboard]")).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // Printing from the dashboard view prints the report.
    await page.emulateMedia({ media: "print" });
    await expect(page.locator(".dpx-dashboard-frame")).toBeHidden();
    await expect(page.locator(".dpx-switch")).toBeHidden();
    await expect(page.locator("h1").first()).toBeVisible();
    await page.emulateMedia({ media: "screen" });

    // `#report` wins over the export's default.
    await page.goto(combinedUrl([], "dashboard") + "#report");
    await expect(page.locator(".dpx-switch button[data-view=report]")).toHaveAttribute(
      "aria-selected",
      "true",
      { timeout: 30_000 },
    );
    expect(await page.locator("iframe").count()).toBe(0);
    expect(attempts).toEqual([]);
  });
});
