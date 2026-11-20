/**
 * The report host: the static runtime mounted into the tiles of a Quarto
 * report, from `file://`, with no network.
 *
 * One manifest (producer B's penguins demo, the same contract producer A
 * writes for a report), inlined once beside the static runtime in its
 * report-only output (no "Report | Dashboard" switch), at the end of a page
 * laid out as Quarto renders the notebook generator's placeholders. The
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
  skipUnlessRuntimeBuilt,
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
  test.beforeEach(() => skipUnlessRuntimeBuilt());

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
    // A figure draws once it is near the viewport (the report mounts lazily).
    await tile(page, "scatter-mass-flipper").scrollIntoViewIfNeeded();
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
    // With no exported filter, no filter: every row.
    await expect(tile(page, "card-body-mass").getByText("4,201.7544")).toBeVisible({
      timeout: 30_000,
    });
    expect(attempts).toEqual([]);
  });

  test("the report alone offers no dashboard", async ({ page }) => {
    const attempts = await blockNetwork(page);
    await page.goto(reportUrl(ADELIE));
    await expect(page.locator("[data-depictio-tile][data-depictio-mounted]").first()).toBeAttached({
      timeout: 30_000,
    });
    await expect(page.locator(".dpx-open-dashboard")).toHaveCount(0);
    await expect(page.locator(".dpx-tile-open")).toHaveCount(0);
    await expect(page.locator("iframe")).toHaveCount(0);
    expect(await page.evaluate(() => "__DEPICTIO_COMBINED__" in window)).toBe(false);
    // The panel speaks of this page only.
    await expect(page.locator("[data-testid='depictio-report-filters']")).toContainText(
      "recomputes in this page",
    );
    expect(attempts).toEqual([]);
  });

  test("the exported state wins over a filter's default", async ({ page }) => {
    // The species filter defaults to Adelie on the dashboard, and the reader
    // cleared it before exporting: the report opens with no filter, as the
    // document says, not on the default.
    const attempts = await blockNetwork(page);
    await page.goto(
      reportUrl([], (m) => {
        const filter = m.dashboard.doc.stored_metadata.find(
          (c: { index: string }) => c.index === "filter-species",
        );
        filter.default_state = { default_value: ["Adelie"] };
        filter.default_value = ["Adelie"];
        for (const tab of m.tabs ?? []) {
          const same = tab.doc.stored_metadata?.find(
            (c: { index: string }) => c.index === "filter-species",
          );
          if (same) Object.assign(same, { default_state: filter.default_state, default_value: ["Adelie"] });
        }
      }),
    );
    await expect(tile(page, "card-body-mass").getByText("4,201.7544")).toBeVisible({
      timeout: 30_000,
    });
    await tile(page, "scatter-mass-flipper").scrollIntoViewIfNeeded();
    await expect.poll(() => scatterPoints(page), { timeout: 30_000 }).toBe(342);
    expect(attempts).toEqual([]);
  });
});

test.describe("report host — scripts blocked", () => {
  test.use({ javaScriptEnabled: false });
  test.beforeEach(() => skipUnlessRuntimeBuilt());

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
