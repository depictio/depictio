/**
 * Large-compute kinds offline (RFC §13).
 *
 * group_compare is frozen at the pair its tile opens on: the producer computed
 * cluster_1 vs cluster_2 with the server's own `group_compare_from_frame` and
 * pointed the tile's defaults at that pair with auto_run on, so it draws on
 * load. Another pair must NOT be answered with the frozen rows under a new
 * label — the shim fails that job with the reason.
 *
 * contact_map's whole-chromosome view is the data path; its zoom windows are
 * replayed by `contactMapWindow` (pinned to the Python function by
 * packages/depictio-static-core/fixtures/contact-map-expected.json).
 *
 * Reference: group_compare_demo.tsv has 60 gene columns, cluster_1 n=220,
 * cluster_2 n=200 (showcase data).
 */
import { expect, test, type Page } from "@playwright/test";

import {
  COMPUTE_MANIFEST,
  blockNetwork,
  injectedBundleUrl,
  skipUnlessBundleBuilt,
} from "./helpers";

test.beforeEach(() => skipUnlessBundleBuilt());

function tile(page: Page, id: string) {
  return page.locator(`[data-component-id="${id}"]`);
}

async function plotPoints(page: Page, id: string): Promise<number> {
  return page.evaluate((componentId) => {
    const el = document.querySelector(
      `[data-component-id="${componentId}"] .js-plotly-plot`,
    ) as unknown as { data?: { x?: unknown[] }[] } | null;
    return (el?.data ?? []).reduce((n, t) => n + (Array.isArray(t.x) ? t.x.length : 0), 0);
  }, id);
}

test("group_compare draws its frozen opening pair, contact_map draws live", async ({ page }) => {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  await page.goto(injectedBundleUrl(COMPUTE_MANIFEST));

  const gc = tile(page, "viz-group-compare");
  await gc.scrollIntoViewIfNeeded();
  await expect(gc).toContainText("cluster_1 (n=220)", { timeout: 30_000 });
  await expect(gc).toContainText("cluster_2 (n=200)");
  await expect(gc).toContainText(/60 of 60 features/i);
  await expect.poll(() => plotPoints(page, "viz-group-compare"), { timeout: 30_000 }).toBe(60);

  const cm = tile(page, "viz-contact-map");
  await cm.scrollIntoViewIfNeeded();
  await expect(cm.locator(".js-plotly-plot")).toBeVisible({ timeout: 30_000 });

  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});

test("another pair is refused with the reason, never relabelled", async ({ page }) => {
  const attempts = await blockNetwork(page);
  await page.goto(injectedBundleUrl(COMPUTE_MANIFEST));
  const gc = tile(page, "viz-group-compare");
  await gc.scrollIntoViewIfNeeded();
  await expect(gc).toContainText("cluster_2 (n=200)", { timeout: 30_000 });

  // Group B → cluster_3: the frozen result does not answer it.
  await gc.getByRole("textbox", { name: "Group B" }).click();
  await page.getByRole("option", { name: "cluster_3", exact: true }).click();
  const compare = gc.getByRole("button", { name: /compare/i });
  if (await compare.isVisible().catch(() => false)) await compare.click();
  await expect(gc).toContainText(
    "This bundle holds the comparison of cluster_1 vs cluster_2",
    { timeout: 30_000 },
  );
  expect(attempts).toHaveLength(0);
});
