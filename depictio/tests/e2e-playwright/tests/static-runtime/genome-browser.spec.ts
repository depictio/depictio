/**
 * The genome browser offline: the real JBrowse view, drawn from files the
 * producer shipped inside the HTML (depictio/serverless/jbrowse_bundle.py),
 * with JBrowse itself from the conditional `jbrowse` add-on.
 *
 * The demo manifest (depictio/serverless/examples/genome_demo.py) holds a
 * synthetic two-contig genome: the FASTA and its index whole, a plain BED and
 * bedGraph whole, and a BAM sliced to the opening locus — its header page and
 * the one page of reads the index points to for ctgA:150,001-150,600, not the
 * page in between. Every read goes through the runtime's fetch shim; the
 * network is blocked.
 */
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

import { GENOME_MANIFEST, blockNetwork, injectedBundleUrl, skipUnlessBundleBuilt } from "./helpers";

test.beforeEach(() => skipUnlessBundleBuilt());

const TILE = '[data-component-id="genome-browser"]';
const ORIGIN = "https://bundle.depictio.invalid/jbrowse/";

interface FileEntry {
  label: string;
  size: number;
  pages: [number, number][] | null;
}

function bundleOf(manifest: Record<string, any>) {
  return manifest.frozen["genome-browser"].payload.bundle as {
    renderable: boolean;
    files: Record<string, FileEntry>;
    omitted: unknown[];
  };
}

test("the manifest ships the session's files, the BAM sliced, and the jbrowse add-on", () => {
  const m = JSON.parse(readFileSync(GENOME_MANIFEST, "utf-8"));
  const b = bundleOf(m);
  expect(b.renderable).toBe(true);
  expect(b.omitted).toEqual([]);
  const byLabel = Object.fromEntries(Object.values(b.files).map((f) => [f.label, f]));
  expect(Object.keys(byLabel).sort()).toEqual([
    "coverage.bedgraph",
    "demo.fa",
    "demo.fa.fai",
    "genes.bed",
    "reads.bam",
    "reads.bam.bai",
  ]);
  // The reads: the header page and the locus' page, not the one in between.
  expect(byLabel["reads.bam"].pages).toEqual([
    [0, 1],
    [2, 1],
  ]);
  expect(byLabel["genes.bed"].pages).toBeNull();
  expect((m.addons as { name: string }[]).map((a) => a.name)).toEqual(["jbrowse"]);
  // Every location of the session points at the bundle, none at an API.
  const session = JSON.stringify(m.frozen["genome-browser"].payload.tracks);
  expect(session).not.toMatch(/demo:\/\/|\/depictio\/api\//);
  expect(m.tiers["genome-browser"].detail).toMatch(/renders offline from 3 of 3 track/);
});

async function trackRendered(page: Page, trackId: string) {
  const track = page.locator(`${TILE} [data-testid^="trackRenderingContainer-"][data-testid$="-${trackId}"]`);
  await expect(track).toBeVisible({ timeout: 60_000 });
  return track;
}

test("JBrowse draws the bundled tracks with no network", async ({ page }, testInfo) => {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));

  await page.goto(injectedBundleUrl(GENOME_MANIFEST));
  const tile = page.locator(TILE);
  await expect(tile).toBeVisible({ timeout: 30_000 });
  await tile.scrollIntoViewIfNeeded();

  // The real browser, not the session table fallback.
  await expect(tile.locator('[data-testid="jbrowse-snapshot"]')).toHaveCount(0);
  expect(
    await page.evaluate(() => typeof (window as unknown as Record<string, unknown>).__depictioJBrowseVendor),
  ).toBe("function");

  for (const id of ["demo-genes", "demo-coverage", "demo-reads"]) {
    const track = await trackRendered(page, id);
    await expect(track.locator("canvas, svg").first()).toBeVisible({ timeout: 60_000 });
  }
  // The genes inside the locus are laid out by name (BED shipped whole).
  await expect(tile.getByText("geneBeta").first()).toBeVisible({ timeout: 60_000 });
  // No track ended in an error, and nothing is still loading.
  await expect(tile.getByText(/Error|outside the region/i)).toHaveCount(0);
  await expect(tile.locator('[data-testid="loading-overlay"], [data-testid="loading"]')).toHaveCount(0, {
    timeout: 60_000,
  });

  await page.screenshot({ path: testInfo.outputPath("genome-browser.png"), fullPage: true });
  await tile.screenshot({ path: testInfo.outputPath("genome-browser-tile.png") });
  expect(attempts).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test("a read outside the shipped pages is refused with the region it holds", async ({ page }) => {
  await blockNetwork(page);
  await page.goto(injectedBundleUrl(GENOME_MANIFEST));
  await expect(page.locator(TILE)).toBeVisible({ timeout: 30_000 });
  await trackRendered(page, "demo-reads");
  const m = JSON.parse(readFileSync(GENOME_MANIFEST, "utf-8"));
  const [key] = Object.entries(bundleOf(m).files).find(([, f]) => f.label === "reads.bam")!;
  const outcome = await page.evaluate(
    async ({ url }) => {
      const page1 = `bytes=${256 * 1024}-${512 * 1024 - 1}`;
      const page2 = `bytes=${512 * 1024}-${768 * 1024 - 1}`;
      const ok = await fetch(url, { headers: { range: page2 } });
      let refused = "";
      try {
        await fetch(url, { headers: { range: page1 } });
      } catch (err) {
        refused = String(err);
      }
      return { status: ok.status, range: ok.headers.get("content-range"), refused };
    },
    { url: ORIGIN + key },
  );
  expect(outcome.status).toBe(206);
  expect(outcome.range).toMatch(/^bytes 524288-\d+\/\d+$/);
  expect(outcome.refused).toMatch(/outside the region this offline bundle ships.*ctgA:149,401-151,200/);
});

/** The demo manifest, altered, injected from a temp file. */
async function variantUrl(edit: (m: Record<string, any>) => void): Promise<string> {
  const m = JSON.parse(readFileSync(GENOME_MANIFEST, "utf-8"));
  edit(m);
  const { writeFileSync, mkdtempSync } = await import("node:fs");
  const { join } = await import("node:path");
  const { tmpdir } = await import("node:os");
  const path = join(mkdtempSync(join(tmpdir(), "genome-variant-")), "m.json");
  writeFileSync(path, JSON.stringify(m));
  return injectedBundleUrl(path);
}

test("without the add-on the tile falls back to the session table, saying why", async ({ page }) => {
  const attempts = await blockNetwork(page);
  await page.goto(await variantUrl((m) => (m.addons = [])));
  const table = page.locator(`${TILE} [data-testid="jbrowse-snapshot"]`);
  await expect(table).toBeVisible({ timeout: 30_000 });
  await expect(table).toContainText("built without the genome browser add-on");
  await expect(table).toContainText("Reads");
  expect(attempts).toEqual([]);
});

test("a session the producer could not ship shows its table with the producer's reason", async ({
  page,
}) => {
  await blockNetwork(page);
  const url = await variantUrl((m) => {
    const b = m.frozen["genome-browser"].payload.bundle;
    b.renderable = false;
    b.reason = "reference sequence unreadable (host not allow-listed)";
  });
  await page.goto(url);
  const table = page.locator(`${TILE} [data-testid="jbrowse-snapshot"]`);
  await expect(table).toBeVisible({ timeout: 30_000 });
  await expect(table).toContainText("host not allow-listed");
});
