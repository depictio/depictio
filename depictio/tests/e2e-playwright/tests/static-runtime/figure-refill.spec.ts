/**
 * Phase-5 exit criterion (the user's #1 ask): a bound ui-mode figure
 * re-renders offline when a filter changes — bind-and-refill (RFC §4).
 *
 * Reference counts from the penguins data: 342 rows total; species split
 * Adelie 151 / Chinstrap 68 / Gentoo 123. Selecting Adelie must drop the
 * plotted point count to 151 with the trace count stable (hidden traces stay,
 * visible:false) and zero network attempts.
 */
import { expect, test } from "@playwright/test";
import {
  PENGUINS_MANIFEST,
  blockNetwork,
  injectedBundleUrl,
  skipUnlessBundleBuilt,
} from "./helpers";

interface PlotlyTrace {
  x?: unknown[];
  visible?: boolean | string;
}

async function plottedPoints(page: import("@playwright/test").Page) {
  return page.evaluate(() => {
    const gd = document.querySelector(".js-plotly-plot") as unknown as {
      data?: PlotlyTrace[];
    };
    const traces = gd?.data ?? [];
    return {
      traceCount: traces.length,
      points: traces
        .filter((t) => t.visible !== false)
        .reduce((n, t) => n + (Array.isArray(t.x) ? t.x.length : 0), 0),
    };
  });
}

test.describe("static bundle — bind-and-refill figure (penguins)", () => {
  test.beforeEach(() => skipUnlessBundleBuilt());

  test("the scatter refills offline when the species filter changes", async ({
    page,
  }) => {
    const attempts = await blockNetwork(page);
    await page.goto(injectedBundleUrl(PENGUINS_MANIFEST));
    // scattergl renders into a WebGL canvas whose container Playwright's
    // visibility heuristic reports as hidden — wait for attachment only; the
    // data polls below are the real readiness signal.
    await page.waitForSelector(".js-plotly-plot", {
      state: "attached",
      timeout: 30_000,
    });

    // Unfiltered: all 342 points across 3 species traces, and no Frozen badge
    // on the figure — it is live now.
    await expect
      .poll(async () => (await plottedPoints(page)).points, { timeout: 30_000 })
      .toBe(342);
    const before = await plottedPoints(page);
    expect(before.traceCount).toBe(3);
    await expect(page.locator('[data-static-tier="frozen"]')).toHaveCount(0);

    // Filter to Adelie.
    await page.locator(".mantine-MultiSelect-input").first().click();
    await page.getByRole("option", { name: "Adelie" }).click();
    await page.keyboard.press("Escape");

    // The figure refills: 151 Adelie points, other traces hidden not dropped.
    await expect
      .poll(async () => (await plottedPoints(page)).points, { timeout: 30_000 })
      .toBe(151);
    const after = await plottedPoints(page);
    expect(after.traceCount).toBe(3);

    expect(attempts).toEqual([]);
  });
});
