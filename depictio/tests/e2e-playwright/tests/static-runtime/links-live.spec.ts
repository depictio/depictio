/**
 * Phase-7 exit criterion: CROSS-DC LINKS resolve in the browser. A filter set
 * on one data collection reaches the components of another through the
 * project's link graph — the offline port of `extend_filters_via_links`
 * (depictio/api/v1/filter_links.py), with the source-DC translation query run
 * against the bundled Parquet instead of a Delta scan (tier A).
 *
 * Contract with the producer half: the penguins manifest ships TWO data
 * collections in one workflow —
 *   joined_penguins_complete   342 measurement rows (island, species, …)
 *   island_regions             4-row lookup: island → region
 * — plus one direct link `island_regions.island -> joined_penguins_complete`
 * (same join column on both sides, resolver `direct`, no target_field). The
 * `region` MultiSelect lives on the LOOKUP collection: `region` is not a
 * penguins column at all, so a region selection can only reach the penguins
 * components through the link. Until that lands this spec skips.
 *
 * Reference values — computed with ./venv/bin/python + Polars over the
 * manifest's own inline Parquet blobs, NOT by hand:
 *
 *   region "Palmer Archipelago East" → island Biscoe
 *     rows                     167 of 342
 *     mean(body_mass_g)        4716.017964071856 → card text "4716.018"
 *     n_unique(species)        2  (Adelie 44, Gentoo 123)
 *   region "Uncharted" → island "Alpha"
 *     rows                       0   — "Alpha" is in the lookup table on
 *     purpose and in no penguin row, so the link resolves to a real value that
 *     matches nothing downstream: the visible zero-state.
 *   species "Adelie" (penguins side)  151 of 342 rows, and the lookup table
 *     keeps all 4 of its rows — no link points back that way.
 *
 * If these drift, the browser's link walk no longer agrees with the server's,
 * which is a real bug rather than a flaky test.
 */
import { readFileSync } from "node:fs";
import { expect, test, type Locator, type Page } from "@playwright/test";
import {
  PENGUINS_MANIFEST,
  blockNetwork,
  injectedBundleUrl,
  skipUnlessBundleBuilt,
} from "./helpers";

const DOTPLOT = "dotplot-mass";

/** Biscoe (= region "Palmer Archipelago East") reference values. */
const BISCOE_ROWS = 167;
const BISCOE_MEAN_MASS = "4716.018";
const BISCOE_SPECIES = "2";
/** Whole frame / penguins-side species filter. */
const ALL_ROWS = 342;
const ALL_MEAN_MASS = "4201.7544";
const ADELIE_ROWS = 151;
/** The lookup collection's own row count. */
const LOOKUP_ROWS = 4;

const REGION_EAST = "Palmer Archipelago East";
const REGION_WEST = "Palmer Archipelago West";
const REGION_NONE = "Uncharted";

function manifest(): {
  links?: { configs?: { source_dc_id?: string; target_dc_id?: string }[] };
} {
  return JSON.parse(readFileSync(PENGUINS_MANIFEST, "utf-8"));
}

/** The demo carries the two-DC link (producer half landed). */
function hasCrossDcLink(): boolean {
  const configs = manifest().links?.configs ?? [];
  return configs.some((c) => c.source_dc_id && c.target_dc_id && c.source_dc_id !== c.target_dc_id);
}

/** Renderers are viewport-gated (LazyMount + their own useInView) and most of
 *  the dashboard sits below the fold — sweep every grid item through the
 *  viewport, as the code-mode and advanced-viz specs do. */
async function scrollAllIntoView(page: Page) {
  const items = page.locator(".react-grid-item");
  const count = await items.count();
  for (let i = 0; i < count; i++) {
    await items.nth(i).scrollIntoViewIfNeeded();
  }
}

/** A table component's grid item, scrolled into view. */
async function tableItem(page: Page, title: string): Promise<Locator> {
  const item = page.locator(".react-grid-item", { hasText: title }).first();
  await item.scrollIntoViewIfNeeded();
  return item;
}

/** Rendered AG Grid rows of a table item. The "N rows" badge only appears once
 *  a table spans more than one page (TableRenderer's `hasReduction`), so small
 *  and empty results are counted off the grid itself. */
function gridRows(table: Locator): Locator {
  return table.locator(".ag-center-cols-container .ag-row");
}

/** Left-panel MultiSelects in YAML order: species, year, region. */
function regionFilter(page: Page): Locator {
  return page.locator(".mantine-MultiSelect-input").nth(2);
}

function speciesFilter(page: Page): Locator {
  return page.locator(".mantine-MultiSelect-input").first();
}

/** Toggle one option of a MultiSelect (open, click, Escape to close). */
async function toggleOption(page: Page, filter: Locator, option: string) {
  await filter.click();
  await page.getByRole("option", { name: option, exact: true }).click();
  await page.keyboard.press("Escape");
  await scrollAllIntoView(page);
}

/** Marker count of the dot plot's point trace — one marker per DC row, so it
 *  reads the link-filtered row count straight off the advanced-viz data path
 *  (see advanced-viz-live.spec.ts). */
async function dotPlotPoints(page: Page): Promise<number> {
  return page.evaluate((componentId) => {
    const el = document.querySelector(`[data-component-id="${componentId}"] .js-plotly-plot`);
    if (!el) return -1;
    const traces = (
      (el as unknown as { data?: { type?: string; x?: unknown[] }[] }).data ?? []
    ).filter((t) => t.type === "scattergl" || t.type === "scatter");
    return traces.reduce((n, t) => n + (Array.isArray(t.x) ? t.x.length : 0), 0);
  }, DOTPLOT);
}

