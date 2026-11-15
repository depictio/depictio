/**
 * The optional Python runtime (Pyodide 314.0.7, RFC §13.6), offline.
 *
 * The bundle is built by producer B with `python_runtime="on"`
 * (`python -m depictio.serverless.pyodide.demo`, a CI step of its own: it
 * carries ~70 MB of verified Pyodide assets, so it is not a committed
 * manifest). Three tiles TypeScript cannot reproduce run the server's own
 * Python in the page:
 *
 *   - a code-mode figure the transpiler refuses, re-run in the server's
 *     RestrictedPython sandbox on every species pick;
 *   - a group comparison, any pair (`group_compare_from_frame`);
 *   - a PCA embedding (`_embedding_result_from_frame`).
 *
 * Zero network with the runtime booted: every Pyodide file is served from
 * the page itself.
 */
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

import { blockNetwork } from "./helpers";

const DEMO = join(
  resolve(__dirname, "../../../../.."),
  "depictio/viewer/dist-static/site/demo-python-runtime.html",
);

test.skip(!existsSync(DEMO), "Python-runtime demo not built (python -m depictio.serverless.pyodide.demo)");
// Booting Pyodide and importing polars + scipy + plotly takes ~8 s headless.
test.setTimeout(180_000);

function tile(page: Page, id: string) {
  return page.locator(`[data-component-id="${id}"]`);
}

async function traceCount(page: Page, id: string): Promise<number> {
  return page.evaluate((cid) => {
    const el = document.querySelector(`[data-component-id="${cid}"] .js-plotly-plot`) as unknown as {
      data?: unknown[];
    } | null;
    return el?.data?.length ?? -1;
  }, id);
}

async function pointCount(page: Page, id: string): Promise<number> {
  return page.evaluate((cid) => {
    const el = document.querySelector(`[data-component-id="${cid}"] .js-plotly-plot`) as unknown as {
      data?: { x?: unknown[] }[];
    } | null;
    return (el?.data ?? []).reduce((n, t) => n + (Array.isArray(t.x) ? t.x.length : 0), 0);
  }, id);
}

test("three tiles run the server's Python in the page, zero network", async ({ page }) => {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  await page.goto(`file://${DEMO}`);
  await expect(page.locator(".react-grid-item").first()).toBeVisible();
  for (const id of ["figure-python-code", "viz-group-compare-py", "viz-pca-py"]) {
    await tile(page, id).scrollIntoViewIfNeeded();
  }

  // The runtime booted (timings recorded by runtime.ts).
  await expect
    .poll(() => page.evaluate(() => window.__DEPICTIO_PYODIDE__?.version ?? null), { timeout: 120_000 })
    .toBe("314.0.7");

  // Code figure: one box trace per species, built by the author's code.
  await expect.poll(() => traceCount(page, "figure-python-code"), { timeout: 60_000 }).toBe(3);
  // Group comparison and PCA computed in Python.
  const gc = tile(page, "viz-group-compare-py");
  await expect(gc).toContainText("cluster_1 (n=220)", { timeout: 60_000 });
  await expect.poll(() => pointCount(page, "viz-pca-py"), { timeout: 60_000 }).toBe(90);

  // A filter re-runs the code: Adelie only → one trace.
  await page.locator(".mantine-MultiSelect-input").first().click();
  await page.getByRole("option", { name: "Adelie", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect.poll(() => traceCount(page, "figure-python-code"), { timeout: 60_000 }).toBe(1);

  // Any pair: B → cluster_3 is computed, not refused.
  await gc.getByRole("textbox", { name: "Group B" }).click();
  await page.getByRole("option", { name: "cluster_3", exact: true }).click();
  await expect(gc).toContainText(/cluster_3 \(n=\d+\)/, { timeout: 60_000 });

  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});
