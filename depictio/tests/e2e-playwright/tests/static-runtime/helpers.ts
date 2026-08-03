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

export function skipUnlessBundleBuilt(): void {
  test.skip(
    !existsSync(BUNDLE_TEMPLATE),
    "static bundle not built — run `pnpm run build:static` in depictio/viewer first",
  );
}

/** Inject the fixture manifest into the built bundle; returns a file:// URL. */
export function injectedBundleUrl(): string {
  const template = readFileSync(BUNDLE_TEMPLATE, "utf-8");
  const manifest = JSON.parse(readFileSync(FIXTURE_MANIFEST, "utf-8"));
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

/** Abort every non-file request; returns the (live) list of attempted URLs. */
export async function blockNetwork(page: Page): Promise<string[]> {
  const attempts: string[] = [];
  await page.route("**/*", async (route) => {
    const url = route.request().url();
    if (url.startsWith("file://")) {
      await route.continue();
    } else {
      attempts.push(url);
      await route.abort();
    }
  });
  return attempts;
}
