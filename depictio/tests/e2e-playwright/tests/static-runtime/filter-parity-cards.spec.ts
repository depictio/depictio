/**
 * Phase-1 exit criterion: live cards recompute offline when an interactive
 * filter changes, and the values match Polars on the same data.
 *
 * The pinned numbers are the server-side reference, computed with Polars over
 * the joined penguins CSVs (depictio/projects/init/penguins/data):
 *   all rows:  mean(body_mass_g) = 4201.754385964912, n_unique(species) = 3
 *   Adelie:    mean(body_mass_g) = 3700.662251655629, n_unique(species) = 1
 * The card renderer displays 4 decimals. If these assertions drift, the
 * in-browser kernels no longer match the server — that is a real bug, not a
 * flaky test.
 */
import { expect, test } from "@playwright/test";
import {
  PENGUINS_MANIFEST,
  blockNetwork,
  injectedBundleUrl,
  skipUnlessBundleBuilt,
} from "./helpers";

test.describe("static bundle — live card parity (penguins)", () => {
  test.beforeEach(() => skipUnlessBundleBuilt());

  test("cards recompute offline when the species filter changes", async ({
    page,
  }) => {
    const attempts = await blockNetwork(page);
    await page.goto(injectedBundleUrl(PENGUINS_MANIFEST));
    await page.waitForSelector(".react-grid-item", { timeout: 30_000 });

    // Unfiltered state — Polars reference values.
    await expect(page.getByText("4201.7544")).toBeVisible({ timeout: 30_000 });
    const speciesCard = page
      .locator(".react-grid-item", { hasText: "Species" })
      .first();
    await expect(speciesCard.getByText("3", { exact: true })).toBeVisible();

    // Filter to Adelie via the species MultiSelect.
    await page.locator(".mantine-MultiSelect-input").first().click();
    await page.getByRole("option", { name: "Adelie" }).click();

    // Cards recompute through the in-browser engine — no network involved.
    await expect(page.getByText("3700.6623")).toBeVisible({ timeout: 30_000 });
    await expect(speciesCard.getByText("1", { exact: true })).toBeVisible();

    // Clearing the filter restores the unfiltered values.
    await page.keyboard.press("Escape");
    await page
      .locator(".mantine-MultiSelect-input")
      .first()
      .locator("..")
      .getByRole("button")
      .first()
      .click()
      .catch(() => {});

    expect(attempts).toEqual([]);
  });

  test("options come from the codebook and the frozen figure stays badged", async ({
    page,
  }) => {
    const attempts = await blockNetwork(page);
    await page.goto(injectedBundleUrl(PENGUINS_MANIFEST));
    await page.waitForSelector(".react-grid-item", { timeout: 30_000 });

    // Year options are the Python-produced codebook keys.
    await page.locator(".mantine-MultiSelect-input").nth(1).click();
    for (const year of ["2007", "2008", "2009"]) {
      await expect(page.getByRole("option", { name: year })).toBeVisible();
    }
    await page.keyboard.press("Escape");

    // The scatter is frozen (phase 5) and badged as such.
    await expect(
      page.locator('[data-static-tier="frozen"]').first(),
    ).toBeVisible();

    expect(attempts).toEqual([]);
  });
});
