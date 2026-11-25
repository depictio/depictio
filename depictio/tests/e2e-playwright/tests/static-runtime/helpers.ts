/**
 * Shared setup for the backend-less static-runtime specs.
 *
 * Composes a bundle page from the built static runtime
 * (depictio/viewer/dist-static/combined-runtime.{js,css}) and a manifest
 * fixture the same way the Python producers do
 * (depictio/serverless/bundle_html.py) — `</`-escaped manifest, add-ons before
 * the runtime's script — and serves it from file://.
 */
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import type { Page, TestInfo } from "@playwright/test";
import { test } from "@playwright/test";

const REPO_ROOT = resolve(__dirname, "../../../../..");
const DIST_STATIC = join(REPO_ROOT, "depictio/viewer/dist-static");
export const RUNTIME_JS = join(DIST_STATIC, "combined-runtime.js");
const RUNTIME_CSS = join(DIST_STATIC, "combined-runtime.css");
export const FIXTURE_MANIFEST = join(
  REPO_ROOT,
  "packages/depictio-static-core/fixtures/manifest-basic.json",
);
export const PENGUINS_MANIFEST = join(
  REPO_ROOT,
  "depictio/viewer/demo/manifests/penguins.json",
);
/** Three-tab family + a filled `provenance` block. Regenerate with
 *  `packages/depictio-static-core/scripts/generate_tabs_fixture.py`. */
export const TABS_MANIFEST = join(
  REPO_ROOT,
  "packages/depictio-static-core/fixtures/manifest-tabs.json",
);

/** Protein structure demo: molecule_3d + pae_matrix + ramachandran over
 *  bundled object files, with the 3Dmol.js add-on. Regenerate with
 *  `depictio/serverless/examples/generate_demo_manifest.py`. */
export const PROTEIN_MANIFEST = join(
  REPO_ROOT,
  "depictio/viewer/demo/manifests/protein.json",
);
/** Large computes: group_compare frozen at its opening pair, contact_map live. */
export const COMPUTE_MANIFEST = join(
  REPO_ROOT,
  "depictio/viewer/demo/manifests/compute.json",
);
/** Genome browser offline: a synthetic genome's BAM (sliced to the opening
 *  locus), BED and bedGraph, with the JBrowse add-on. Regenerate with
 *  `depictio/serverless/examples/genome_demo.py`. */
export const GENOME_MANIFEST = join(
  REPO_ROOT,
  "depictio/viewer/demo/manifests/genome.json",
);
/** A frozen map that keeps its own basemap (Carto positron) beside a live
 *  card and filter. Regenerate with
 *  `depictio/serverless/examples/generate_demo_manifest.py`. */
export const MAP_MANIFEST = join(
  REPO_ROOT,
  "depictio/viewer/demo/manifests/map.json",
);
/** A GenomeSpy genome_view (bold lane titles, the hg38 gene lane) with the
 *  hg38 gene table shipped in the file. Regenerate with
 *  `depictio/serverless/examples/generate_demo_manifest.py`. */
export const GENOMESPY_MANIFEST = join(
  REPO_ROOT,
  "depictio/viewer/demo/manifests/genomespy.json",
);
const ADDONS_DIR = join(REPO_ROOT, "depictio/viewer/dist-static/addons");

/** The add-ons a manifest names, as markup — the producers' rule
 *  (depictio/serverless/addons.py::addons_html). */
export function addonsHtml(names: string[]): string {
  if (!names.length) return "";
  const registry = JSON.parse(readFileSync(join(ADDONS_DIR, "addons.json"), "utf-8")) as Record<
    string,
    { file: string }
  >;
  return names
    .map((n) => {
      const info = registry[n];
      if (!info) throw new Error(`add-on ${n} is not built (pnpm run build:static)`);
      const body = readFileSync(join(ADDONS_DIR, info.file), "utf-8");
      return `<script data-depictio-addon="${n}">${body}</script>`;
    })
    .join("");
}

export function skipUnlessBundleBuilt(): void {
  test.skip(
    !existsSync(RUNTIME_JS) || !existsSync(RUNTIME_CSS),
    "static bundle not built — run `pnpm run build:static` in depictio/viewer first",
  );
}

/** Fixture dirs this worker wrote, removed when it exits: each test writes a
 *  10-50 MB HTML file, and leaving them behind filled a dev box's disk
 *  (1700 dirs, 9.8 GB). */
const FIXTURE_DIRS: string[] = [];
process.once("exit", () => {
  for (const dir of FIXTURE_DIRS) rmSync(dir, { recursive: true, force: true });
});

/** A fresh temp dir for one fixture file, removed when the worker exits. */
export function fixtureDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  FIXTURE_DIRS.push(dir);
  return dir;
}

/** Compose the bundle page for a manifest from the built runtime (the
 *  producers' composition, depictio/serverless/bundle_html.py); returns a
 *  file:// URL. */
