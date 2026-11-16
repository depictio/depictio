/**
 * Shared setup for the backend-less static-runtime specs.
 *
 * Injects a manifest fixture into the built single-file bundle
 * (depictio/viewer/dist-static/static.html) the same way the Python producers
 * do — token replacement with `</`-escaping — and serves it from file://.
 */
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import type { Page, TestInfo } from "@playwright/test";
import { test } from "@playwright/test";

const REPO_ROOT = resolve(__dirname, "../../../../..");
export const BUNDLE_TEMPLATE = join(
  REPO_ROOT,
  "depictio/viewer/dist-static/static.html",
);
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
const ADDONS_DIR = join(REPO_ROOT, "depictio/viewer/dist-static/addons");

/** Append the add-ons a manifest names before `</body>` — the producers' rule
 *  (depictio/serverless/addons.py::apply_addons). */
export function applyAddons(template: string, names: string[]): string {
  if (!names.length) return template;
  const registry = JSON.parse(readFileSync(join(ADDONS_DIR, "addons.json"), "utf-8")) as Record<
    string,
    { file: string }
  >;
  const scripts = names
    .map((n) => {
      const info = registry[n];
      if (!info) throw new Error(`add-on ${n} is not built (pnpm run build:static)`);
      const body = readFileSync(join(ADDONS_DIR, info.file), "utf-8");
      return `<script data-depictio-addon="${n}">${body}</script>`;
    })
    .join("");
  const at = template.lastIndexOf("</body>");
  return at < 0 ? template + scripts : template.slice(0, at) + scripts + template.slice(at);
}

export function skipUnlessBundleBuilt(): void {
  test.skip(
    !existsSync(BUNDLE_TEMPLATE),
    "static bundle not built — run `pnpm run build:static` in depictio/viewer first",
  );
}

/** Inject a manifest into the built bundle; returns a file:// URL. */
export function injectedBundleUrl(manifestPath: string = FIXTURE_MANIFEST): string {
  const template = readFileSync(BUNDLE_TEMPLATE, "utf-8");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf-8"));
  // Same convention as depictio/catalog/payload.py::_inject. replaceAll +
  // a function replacement: a plain string replacement would interpret `$`
  // sequences in the JSON, and Python's .replace (which producers use)
  // replaces every occurrence.
  const blob = JSON.stringify(manifest).replace(/<\//g, "<\\/");
  const names = ((manifest.addons ?? []) as { name: string }[]).map((a) => a.name);
  const html = applyAddons(template, names).replaceAll("__BUNDLE_MANIFEST__", () => blob);
  const dir = mkdtempSync(join(tmpdir(), "depictio-static-"));
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
// The report host: the same runtime mounted into a report's tiles
// ---------------------------------------------------------------------------

const DIST_STATIC = join(REPO_ROOT, "depictio/viewer/dist-static");
export const REPORT_RUNTIME_JS = join(DIST_STATIC, "report-runtime.js");
/** The report skeleton: the DOM Quarto renders from the notebook generator's
 *  placeholders, for the penguins demo manifest. Regenerate with
 *  `depictio/serverless/examples/generate_report_fixture.py`. */
export const PENGUINS_REPORT = join(REPO_ROOT, "depictio/viewer/demo/reports/penguins.html");

export function skipUnlessReportRuntimeBuilt(): void {
  test.skip(
    !existsSync(REPORT_RUNTIME_JS),
    "report runtime not built — run `pnpm run build:static` in depictio/viewer first",
  );
}

const jsonScript = (id: string, payload: unknown) =>
  `<script type="application/json" id="${id}">${JSON.stringify(payload)
    .replace(/<\//g, "<\\/")
    .replace(/<!--/g, "<\\u0021--")}</script>`;

/** The penguins report with the runtime and the manifest inlined once at its
 *  end — the producer's block (depictio/notebook/report_runtime.py) — opened
 *  on `initialFilters`. Returns a file:// URL. */
export function reportUrl(initialFilters: unknown[] = []): string {
  const manifest = JSON.parse(readFileSync(PENGUINS_MANIFEST, "utf-8"));
  manifest.initial_filters = initialFilters;
  const js = readFileSync(REPORT_RUNTIME_JS, "utf-8")
    .replace(/<\/script/g, "<\\/script")
    .replace(/<!--/g, "<\\!--");
  const css = readFileSync(join(DIST_STATIC, "report-runtime.css"), "utf-8");
  const block =
    `<style data-depictio-report-runtime="css">${css}</style>` +
    jsonScript("depictio-report-config", { brand: { primary: "#228be6" } }) +
    jsonScript("depictio-report-manifest", manifest) +
    `<script data-depictio-report-runtime="js">${js}</script>`;
  const html = readFileSync(PENGUINS_REPORT, "utf-8").replace(
    "<!--DEPICTIO_REPORT_RUNTIME-->",
    () => block,
  );
  const dir = mkdtempSync(join(tmpdir(), "depictio-report-"));
  const out = join(dir, "report-fixture.html");
  writeFileSync(out, html);
  return `file://${out}`;
}
