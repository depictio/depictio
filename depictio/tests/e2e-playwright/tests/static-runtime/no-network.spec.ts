/**
 * The static bundle must render fully offline: file:// origin, every non-file
 * request blocked, zero network attempts, zero page errors.
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
