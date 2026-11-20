/**
 * Phase-6 exit criterion: a CODE-MODE figure with a transpiled prologue
 * renders LIVE offline — mask the base table, replay the prologue IR
 * (group_by + sort here), refill the scaffold from the derived frame.
 *
 * Contract with the producer half: the penguins manifest ships component
 * `figure-codemode`, a code-mode bar chart whose prologue is
 *   df2 = df.group_by("species").agg(pl.col("body_mass_g").mean().alias("mean_mass"))
 *   df2 = df2.sort("mean_mass", descending=True)
 *   fig = px.bar(df2, x="species", y="mean_mass")
 * Until that lands (manifest has no non-empty prologues entry for it), this
 * spec skips.
 *
 * Reference values — computed with ./venv/bin/python + Polars over the joined
 * penguins CSVs (depictio/projects/init/penguins/data), NOT by hand:
 *   mean(body_mass_g) by species, descending:
 *     Gentoo    5076.016260162602
 *     Chinstrap 3733.0882352941176
 *     Adelie    3700.662251655629   (same pin as filter-parity-cards.spec.ts)
 * Adelie-only (species filter): single bar at 3700.662251655629.
 * If these assertions drift, the in-browser prologue/refill kernels no longer
 * match Polars — that is a real bug, not a flaky test.
 */
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import {
  PENGUINS_MANIFEST,
  blockNetwork,
  injectedBundleUrl,
  skipUnlessBundleBuilt,
} from "./helpers";

const MEAN_GENTOO = 5076.016260162602;
const MEAN_CHINSTRAP = 3733.0882352941176;
const MEAN_ADELIE = 3700.662251655629;

interface PlotlyTrace {
  type?: string;
  x?: unknown[];
  y?: unknown[];
  visible?: boolean | string;
}

/** The manifest, loaded the way helpers.ts loads it for injection. */
function penguinsManifest(): { prologues?: Record<string, unknown[]> } {
  return JSON.parse(readFileSync(PENGUINS_MANIFEST, "utf-8"));
}

function hasCodemodePrologue(): boolean {
  const ops = penguinsManifest().prologues?.["figure-codemode"];
  return Array.isArray(ops) && ops.length > 0;
}

/** Visible bar-trace data across all mounted Plotly plots (the bar chart is
 *  the only bar-typed figure on the penguins dashboard; the scatter is
 *  scatter/scattergl). */
async function barData(page: import("@playwright/test").Page) {
  return page.evaluate(() => {
    const plots = document.querySelectorAll(".js-plotly-plot");
    for (const el of plots) {
      const gd = el as unknown as { data?: PlotlyTrace[] };
      const traces = gd.data ?? [];
      if (!traces.some((t) => t.type === "bar")) continue;
      const visible = traces.filter(
        (t) => t.type === "bar" && t.visible !== false,
      );
      return {
        found: true,
        visibleBarTraces: visible.length,
        x: visible.flatMap((t) => (Array.isArray(t.x) ? t.x : [])),
        y: visible.flatMap((t) => (Array.isArray(t.y) ? t.y : [])),
      };
    }
    return { found: false, visibleBarTraces: 0, x: [], y: [] };
  });
}

/** FigureRenderer only fetches once in view — the codemode bar chart may sit
 *  below the fold, so sweep every grid item through the viewport to arm all
 *  in-view gates before polling (verified: without this the figure never
 *  renders headless). */
async function scrollAllIntoView(page: import("@playwright/test").Page) {
  const items = page.locator(".react-grid-item");
  const count = await items.count();
  for (let i = 0; i < count; i++) {
    await items.nth(i).scrollIntoViewIfNeeded();
  }
}

test.describe("static bundle — code-mode prologue figure (penguins)", () => {
  test.beforeEach(() => {
    skipUnlessBundleBuilt();
    test.skip(
      !hasCodemodePrologue(),
      "penguins manifest has no figure-codemode prologue yet — producer half not landed",
    );
  });

  test("the bar chart derives live from the prologue and refills on filter", async ({
    page,
  }) => {
    const attempts = await blockNetwork(page);
    await page.goto(injectedBundleUrl(PENGUINS_MANIFEST));
    await page.waitForSelector(".js-plotly-plot", {
      state: "attached",
      timeout: 30_000,
    });
    await scrollAllIntoView(page);

    // Unfiltered: one bar trace with the 3 species in DESCENDING mean order
    // (the prologue's sort drives category order), values = Polars means.
    await expect
      .poll(async () => (await barData(page)).x.length, { timeout: 30_000 })
      .toBe(3);
    const before = await barData(page);
    expect(before.visibleBarTraces).toBe(1);
    expect(before.x).toEqual(["Gentoo", "Chinstrap", "Adelie"]);
    expect(before.y[0] as number).toBeCloseTo(MEAN_GENTOO, 6);
    expect(before.y[1] as number).toBeCloseTo(MEAN_CHINSTRAP, 6);
    expect(before.y[2] as number).toBeCloseTo(MEAN_ADELIE, 6);
    // Live, not frozen.
    await expect(page.locator('[data-static-tier="frozen"]')).toHaveCount(0);

    // Filter to Adelie via the species MultiSelect: the mask applies to the
    // BASE rows, the prologue re-groups the survivors → a single Adelie bar.
    await page.locator(".mantine-MultiSelect-input").first().click();
    await page.getByRole("option", { name: "Adelie" }).click();
    await page.keyboard.press("Escape");
    await scrollAllIntoView(page);

    await expect
      .poll(async () => (await barData(page)).x.length, { timeout: 30_000 })
      .toBe(1);
    const filtered = await barData(page);
    expect(filtered.visibleBarTraces).toBe(1);
    expect(filtered.x).toEqual(["Adelie"]);
    expect(filtered.y[0] as number).toBeCloseTo(MEAN_ADELIE, 6);

    // Clear the filter (toggle Adelie back off, Escape to close): the chart
    // refills to the full 3-species derivation.
    await page.locator(".mantine-MultiSelect-input").first().click();
    await page.getByRole("option", { name: "Adelie" }).click();
    await page.keyboard.press("Escape");
    await scrollAllIntoView(page);

    await expect
      .poll(async () => (await barData(page)).x.length, { timeout: 30_000 })
      .toBe(3);
    const after = await barData(page);
    expect(after.x).toEqual(["Gentoo", "Chinstrap", "Adelie"]);
    expect(after.y[0] as number).toBeCloseTo(MEAN_GENTOO, 6);

    expect(attempts).toEqual([]);
  });
});
