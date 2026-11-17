/**
 * GenomeSpy tiles make no request a bundle cannot answer.
 *
 * A live genome view reaches the network twice, and an advanced-viz bundle
 * did both offline: GenomeSpy fetches any font other than the one it embeds
 * (a bold lane title sent it to raw.githubusercontent.com for Lato's
 * METADATA.pb), and the gene lane fetches `assets/genomes/<assembly>.genes.json`
 * from the app's base URL, a file:// request from a bundle. The runtime now
 * draws every label in the embedded font and reads the gene table the
 * producer shipped (`inline_blobs["genes_hg38"]`).
 */
import { expect, test } from "@playwright/test";

import { GENOMESPY_MANIFEST, blockNetwork, injectedBundleUrl, skipUnlessBundleBuilt } from "./helpers";

test.beforeEach(() => skipUnlessBundleBuilt());

test("a genome view with lane titles and a gene lane draws with zero network", async ({ page }) => {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));

  await page.goto(injectedBundleUrl(GENOMESPY_MANIFEST));
  const tile = page.locator(".react-grid-item", { hasText: "ChIP-seq depth over the genes" }).first();
  await expect(tile).toBeVisible();
  await expect(tile.locator("canvas").first()).toBeVisible({ timeout: 30_000 });

  // The gene search is offered only once a gene table loaded: the shipped one.
  await expect(tile.getByText("Locus or gene")).toBeVisible({ timeout: 20_000 });

  // Fonts load lazily, after the first frame: give GenomeSpy the time it took
  // to reach GitHub before.
  await page.waitForTimeout(3000);
  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});

test("the shipped gene table is the one the server serves, compressed", async () => {
  const { readFileSync } = await import("node:fs");
  const { gunzipSync } = await import("node:zlib");
  const { join } = await import("node:path");
  const manifest = JSON.parse(readFileSync(GENOMESPY_MANIFEST, "utf-8"));
  const blob = manifest.inline_blobs?.genes_hg38 as string | undefined;
  expect(blob, "inline_blobs.genes_hg38").toBeTruthy();
  const shipped = gunzipSync(Buffer.from(blob!, "base64"));
  const served = readFileSync(
    join(__dirname, "../../../../viewer/public/assets/genomes/hg38.genes.json"),
  );
  expect(shipped.equals(served)).toBe(true);
});
