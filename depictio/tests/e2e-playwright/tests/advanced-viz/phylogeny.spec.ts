/**
 * Phylogeny renderer UX (issue #935): zoom on/off toggle, drag-to-pan while
 * zoomed, subtree select/deselect, and the subtree actions (filter to
 * subtree, export .nwk).
 *
 * Runs against the seeded `advanced_viz_showcase` phylogeny dashboard
 * (public, single "phylo-tree" component, 21-tip bacterial tree — small
 * enough that every trace renders as SVG). Skips when that dashboard isn't
 * seeded (custom stacks with example dashboards disabled).
 *
 * Plotly's canvas has no per-node DOM hooks, so node clicks are driven by
 * converting the internal-node trace's data coordinates to pixels via
 * `_fullLayout` axis converters; zoom/pan state is asserted on
 * `_fullLayout.dragmode` / `xaxis.range`.
 */

import { test, expect, getAuthMode, API_URL, API_PREFIX } from "@fixtures/auth";
import type { Page } from "@playwright/test";

// _id of .db_seeds/dashboard_phylogeny.json in projects/init/advanced_viz_showcase.
const PHYLO_DASHBOARD_ID = "646b0f3c1e4a2d7f8e5b8d18";

const PLOT = ".js-plotly-plot";

async function dragmode(page: Page): Promise<unknown> {
  return page.evaluate(
    (sel) => (document.querySelector(sel) as any)?._fullLayout?.dragmode,
    PLOT,
  );
}

async function xRange(page: Page): Promise<number[]> {
  return page.evaluate(
    (sel) => [...(document.querySelector(sel) as any)._fullLayout.xaxis.range],
    PLOT,
  );
}

/** Pixel position (viewport coords) of the i-th point of the invisible
 *  internal-node click-target trace.
 *
 *  A tree with more tips than the fold can hold leaves the deepest node below
 *  the viewport, and `page.mouse.click` only dispatches inside it — so the
 *  point is scrolled into view before it is measured. The canvas scrolls in
 *  its own container rather than the window, hence the ancestor walk. */
async function internalNodePixel(
  page: Page,
  which: "first" | "deepest",
): Promise<{ x: number; y: number }> {
  const measure = () =>
    page.evaluate(
      ({ sel, which }) => {
        const gd = document.querySelector(sel) as any;
        const trace = gd._fullData.find((t: any) =>
          String(t.hovertemplate ?? "").includes("highlight subtree"),
        );
        if (!trace) throw new Error("internal-node trace not found");
        let i = 0;
        if (which === "deepest") {
          for (let k = 1; k < trace.x.length; k++) if (trace.x[k] > trace.x[i]) i = k;
        }
        const rect = gd.getBoundingClientRect();
        const fl = gd._fullLayout;
        return {
          x: rect.left + fl.xaxis._offset + fl.xaxis.d2p(trace.x[i]),
          y: rect.top + fl.yaxis._offset + fl.yaxis.d2p(trace.y[i]),
        };
      },
      { sel: PLOT, which },
    );

  const pt = await measure();
  const height = page.viewportSize()!.height;
  // Leave a margin so a point flush against an edge still takes the click.
  if (pt.y >= 8 && pt.y <= height - 8) return pt;

  await page.evaluate(
    ({ sel, dy }) => {
      let el = document.querySelector(sel) as HTMLElement | null;
      while (el) {
        const overflowY = getComputedStyle(el).overflowY;
        if (/(auto|scroll)/.test(overflowY) && el.scrollHeight > el.clientHeight) {
          el.scrollTop += dy;
          return;
        }
        el = el.parentElement;
      }
      window.scrollBy(0, dy);
    },
    { sel: PLOT, dy: pt.y - height / 2 },
  );

  return measure();
}

async function tipCount(page: Page): Promise<number> {
  return page.evaluate((sel) => {
    const gd = document.querySelector(sel) as any;
    // The tips trace is the marker trace carrying per-point text labels.
    const tips = gd._fullData.find(
      (t: any) => String(t.mode ?? "").includes("markers") && Array.isArray(t.text),
    );
    return tips ? tips.x.length : -1;
  }, PLOT);
}

