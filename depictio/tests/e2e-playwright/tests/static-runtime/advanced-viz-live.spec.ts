/**
 * Phase-4 exit criterion: the ADVANCED VIZ data path runs offline. The
 * sunburst and dot plot on the penguins bundle call the same
 * `fetchAdvancedVizData` their server-backed counterparts do; the static
 * runtime answers it from the bundled Parquet (mask → projection →
 * `reduceFrame`, the in-browser port of the endpoint's sampling policy)
 * instead of `POST /advanced_viz/data`.
 *
 * Contract with the producer half: the manifest ships `sunburst-mass`
 * (viz_kind sunburst, rank_cols [species, island], abundance body_mass_g) and
 * `dotplot-mass` (dot_plot: cluster species, gene island, mean body_mass_g,
 * frac bill_length_mm), both tier `live`, over one 342-row DC. Until that
 * lands this spec skips.
 *
 * Reference values — computed with ./venv/bin/python + Polars over the
 * manifest's own inline Parquet blob, NOT by hand:
 *
 *   body_mass_g sum, all 342 rows                    1_437_000
 *   ... Adelie only                                    558_800
 *   (species, island) pairs present                          5
 *     Adelie/Biscoe 44, Adelie/Dream 56, Adelie/Torgersen 51,
 *     Chinstrap/Dream 68, Gentoo/Biscoe 123          → Adelie total 151
 *
 * Both kinds have sampling policy 'none' (their renderers aggregate the rows
 * they are handed), and 342 rows sit far below both the 10k display cap and
 * the 2M no-sample ceiling — so the frames must arrive whole and unflagged:
 * no "estimated" badge, no "N / M pts" badge. If these assertions drift, the
 * browser's advanced-viz data path no longer agrees with Polars, which is a
 * real bug rather than a flaky test.
 */
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import {
  PENGUINS_MANIFEST,
  blockNetwork,
  injectedBundleUrl,
  skipUnlessBundleBuilt,
} from "./helpers";

const SUNBURST = "sunburst-mass";
const DOTPLOT = "dotplot-mass";

/** body_mass_g totals (the sunburst's abundance measure). */
const MASS_ALL = 1_437_000;
const MASS_ADELIE = 558_800;
/** One dot-plot marker per DC row: the renderer plots rows, not aggregates. */
const ROWS_ALL = 342;
const ROWS_ADELIE = 151;
/** Sunburst nodes = 3 species + the 5 (species, island) pairs that exist. */
const NODES_ALL = 8;
const NODES_ADELIE = 4;

interface SunburstTrace {
  type?: string;
  ids?: string[];
  parents?: string[];
  values?: number[];
}

interface MarkerTrace {
  type?: string;
  x?: unknown[];
}

function manifest(): { tiers?: Record<string, { tier?: string }> } {
  return JSON.parse(readFileSync(PENGUINS_MANIFEST, "utf-8"));
}

function bothLive(): boolean {
  const tiers = manifest().tiers ?? {};
  return tiers[SUNBURST]?.tier === "live" && tiers[DOTPLOT]?.tier === "live";
}

/** advanced_viz renderers are viewport-gated twice over (LazyMount + the
 *  renderer's own useInView), and both charts sit below the fold — sweep every
 *  grid item through the viewport to arm the gates, as the code-mode spec
 *  does. */
async function scrollAllIntoView(page: Page) {
  const items = page.locator(".react-grid-item");
  const count = await items.count();
  for (let i = 0; i < count; i++) {
    await items.nth(i).scrollIntoViewIfNeeded();
  }
}

/** The sunburst's node table, read off the mounted Plotly graph div. `ids`
 *  are the renderer's path ids ("Adelie | Dream"), unlike `labels`, which
 *  carry the per-arc percentage text. */
async function sunburstNodes(page: Page) {
  return page.evaluate((componentId) => {
    const el = document.querySelector(
      `[data-component-id="${componentId}"] .js-plotly-plot`,
    );
    if (!el) return { found: false, nodes: 0, rootIds: [] as string[], rootTotal: 0 };
    const traces = ((el as unknown as { data?: SunburstTrace[] }).data ?? []).filter(
      (t) => t.type === "sunburst",
    );
    const ids = traces.flatMap((t) => t.ids ?? []);
    const parents = traces.flatMap((t) => t.parents ?? []);
    const values = traces.flatMap((t) => t.values ?? []);
    const rootIds: string[] = [];
    let rootTotal = 0;
    for (let i = 0; i < ids.length; i++) {
      if (parents[i] === "") {
        rootIds.push(ids[i]);
        rootTotal += Number(values[i]) || 0;
      }
    }
    return { found: true, nodes: ids.length, rootIds: rootIds.sort(), rootTotal };
  }, SUNBURST);
}

