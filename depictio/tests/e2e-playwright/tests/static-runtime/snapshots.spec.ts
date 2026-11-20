/**
 * Zero omitted tiles (RFC §13): components that need the server at view time
 * still RENDER from an export-time snapshot.
 *
 *   - an image gallery ships thumbnails of its default rows (producer A reads
 *     them from S3 and downsamples them); the shim hands the renderer `blob:`
 *     URLs, which it uses as is;
 *   - a JBrowse tile shows its export-time session (assembly, locus, track
 *     table) instead of a blank stub.
 *
 * The manifest is the basic fixture plus the two components, with the payload
 * shapes producer A writes (`_freeze_image`, `_freeze_jbrowse`).
 */
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

import { FIXTURE_MANIFEST, blockNetwork, injectedBundleUrl, skipUnlessBundleBuilt } from "./helpers";

test.beforeEach(() => skipUnlessBundleBuilt());

// A 2 x 2 PNG.
const PNG =
  "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP4z8AARAwQCgAf7gP9i18U1AAAAABJRU5ErkJggg==";

function manifestPath(): string {
  const m = JSON.parse(readFileSync(FIXTURE_MANIFEST, "utf-8"));
  const doc = m.dashboard.doc;
  doc.stored_metadata.push(
    {
      index: "comp-image-1",
      component_type: "image",
      title: "Cells",
      wf_id: "wf-images",
      dc_id: "dc00000000000000000000a1",
      image_column: "img",
      s3_base_folder: "s3://depictio-bucket/cells/",
    },
    { index: "comp-jbrowse-1", component_type: "jbrowse", title: "Genome browser" },
  );
  m.tiers["comp-image-1"] = { tier: "frozen", reason: "image", detail: "export-time snapshot" };
  m.tiers["comp-jbrowse-1"] = { tier: "frozen", reason: "jbrowse", detail: "export-time session" };
  m.inline_blobs.obj_cell1 = PNG;
  m.frozen["comp-image-1"] = {
    kind: "image",
    filter_state: [],
    payload: {
      rows: [{ img: "inline:obj_cell1", cell_id: "c1" }],
      image_column: "img",
      sort_by: null,
      sort_dir: "desc",
      sortable_columns: ["cell_id"],
      paths: ["inline:obj_cell1"],
      filter_applied: false,
      filter_count: 0,
    },
  };
  m.frozen["comp-jbrowse-1"] = {
    kind: "jbrowse",
    filter_state: [],
    payload: {
      assembly: { name: "hg38" },
      tracks: [],
      shown_track_ids: ["t1"],
      location: "chr1:10,000-20,000",
      view: {},
      configuration: {},
      track_rows: [
        { track_id: "t1", name: "H3K27ac", format: "bigwig", sample: "S1", selection_value: null },
        { track_id: "t2", name: "Input", format: "bigwig", sample: "S1", selection_value: null },
      ],
      selection_column: null,
      tracks_dc_id: "dc-tracks",
      filter_applied: false,
      total_tracks: 2,
      matched_tracks: 2,
      truncated: false,
    },
  };
  const out = join(mkdtempSync(join(tmpdir(), "snapshots-")), "m.json");
  writeFileSync(out, JSON.stringify(m));
  return out;
}

test("an image gallery and a genome browser render their export-time snapshots", async ({
  page,
}) => {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  await page.goto(injectedBundleUrl(manifestPath()));

  const gallery = page.locator('[data-component-id="comp-image-1"]');
  await gallery.scrollIntoViewIfNeeded();
  const img = gallery.locator("img").first();
  await expect(img).toBeVisible({ timeout: 30_000 });
  expect(await img.getAttribute("src")).toMatch(/^blob:/);
  await expect.poll(() => img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBe(2);

  const jb = page.locator('[data-component-id="comp-jbrowse-1"]');
  await jb.scrollIntoViewIfNeeded();
  await expect(jb.getByTestId("jbrowse-snapshot")).toBeVisible({ timeout: 30_000 });
  await expect(jb).toContainText("hg38");
  await expect(jb).toContainText("chr1:10,000-20,000");
  await expect(jb).toContainText("H3K27ac");

  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});

/** A UMAP (no browser can rerun it) keeps its export-time coordinates and
 *  drops the points the filters exclude, matched on its sample column. */
test("a frozen UMAP follows the filters by dropping points", async ({ page }) => {
  const { PENGUINS_MANIFEST } = await import("./helpers");
  const m = JSON.parse(readFileSync(PENGUINS_MANIFEST, "utf-8"));
  const dcId = "e26f036c4d124f11b2f23fd8";
  const ids: string[] = [];
  for (const run of ["run_1_adelie", "run_2_chinstrap", "run_3_gentoo"]) {
    const csv = readFileSync(
      join(__dirname, "../../../../projects/init/penguins/data", run, "demographic_data.csv"),
      "utf-8",
    );
    for (const line of csv.trim().split("\n").slice(1)) ids.push(line.split(",")[0]);
  }
  m.dashboard.doc.stored_metadata.push({
    index: "emb-umap",
    component_type: "advanced_viz",
    viz_kind: "embedding",
    title: "UMAP (frozen)",
    wf_id: "d294bc6d698b0ce731cb0758",
    dc_id: dcId,
    config: {
      viz_kind: "embedding",
      compute_method: "umap",
      sample_id_col: "individual_id",
      dim_1_col: "dim_1",
      dim_2_col: "dim_2",
    },
  });
  m.tiers["emb-umap"] = { tier: "frozen", reason: "celery_compute", detail: "frozen UMAP" };
  m.frozen["emb-umap"] = {
    kind: "compute",
    filter_state: [],
    payload: {
      result: { sample_ids: ids, dim_1: ids.map((_, i) => i), dim_2: ids.map((_, i) => -i) },
    },
  };
  const path = join(mkdtempSync(join(tmpdir(), "umap-")), "m.json");
  writeFileSync(path, JSON.stringify(m));

  const attempts = await blockNetwork(page);
  await page.goto(injectedBundleUrl(path));
  const tile = page.locator('[data-component-id="emb-umap"]');
  await tile.scrollIntoViewIfNeeded();
  const points = () =>
    page.evaluate(() => {
      const el = document.querySelector('[data-component-id="emb-umap"] .js-plotly-plot') as unknown as {
        data?: { x?: unknown[] }[];
      } | null;
      return (el?.data ?? []).reduce((n, t) => n + (Array.isArray(t.x) ? t.x.length : 0), 0);
    });
  await expect.poll(points, { timeout: 30_000 }).toBe(ids.length);
  await page.locator(".mantine-MultiSelect-input").first().click();
  await page.getByRole("option", { name: "Adelie", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect.poll(points, { timeout: 30_000 }).toBe(151);
  expect(attempts).toHaveLength(0);
});
