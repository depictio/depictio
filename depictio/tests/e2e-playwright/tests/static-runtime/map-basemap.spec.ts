/**
 * A frozen map keeps the dashboard's own basemap, and still draws offline.
 *
 * Bundles used to force `white-bg` on every map so they never touched the
 * network; they now keep `map_style` (depictio/serverless/maps.py), so the
 * basemap loads for an online reader. Two promises follow, both checked here:
 *
 * - offline (every non-file request aborted), the markers still draw — on a
 *   blank background, since a Carto style that never loads would otherwise
 *   leave MapLibre with no trace layers — with no page error, and the only
 *   requests ever attempted go to the basemap hosts, listed explicitly;
 * - online (the style.json answered), the figure keeps that basemap and the
 *   markers draw over it, again with no page error.
 */
import { expect, test, type Page } from "@playwright/test";

import { MAP_MANIFEST, injectedBundleUrl, isDisguisedServerCall, skipUnlessBundleBuilt } from "./helpers";

/** The basemap hosts a map tile may contact (maps.py / mapBasemap.ts BASEMAP_HOSTS). */
const BASEMAP_HOSTS = new Set([
  "basemaps.cartocdn.com",
  "tiles.basemaps.cartocdn.com",
  "tiles-a.basemaps.cartocdn.com",
  "tiles-b.basemaps.cartocdn.com",
  "tiles-c.basemaps.cartocdn.com",
  "tiles-d.basemaps.cartocdn.com",
  "tile.openstreetmap.org",
]);

/** A minimal stand-in for Carto's style.json: one background layer, no sources. */
const FAKE_STYLE = {
  version: 8,
  name: "fake-positron",
  sources: {},
  layers: [{ id: "fake-positron-bg", type: "background", paint: { "background-color": "#eeeeee" } }],
};

test.beforeEach(() => skipUnlessBundleBuilt());

async function route(page: Page, online: boolean): Promise<string[]> {
  const attempts: string[] = [];
  await page.route("**/*", async (r) => {
    const url = r.request().url();
    if (url.startsWith("file://") && !isDisguisedServerCall(url)) return r.continue();
    attempts.push(url);
    if (online && url.endsWith("/positron-gl-style/style.json")) {
      return r.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "access-control-allow-origin": "*" },
        body: JSON.stringify(FAKE_STYLE),
      });
    }
    return r.abort();
  });
  return attempts;
}

/** The map subplot's style and how many plotly trace layers MapLibre holds. */
async function mapState(page: Page) {
  return page.evaluate(() => {
    for (const gd of Array.from(document.querySelectorAll(".js-plotly-plot"))) {
      const full = (gd as unknown as { _fullLayout?: Record<string, any> })._fullLayout;
      const sub = full?.map;
      if (!sub) continue;
      const map = sub._subplot?.map;
      const layers: string[] = map ? map.getStyle().layers.map((l: { id: string }) => l.id) : [];
      return {
        style: typeof sub.style === "string" ? sub.style : (sub.style?.name as string),
        traceLayers: layers.filter((id) => id.startsWith("plotly-trace-layer")).length,
      };
    }
    return null;
  });
}

for (const online of [false, true]) {
  test(`a frozen map draws its markers ${online ? "over its basemap" : "offline"}`, async ({ page }) => {
    const attempts = await route(page, online);
    const pageErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(String(err)));

    await page.goto(injectedBundleUrl(MAP_MANIFEST));
    const tile = page.locator(".react-grid-item", { hasText: "Sampling locations" }).first();
    await expect(tile).toBeVisible();
    await expect(tile.getByText("marine")).toBeVisible(); // legend: the family colours' categories

    await expect.poll(async () => (await mapState(page))?.traceLayers ?? 0, { timeout: 20_000 }).toBeGreaterThan(0);
    const state = await mapState(page);
    expect(state?.style).toBe(online ? "fake-positron" : "depictio-offline-blank");

    // A filter change re-renders the map with a fresh style object. Plotly
    // relinks the old full layout onto it and deletes every empty object on
    // the way: a blank style with `sources: {}` lost its `sources`, MapLibre
    // refused it, and Plotly threw `Error: Map error.` (ampliseq, offline).
    await page.locator("input.mantine-MultiSelect-inputField").first().click();
    await page.getByRole("option").first().click();
    await page.keyboard.press("Escape");
    await expect(page.getByText(/Samples/).first()).toBeVisible();
    await page.waitForTimeout(1500);
    expect((await mapState(page))?.traceLayers ?? 0).toBeGreaterThan(0);
    expect((await mapState(page))?.style).toBe(online ? "fake-positron" : "depictio-offline-blank");

    const hosts = attempts.map((u) => new URL(u).host);
    const stray = hosts.filter((h) => !BASEMAP_HOSTS.has(h));
    expect(stray, `requests outside the basemap hosts:\n${attempts.join("\n")}`).toHaveLength(0);
    expect(hosts.length).toBeGreaterThan(0); // the probe did reach for the basemap
    expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
  });
}
