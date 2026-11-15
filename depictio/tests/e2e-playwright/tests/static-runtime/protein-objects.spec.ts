/**
 * Protein kinds offline: molecule_3d, pae_matrix and ramachandran draw from
 * object files (a PDB structure, a PAE matrix) the producer read at build time
 * and shipped inside the HTML. The runtime answers the tiles' manifest read
 * (`GET /files/indexed/{dc_id}`) from `BundleManifest.objects` with `blob:`
 * URLs, so the renderers' own download path runs; 3Dmol.js is the conditional
 * add-on the producer appended because the bundle holds a molecule_3d tile.
 *
 * Reference values, from the showcase files the demo is built from
 * (depictio/projects/init/advanced_viz_showcase/data/): demo_protein.pdb has
 * 172 residues in chain A; the PAE matrix is 172 x 172.
 */
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

import {
  PROTEIN_MANIFEST,
  blockNetwork,
  injectedBundleUrl,
  skipUnlessBundleBuilt,
} from "./helpers";

test.beforeEach(() => skipUnlessBundleBuilt());

async function scrollAllIntoView(page: Page) {
  const items = page.locator(".react-grid-item");
  const count = await items.count();
  for (let i = 0; i < count; i++) await items.nth(i).scrollIntoViewIfNeeded();
}

function tile(page: Page, id: string) {
  return page.locator(`[data-component-id="${id}"]`);
}

test("the manifest ships the structure and PAE files and the 3Dmol add-on", () => {
  const m = JSON.parse(readFileSync(PROTEIN_MANIFEST, "utf-8"));
  const files = Object.values(m.objects as Record<string, { files: { name: string }[] }>)
    .flatMap((c) => c.files.map((f) => f.name))
    .sort();
  expect(files).toEqual(["demo_protein.pae.tsv", "demo_protein.pdb"]);
  expect((m.addons as { name: string }[]).map((a) => a.name)).toEqual(["3dmol"]);
  for (const id of ["viz-structure", "viz-pae", "viz-ramachandran"]) {
    expect(m.tiers[id].tier).toBe("live");
  }
});

test("structure, PAE and Ramachandran render from bundled files, no network", async ({ page }) => {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));

  await page.goto(injectedBundleUrl(PROTEIN_MANIFEST));
  await expect(page.locator(".react-grid-item").first()).toBeVisible();
  await scrollAllIntoView(page);

  // 3Dmol.js came from the add-on, not from a stub.
  expect(await page.evaluate(() => typeof (window as unknown as Record<string, unknown>)["3Dmol"])).toBe(
    "object",
  );

  // molecule_3d: a WebGL canvas inside the tile, no "unavailable" empty state.
  await tile(page, "viz-structure").scrollIntoViewIfNeeded();
  await expect(tile(page, "viz-structure").locator("canvas").first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(tile(page, "viz-structure")).not.toContainText(/unavailable|not in the bundle/i);

  // pae_matrix: the matrix is painted on a canvas.
  await tile(page, "viz-pae").scrollIntoViewIfNeeded();
  await expect(tile(page, "viz-pae").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  await expect(tile(page, "viz-pae")).not.toContainText(/unavailable|not in the bundle/i);

  // ramachandran: one marker per residue with both torsions (the two chain
  // ends have one each), read off the mounted Plotly graph.
  await tile(page, "viz-ramachandran").scrollIntoViewIfNeeded();
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const el = document.querySelector(
            '[data-component-id="viz-ramachandran"] .js-plotly-plot',
          ) as unknown as { data?: { x?: unknown[] }[] } | null;
          return (el?.data ?? []).reduce((n, t) => n + (Array.isArray(t.x) ? t.x.length : 0), 0);
        }),
      { timeout: 30_000 },
    )
    .toBeGreaterThan(150);

  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});

test("without the add-on the structure tile says so and the other two still draw", async ({
  page,
}) => {
  const attempts = await blockNetwork(page);
  const m = JSON.parse(readFileSync(PROTEIN_MANIFEST, "utf-8"));
  m.addons = [];
  const { writeFileSync, mkdtempSync } = await import("node:fs");
  const { join } = await import("node:path");
  const { tmpdir } = await import("node:os");
  const path = join(mkdtempSync(join(tmpdir(), "protein-noaddon-")), "m.json");
  writeFileSync(path, JSON.stringify(m));
  await page.goto(injectedBundleUrl(path));
  await scrollAllIntoView(page);
  await expect(tile(page, "viz-structure")).toContainText(/unavailable/i, { timeout: 30_000 });
  await expect(tile(page, "viz-pae").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  expect(attempts).toHaveLength(0);
});
