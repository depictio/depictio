/**
 * The static bundle must render fully offline: file:// origin, every non-file
 * request blocked, zero network attempts, zero page errors.
 *
 * Second test: the same rule one click deep. The export modal's opener sits
 * in the Settings drawer, a surface a reader CAN open inside a bundle; its
 * `isStaticBundle` guard keeps it shut (and the four export calls are shimmed
 * to refuse all the same — scripts/check-static-shim.mjs gates the whole
 * shim surface).
 *
 * Third test: the guard itself. From a `file://` page `/depictio/api/...`
 * resolves to another `file://` URL, which a non-file-only guard would wave
 * through; `blockNetwork` must record it.
 */
import { expect, test } from "@playwright/test";

import { blockNetwork, injectedBundleUrl, skipUnlessBundleBuilt } from "./helpers";

test.beforeEach(() => skipUnlessBundleBuilt());

test("renders the fixture dashboard with no network at all", async ({ page }) => {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));

  await page.goto(injectedBundleUrl());

  // The real viewer App mounted with the manifest's dashboard.
  await expect(page).toHaveTitle(/Fixture: basic/);
  await expect(page.locator(".react-grid-item")).toHaveCount(3);

  // Frozen payloads rendered through the real renderers.
  await expect(page.getByText("43.92")).toBeVisible(); // card value
  await expect(page.getByText("A hand-written fixture manifest")).toBeVisible(); // text body
  await expect(page.getByText("Fixture scatter")).toBeVisible(); // figure title

  // The point of the exercise: nothing left the page.
  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});

test("the settings drawer offers no export action inside a bundle", async ({ page }) => {
  const attempts = await blockNetwork(page);
  await page.goto(injectedBundleUrl());
  await expect(page.locator(".react-grid-item")).toHaveCount(3);

  // The Settings gear is NOT static-gated (unlike Edit), so the drawer opens
  // here exactly as it does on a server.
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const drawer = page.getByRole("dialog").filter({ hasText: "Dashboard settings" });
  await expect(drawer).toBeVisible();

  // Absent, not merely disabled — the opposite of the server-side non-owner
  // rule (tests/export/export-static.spec.ts asserts the disabled button
  // there). A bundle has no backend to build a new export from, so there is no
  // affordance to keep discoverable, and rendering one would put the four
  // unshimmed export calls back within reach.
  await expect(page.locator("[data-testid='settings-nav-export']")).toHaveCount(0);
  await expect(page.locator("[data-testid='export-static-btn']")).toHaveCount(0);
  // Opening the drawer is itself a shim surface (fetchProject); it must not
  // reach for the network either.
  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
});

test("the offline guard catches an API call disguised as a file:// URL", async ({ page }) => {
  const attempts = await blockNetwork(page);
  await page.goto(injectedBundleUrl());
  await expect(page.locator(".react-grid-item")).toHaveCount(3);
  await page.evaluate(async () => {
    await fetch("/depictio/api/v1/dashboards/get/x").catch(() => null);
    await fetch("/assets/genomes/hg38.genes.json").catch(() => null);
  });
  expect(attempts.some((u) => u.startsWith("file://") && u.includes("/depictio/api/v1/"))).toBe(true);
  expect(attempts.some((u) => u.startsWith("file://") && u.includes("/assets/genomes/"))).toBe(true);
});
