/**
 * The report host: the static runtime mounted into the tiles of a Quarto
 * report, from `file://`, with no network.
 *
 * One manifest (producer B's penguins demo, the same contract producer A
 * writes for a report), inlined once beside the report runtime, at the end of
 * a page laid out as Quarto renders the notebook generator's placeholders. The
 * report opens on an exported state (species = Adelie); the filter panel in
 * its "Filters" part recomputes every tile in the page. Reference numbers are
 * the Polars ones of filter-parity-cards.spec.ts:
 *   all rows: mean(body_mass_g) = 4201.7544, 342 points, 3 species
 *   Adelie:   mean(body_mass_g) = 3700.6623, 151 points, 1 species
 */
import { expect, test, type Page } from "@playwright/test";
import {
  PENGUINS_MANIFEST,
  blockNetwork,
  reportUrl,
  skipUnlessReportRuntimeBuilt,
} from "./helpers";
import { readFileSync } from "node:fs";

const manifest = JSON.parse(readFileSync(PENGUINS_MANIFEST, "utf-8"));
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

const TAB = manifest.dashboard.id as string;
// `~=`: a card row's placeholder names every card of the row.
const tile = (page: Page, index: string) =>
  page.locator(`[data-depictio-tile~="${TAB}:${index}"]`);

async function scatterPoints(page: Page): Promise<number> {
  return page.evaluate(() => {
    const gd = document.querySelector(
      '[data-depictio-tile$=":scatter-mass-flipper"] .js-plotly-plot',
    ) as unknown as { data?: { x?: unknown[]; visible?: boolean | string }[] } | null;
    return (gd?.data ?? [])
      .filter((t) => t.visible !== false)
      .reduce((n, t) => n + (Array.isArray(t.x) ? t.x.length : 0), 0);
  });
}

test.describe("report host — the runtime mounted into a report", () => {
  test.beforeEach(() => skipUnlessReportRuntimeBuilt());

  test("tiles mount in place, open on the exported state and follow the panel", async ({
    page,
  }) => {
    const attempts = await blockNetwork(page);
    await page.goto(reportUrl(ADELIE));
    await expect(page.locator("[data-depictio-filters][data-depictio-mounted]")).toHaveCount(1, {
      timeout: 30_000,
    });

    // Every tile the manifest holds is drawn, and its fallback hidden: one
    // output per tile, never two.
    await expect(page.locator("[data-depictio-tile][data-depictio-mounted]")).toHaveCount(7);
    for (const fallback of await page
      .locator("[data-depictio-mounted] > .depictio-fallback")
      .all()) {
      await expect(fallback).toBeHidden();
    }
    // A tile the manifest does not hold keeps the export's own output.
    const missing = tile(page, "not-in-the-manifest");
    await expect(missing).not.toHaveAttribute("data-depictio-mounted", "");
    await expect(missing.locator(".depictio-fallback")).toBeVisible();
    await expect(missing).toHaveAttribute("data-depictio-fallback-reason", /not in tab/);

    // The exported state: Adelie only, in the card and in the figure.
    const cards = tile(page, "card-body-mass");
    await expect(cards.getByText("3,700.6623")).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => scatterPoints(page), { timeout: 30_000 }).toBe(151);

    // Drop the species filter in the report's own panel: the card and the
    // scatter recompute in the page.
    const panel = page.locator("[data-testid='depictio-report-filters']");
    await panel.locator(".mantine-MultiSelect-root .mantine-Pill-remove").first().click();
    await expect(cards.getByText("4,201.7544")).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => scatterPoints(page), { timeout: 30_000 }).toBe(342);

    // And back to the state the document narrates.
    await page.locator("[data-testid='depictio-report-reset']").click();
    await expect(cards.getByText("3,700.6623")).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => scatterPoints(page), { timeout: 30_000 }).toBe(151);

    expect(attempts).toEqual([]);
  });

  test("the runtime does not restyle the report around it", async ({ page }) => {
    const attempts = await blockNetwork(page);
    await page.goto(reportUrl());
    await expect(page.locator("[data-depictio-tile][data-depictio-mounted]").first()).toBeAttached({
      timeout: 30_000,
    });
    const host = await page.evaluate(() => ({
      font: getComputedStyle(document.body).fontFamily,
      margin: getComputedStyle(document.body).margin,
      probe: getComputedStyle(document.querySelector(".host-probe")!).marginBottom,
    }));
    expect(host.font).toContain("Georgia");
    expect(host.margin).toBe("0px");
    expect(host.probe).toBe("16px");
    // With no exported filter, the dashboard's default state: every row.
    await expect(tile(page, "card-body-mass").getByText("4,201.7544")).toBeVisible({
      timeout: 30_000,
    });
    expect(attempts).toEqual([]);
  });

});

test.describe("report host — scripts blocked", () => {
  test.use({ javaScriptEnabled: false });
  test.beforeEach(() => skipUnlessReportRuntimeBuilt());

  test("without the runtime, the report is its fallbacks", async ({ page }) => {
    const attempts = await blockNetwork(page);
    await page.goto(reportUrl(ADELIE));
    await expect(page.locator("[data-depictio-mounted]")).toHaveCount(0);
    for (const fallback of await page.locator(".depictio-fallback").all()) {
      await expect(fallback).toBeVisible();
    }
    expect(attempts).toEqual([]);
  });
});