/** Marker count of the dot plot's single point trace (scattergl, or scatter
 *  when the WebGL budget declined the slot — `adaptGlTrace` swaps the type,
 *  never the arrays). */
async function dotPlotPoints(page: Page) {
  return page.evaluate((componentId) => {
    const el = document.querySelector(
      `[data-component-id="${componentId}"] .js-plotly-plot`,
    );
    if (!el) return -1;
    const traces = ((el as unknown as { data?: MarkerTrace[] }).data ?? []).filter(
      (t) => t.type === "scattergl" || t.type === "scatter",
    );
    return traces.reduce((n, t) => n + (Array.isArray(t.x) ? t.x.length : 0), 0);
  }, DOTPLOT);
}

/** Toggle one species in the left panel's MultiSelect (same driving as the
 *  code-mode spec: open, click the option, Escape to close the dropdown). */
async function toggleSpecies(page: Page, species: string) {
  await page.locator(".mantine-MultiSelect-input").first().click();
  await page.getByRole("option", { name: species }).click();
  await page.keyboard.press("Escape");
  await scrollAllIntoView(page);
}

test.describe("static bundle — live advanced viz (penguins)", () => {
  test.beforeEach(() => {
    skipUnlessBundleBuilt();
    test.skip(
      !bothLive(),
      "penguins manifest has no live sunburst + dot plot yet — producer half not landed",
    );
  });

  test("the sunburst and dot plot render from the bundle and re-render on filter", async ({
    page,
  }) => {
    const attempts = await blockNetwork(page);
    await page.goto(injectedBundleUrl(PENGUINS_MANIFEST));
    await page.waitForSelector(".js-plotly-plot", { state: "attached", timeout: 30_000 });
    await scrollAllIntoView(page);

    // Both components mount a Plotly chart rather than the frame's error
    // Alert (a live component has no frozen payload to fall back to, so a
    // broken data path shows up here as a missing chart).
    for (const componentId of [SUNBURST, DOTPLOT]) {
      await expect(
        page.locator(`[data-component-id="${componentId}"] .js-plotly-plot`),
      ).toHaveCount(1, { timeout: 30_000 });
    }

    // Unfiltered: every one of the 342 rows reaches both renderers.
    await expect
      .poll(async () => (await sunburstNodes(page)).nodes, { timeout: 30_000 })
      .toBe(NODES_ALL);
    const sunburst = await sunburstNodes(page);
    expect(sunburst.rootIds).toEqual(["Adelie", "Chinstrap", "Gentoo"]);
    expect(sunburst.rootTotal).toBeCloseTo(MASS_ALL, 6);

    await expect
      .poll(async () => await dotPlotPoints(page), { timeout: 30_000 })
      .toBe(ROWS_ALL);

    // Policy 'none' + 342 rows ≪ every ceiling ⇒ the frames are exact: no
    // reduction badge, no "estimates" warning.
    for (const componentId of [SUNBURST, DOTPLOT]) {
      const item = page.locator(`[data-component-id="${componentId}"]`);
      await expect(item.getByText("estimated", { exact: true })).toHaveCount(0);
      await expect(item.getByText(/\bpts\b/)).toHaveCount(0);
    }
    // Live, not frozen.
    await expect(page.locator('[data-static-tier="frozen"]')).toHaveCount(0);

    // Filter to Adelie: the mask is applied before projection, so both charts
    // shrink to the Adelie rows — sunburst to one root + its 3 islands, dot
    // plot to the 151 Adelie rows.
    await toggleSpecies(page, "Adelie");

    await expect
      .poll(async () => (await sunburstNodes(page)).nodes, { timeout: 30_000 })
      .toBe(NODES_ADELIE);
    const filtered = await sunburstNodes(page);
    expect(filtered.rootIds).toEqual(["Adelie"]);
    expect(filtered.rootTotal).toBeCloseTo(MASS_ADELIE, 6);

    await expect
      .poll(async () => await dotPlotPoints(page), { timeout: 30_000 })
      .toBe(ROWS_ADELIE);

    // Clearing the filter restores the whole frame — the data path is
    // recomputed per filter state, not cached from the first render.
    await toggleSpecies(page, "Adelie");

    await expect
      .poll(async () => (await sunburstNodes(page)).nodes, { timeout: 30_000 })
      .toBe(NODES_ALL);
    expect((await sunburstNodes(page)).rootTotal).toBeCloseTo(MASS_ALL, 6);
    await expect
      .poll(async () => await dotPlotPoints(page), { timeout: 30_000 })
      .toBe(ROWS_ALL);

    expect(attempts).toEqual([]);
  });
});