export function injectedBundleUrl(manifestPath: string = FIXTURE_MANIFEST): string {
  const manifest = JSON.parse(readFileSync(manifestPath, "utf-8"));
  // `</` and `<!--` cannot close or wedge open the manifest's script element.
  const blob = JSON.stringify(manifest).replace(/<\//g, "<\\/").replace(/<!--/g, "<\\u0021--");
  const names = ((manifest.addons ?? []) as { name: string }[]).map((a) => a.name);
  const html =
    '<!doctype html><html lang="en"><head><meta charset="UTF-8" />' +
    '<meta name="viewport" content="width=device-width, initial-scale=1.0" />' +
    '<meta name="color-scheme" content="light dark" />' +
    `<title>${escapeHtml(manifest.dashboard?.title || "Depictio")}</title>` +
    `<style>${readFileSync(RUNTIME_CSS, "utf-8").replace(/<\/style/gi, "<\\/style")}</style>` +
    '</head><body><div id="root"></div>' +
    `<script id="bundle-manifest" type="application/json">${blob}</script>` +
    addonsHtml(names) +
    `<script>${scriptText(readFileSync(RUNTIME_JS, "utf-8"))}</script>` +
    "</body></html>";
  const dir = fixtureDir("depictio-static-");
  const out = join(dir, "bundle-fixture.html");
  writeFileSync(out, html);
  return `file://${out}`;
}

/** A `file://` URL a bundle must never request: from a `file://` page an
 *  absolute API path (`/depictio/api/v1/...`) or an asset path
 *  (`/assets/genomes/...`, a GenomeSpy gene lane) resolves to ANOTHER
 *  `file://` URL, which a "non-file only" guard lets straight through. Such a
 *  request is an unshimmed server call in disguise. */
export function isDisguisedServerCall(url: string): boolean {
  return /^file:\/\/.*\/(depictio\/api|assets)\//.test(url);
}

/** Abort every non-file request, and every file:// request that is really a
 *  server/asset call (`isDisguisedServerCall`); returns the (live) list of
 *  attempted URLs. */
export async function blockNetwork(page: Page): Promise<string[]> {
  const attempts: string[] = [];
  const record = (url: string) => {
    if (!attempts.includes(url)) attempts.push(url);
  };
  await page.route("**/*", async (route) => {
    const url = route.request().url();
    if (url.startsWith("file://") && !isDisguisedServerCall(url)) {
      await route.continue();
    } else {
      record(url);
      await route.abort();
    }
  });
  // Chromium refuses `fetch()` of a file:// URL before routing ever sees it,
  // so a disguised API call only shows up as the console error it raises.
  page.on("console", (msg) => {
    for (const m of msg.text().matchAll(/file:\/\/[^\s'"]+/g)) {
      const url = m[0].replace(/[.,;:)]+$/, "");
      if (isDisguisedServerCall(url)) record(url);
    }
  });
  page.on("request", (req) => {
    if (isDisguisedServerCall(req.url())) record(req.url());
  });
  return attempts;
}

// ---------------------------------------------------------------------------
// A report with the runtime embedded: the report alone, or the report AND the
// dashboard in one HTML (the combined file)
// ---------------------------------------------------------------------------

/** The report skeleton: the DOM Quarto renders from the notebook generator's
 *  placeholders, for the penguins demo manifest. Regenerate with
 *  `depictio/serverless/examples/generate_report_fixture.py`. */
export const PENGUINS_REPORT = join(REPO_ROOT, "depictio/viewer/demo/reports/penguins.html");

export function skipUnlessRuntimeBuilt(): void {
  test.skip(
    !existsSync(RUNTIME_JS),
    "static runtime not built — run `pnpm run build:static` in depictio/viewer first",
  );
}

const jsonScript = (id: string, payload: unknown) =>
  `<script type="application/json" id="${id}">${JSON.stringify(payload)
    .replace(/<\//g, "<\\/")
    .replace(/<!--/g, "<\\u0021--")}</script>`;

const scriptText = (text: string) =>
  text.replace(/<\/script/g, "<\\/script").replace(/<!--/g, "<\\!--");
const escapeHtml = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** The penguins report with the runtime and the manifest inlined once at its
 *  end — the producer's composition (depictio/serverless/combined.py) for a
 *  report with no Plotly copy of its own — opened on `initialFilters`.
 *  `defaultView` makes it the combined file (the switch on, opening on that
 *  view); without it, the report alone. Returns a file:// URL. */
function runtimeReportUrl(
  initialFilters: unknown[],
  defaultView: "report" | "dashboard" | null,
  edit?: (manifest: Record<string, any>) => void,
): string {
  const manifest = JSON.parse(readFileSync(PENGUINS_MANIFEST, "utf-8"));
  manifest.initial_filters = initialFilters;
  edit?.(manifest);
  const config: Record<string, unknown> = { brand: { primary: "#228be6" } };
  if (defaultView) config.combined = { default_view: defaultView };
  const block =
    jsonScript("depictio-report-config", config) +
    jsonScript("depictio-report-manifest", manifest) +
    `<script type="text/plain" data-depictio-runtime="css">${scriptText(
      readFileSync(RUNTIME_CSS, "utf-8"),
    )}</script>` +
    `<script data-depictio-runtime="js">${scriptText(readFileSync(RUNTIME_JS, "utf-8"))}</script>`;
  const html = readFileSync(PENGUINS_REPORT, "utf-8").replace(
    "<!--DEPICTIO_REPORT_RUNTIME-->",
    () => block,
  );
  const dir = fixtureDir(defaultView ? "depictio-combined-" : "depictio-report-");
  const out = join(dir, defaultView ? "combined-fixture.html" : "report-fixture.html");
  writeFileSync(out, html);
  return `file://${out}`;
}

/** The report alone (no "Report | Dashboard" switch); `edit` changes the
 *  manifest first. */
export function reportUrl(
  initialFilters: unknown[] = [],
  edit?: (manifest: Record<string, any>) => void,
): string {
  return runtimeReportUrl(initialFilters, null, edit);
}

/** The combined file, opening on `defaultView` when its link names none. */
export function combinedUrl(
  initialFilters: unknown[] = [],
  defaultView: "report" | "dashboard" = "report",
): string {
  return runtimeReportUrl(initialFilters, defaultView);
}