async function openBundle(page: Page): Promise<string[]> {
  const attempts = await blockNetwork(page);
  await page.goto(injectedBundleUrl(PENGUINS_MANIFEST));
  await page.waitForSelector(".react-grid-item", { timeout: 30_000 });
  await scrollAllIntoView(page);
  return attempts;
}

test.describe("static bundle — cross-DC link resolution (penguins)", () => {
  test.beforeEach(() => {
    skipUnlessBundleBuilt();
    test.skip(
      !hasCrossDcLink(),
      "penguins manifest ships no cross-DC link yet — producer half not landed",
    );
  });

  test("the region filter reads its options from the linked collection", async ({ page }) => {
    const attempts = await openBundle(page);

    // Options come from the LOOKUP DC's `region` column (a column the penguins
    // frame does not have), through the same live unique-values path.
    await regionFilter(page).click();
    for (const region of [REGION_EAST, REGION_WEST, REGION_NONE]) {
      await expect(page.getByRole("option", { name: region, exact: true })).toBeVisible({
        timeout: 30_000,
      });
    }
    await expect(page.getByRole("option")).toHaveCount(3);
    await page.keyboard.press("Escape");

    // The lookup collection itself renders live, all 4 rows.
    const lookup = await tableItem(page, "Island Regions");
    await expect(gridRows(lookup)).toHaveCount(LOOKUP_ROWS, { timeout: 30_000 });
    await expect(page.locator('[data-static-tier="frozen"]')).toHaveCount(0);

    expect(attempts).toEqual([]);
  });

  test("a region selection filters the penguins collection through the link", async ({ page }) => {
    const attempts = await openBundle(page);

    // Unfiltered baseline.
    const penguins = await tableItem(page, "Raw Measurements");
    await expect(penguins.getByText(`${ALL_ROWS} rows`)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(ALL_MEAN_MASS)).toBeVisible();

    // region "Palmer Archipelago East" → island "Biscoe" → the 167 Biscoe
    // penguins. Nothing on the penguins DC is named `region`: every one of
    // these numbers arrived through the link walk.
    await toggleOption(page, regionFilter(page), REGION_EAST);

    await expect(penguins.getByText(`${BISCOE_ROWS} rows`)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(BISCOE_MEAN_MASS)).toBeVisible({ timeout: 30_000 });
    const speciesCard = page.locator(".react-grid-item", { hasText: "Species" }).first();
    await expect(speciesCard.getByText(BISCOE_SPECIES, { exact: true })).toBeVisible();
    await expect.poll(async () => await dotPlotPoints(page), { timeout: 30_000 }).toBe(BISCOE_ROWS);

    // The lookup table is the link's SOURCE: `region` is its own column, so it
    // narrows natively to the one row that produced the translation.
    const lookup = await tableItem(page, "Island Regions");
    await expect(gridRows(lookup)).toHaveCount(1, { timeout: 30_000 });

    // Clearing restores every component — link resolution runs per render, not
    // once at mount.
    await toggleOption(page, regionFilter(page), REGION_EAST);
    await expect(penguins.getByText(`${ALL_ROWS} rows`)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(ALL_MEAN_MASS)).toBeVisible({ timeout: 30_000 });

    expect(attempts).toEqual([]);
  });

  test("a region matching no penguin island renders the zero state", async ({ page }) => {
    const attempts = await openBundle(page);

    const penguins = await tableItem(page, "Raw Measurements");
    await expect(penguins.getByText(`${ALL_ROWS} rows`)).toBeVisible({ timeout: 30_000 });

    // "Uncharted" resolves to island "Alpha" — a real translated value that
    // matches no penguin row. The link is NOT a no-match (that would be a
    // region absent from the lookup table, unreachable from this dropdown):
    // the filter propagates and simply selects nothing.
    await toggleOption(page, regionFilter(page), REGION_NONE);

    await expect(gridRows(penguins)).toHaveCount(0, { timeout: 30_000 });
    // Mean of an empty selection has no answer → the card's em-dash empty
    // state; nunique of an empty selection is 0 (engine aggregate contract).
    const massCard = page.locator(".react-grid-item", { hasText: "Mean Body Mass" }).first();
    await expect(massCard.getByText("—", { exact: true })).toBeVisible({ timeout: 30_000 });
    const speciesCard = page.locator(".react-grid-item", { hasText: "Species" }).first();
    await expect(speciesCard.getByText("0", { exact: true })).toBeVisible();
    // The advanced-viz data path returns an empty frame, so the dot plot drops
    // its chart for the renderer's own empty state rather than plotting zero
    // markers.
    await expect(
      page.locator(`[data-component-id="${DOTPLOT}"]`).getByText("No data"),
    ).toBeVisible({ timeout: 30_000 });

    // The lookup table still shows the row the selection came from.
    const lookup = await tableItem(page, "Island Regions");
    await expect(gridRows(lookup)).toHaveCount(1, { timeout: 30_000 });

    expect(attempts).toEqual([]);
  });

  test("penguins-side filters do not travel back to the lookup collection", async ({ page }) => {
    const attempts = await openBundle(page);

    const lookup = await tableItem(page, "Island Regions");
    await expect(gridRows(lookup)).toHaveCount(LOOKUP_ROWS, { timeout: 30_000 });

    // The link is one-way (island_regions → joined_penguins_complete) and
    // `species` is not a lookup column: the lookup table keeps all its rows
    // while the penguins table narrows.
    await toggleOption(page, speciesFilter(page), "Adelie");

    const penguins = await tableItem(page, "Raw Measurements");
    await expect(penguins.getByText(`${ADELIE_ROWS} rows`)).toBeVisible({ timeout: 30_000 });
    await expect(gridRows(lookup)).toHaveCount(LOOKUP_ROWS);

    expect(attempts).toEqual([]);
  });
});
