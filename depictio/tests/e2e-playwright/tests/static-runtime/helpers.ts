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
  const html = template.replaceAll("__BUNDLE_MANIFEST__", () => blob);
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