test.describe("Phylogeny zoom / pan / subtree selection", () => {
  test.beforeEach(async ({ page, request, loginAsAdmin }) => {
    // Anonymous 404 means the showcase project isn't seeded on this stack
    // (CI always seeds it). Auth-shaped statuses (401/403) still prove the
    // dashboard exists, so only a real 404 skips.
    const probe = await request.get(
      `${API_URL}${API_PREFIX}/dashboards/get/${PHYLO_DASHBOARD_ID}`,
    );
    test.skip(probe.status() === 404, "advanced_viz_showcase phylogeny dashboard not seeded");

    const mode = await getAuthMode();
    if (!mode.is_single_user_mode && !mode.is_public_mode) {
      await loginAsAdmin();
    }
    await page.goto(`/dashboard/${PHYLO_DASHBOARD_ID}`);
    await expect(page.locator("[data-testid='phylo-toolbar']")).toBeVisible({
      timeout: 30_000,
    });
    // The figure mounts after the newick + metadata fetches resolve.
    await page.waitForFunction(
      (sel) => Boolean((document.querySelector(sel) as any)?._fullLayout?.xaxis),
      PLOT,
      { timeout: 30_000 },
    );
  });

  test("zoom toggle enables pan-dragging and reset view restores the fit", async ({ page }) => {
    // Off by default: no drag interaction at all.
    expect(await dragmode(page)).toBe(false);

    await page.locator("[data-testid='phylo-zoom-toggle']").click();
    await page.waitForFunction(
      (sel) => (document.querySelector(sel) as any)?._fullLayout?.dragmode === "pan",
      PLOT,
    );

    // Drag = pan: the x-range shifts.
    const fitted = await xRange(page);
    const box = (await page.locator(PLOT).boundingBox())!;
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.move(cx - 120, cy, { steps: 5 });
    await page.mouse.up();
    await expect
      .poll(async () => {
        const r = await xRange(page);
        return Math.abs(r[0] - fitted[0]);
      })
      .toBeGreaterThan(1e-6);

    // Reset view re-applies the fitted ranges.
    await page.locator("[data-testid='phylo-reset-view']").click();
    await expect
      .poll(async () => {
        const r = await xRange(page);
        return Math.abs(r[0] - fitted[0]) + Math.abs(r[1] - fitted[1]);
      })
      .toBeLessThan(1e-6);

    // Toggle back off.
    await page.locator("[data-testid='phylo-zoom-toggle']").click();
    await page.waitForFunction(
      (sel) => (document.querySelector(sel) as any)?._fullLayout?.dragmode === false,
      PLOT,
    );
  });

  test("subtree selects on click, deselects on re-click and via the clear control", async ({
    page,
  }) => {
    const info = page.locator("[data-testid='phylo-selection-info']");
    await expect(info).toBeHidden();

    const node = await internalNodePixel(page, "deepest");
    await page.mouse.click(node.x, node.y);
    await expect(info).toBeVisible();
    await expect(info).toContainText("Tips");

    // Re-clicking the same node deselects.
    await page.mouse.click(node.x, node.y);
    await expect(info).toBeHidden();

    // Explicit clear control.
    await page.mouse.click(node.x, node.y);
    await expect(info).toBeVisible();
    await page.locator("[data-testid='phylo-clear-selection']").click();
    await expect(info).toBeHidden();
  });

  test("filter-to-subtree toggles without dimming the tree's own tips", async ({ page }) => {
    const allTips = await tipCount(page);
    expect(allTips).toBeGreaterThan(0);

    const node = await internalNodePixel(page, "deepest");
    await page.mouse.click(node.x, node.y);

    const filterBtn = page.locator("[data-testid='phylo-filter-subtree']");
    await expect(filterBtn).toHaveText("Filter");
    await filterBtn.click();
    await expect(filterBtn).toHaveText("Filtered");

    // Self-exclusion: the tree strips its own filter before fetching, so it
    // keeps rendering every tip (the selection reads as the highlight).
    expect(await tipCount(page)).toBe(allTips);

    await filterBtn.click();
    await expect(filterBtn).toHaveText("Filter");
  });

  test("export .nwk downloads the selected clade", async ({ page }) => {
    const node = await internalNodePixel(page, "deepest");
    await page.mouse.click(node.x, node.y);
    await expect(page.locator("[data-testid='phylo-selection-info']")).toBeVisible();

    const downloadP = page.waitForEvent("download");
    await page.locator("[data-testid='phylo-export-newick']").click();
    const download = await downloadP;
    expect(download.suggestedFilename()).toMatch(/\.nwk$/);
  });
});
