/**
 * Phase-3 exit criterion: the table component is LIVE in a static bundle —
 * AG Grid pages, header-click sorting and filter narrowing all recompute
 * offline through the in-browser sortSlice kernel, with zero network.
 *
 * Pinned reference values, computed with Polars 1.42.1 over the joined
 * penguins CSVs (depictio/projects/init/penguins/data) — the same ordering
 * `render_table_endpoint` serves (nulls_last=True, maintain_order=True):
 *   natural order row 0:            individual_id = "adelie_1"
 *   natural order row 100 (page 2): individual_id = "adelie_101"
 *   sort body_mass_g asc  row 0:    body_mass_g = 2700 (chinstrap_39)
 *   sort body_mass_g desc row 0:    body_mass_g = 6300 (gentoo_18)
 *   species == Adelie:              151 of 342 rows
 * If these drift, the in-browser kernel no longer matches the server —
 * a real bug, not a flaky test.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";
import {
  PENGUINS_MANIFEST,
  blockNetwork,
  injectedBundleUrl,
  skipUnlessBundleBuilt,
} from "./helpers";

/** The table component's grid item (scrolled into view so the lazy
 *  in-view fetch actually fires — the table sits below the fold). */
async function tableItem(page: Page): Promise<Locator> {
  const item = page
    .locator(".react-grid-item", { hasText: "Raw Measurements" })
    .first();
  await item.scrollIntoViewIfNeeded();
  return item;
}

function cell(table: Locator, rowIndex: number, colId: string): Locator {
  return table.locator(
    `.ag-center-cols-container .ag-row[row-index="${rowIndex}"] .ag-cell[col-id="${colId}"]`,
  );
}

test.describe("static bundle — live table (penguins)", () => {
  test.beforeEach(() => skipUnlessBundleBuilt());

  test("renders offline, sorts on header click and paginates", async ({
    page,
  }) => {
    const attempts = await blockNetwork(page);
    await page.goto(injectedBundleUrl(PENGUINS_MANIFEST));
    await page.waitForSelector(".react-grid-item", { timeout: 30_000 });

    const table = await tableItem(page);
    // Live tier — no frozen badge anywhere on the dashboard.
    await expect(page.locator('[data-static-tier="frozen"]')).toHaveCount(0);

    // Unfiltered natural order: 342 total rows, first row is the first row
    // of the joined frame.
    await expect(table.getByText("342 rows")).toBeVisible({ timeout: 30_000 });
    await expect(cell(table, 0, "individual_id")).toHaveText("adelie_1");

    // Pagination: page 2 starts at row 100 of the natural order. AG Grid's
    // infinite row model fetches the block through the shim's live path.
    await table.locator('[aria-label="Next Page"]').click();
    await expect(cell(table, 100, "individual_id")).toHaveText("adelie_101", {
      timeout: 30_000,
    });
    await table.locator('[aria-label="Previous Page"]').click();
    await expect(cell(table, 0, "individual_id")).toHaveText("adelie_1");

    // Header click #1 → ascending: smallest body mass first (Polars asc,
    // nulls last). The header label is the live-path titlecased name.
    const massHeader = table.locator(
      '.ag-header-cell[col-id="body_mass_g"] .ag-header-cell-label',
    );
    await massHeader.click();
    await expect(cell(table, 0, "body_mass_g")).toHaveText("2700", {
      timeout: 30_000,
    });
    await expect(cell(table, 0, "individual_id")).toHaveText("chinstrap_39");

    // Header click #2 → descending: largest first.
    await massHeader.click();
    await expect(cell(table, 0, "body_mass_g")).toHaveText("6300", {
      timeout: 30_000,
    });
    await expect(cell(table, 0, "individual_id")).toHaveText("gentoo_18");

    expect(attempts).toEqual([]);
  });

  test("the species filter narrows the live row count offline", async ({
    page,
  }) => {
    const attempts = await blockNetwork(page);
    await page.goto(injectedBundleUrl(PENGUINS_MANIFEST));
    await page.waitForSelector(".react-grid-item", { timeout: 30_000 });

    const table = await tableItem(page);
    await expect(table.getByText("342 rows")).toBeVisible({ timeout: 30_000 });

    // Filter to Adelie via the species MultiSelect: the table refetches its
    // pages through the mask path — 151 of 342 rows survive.
    await page.locator(".mantine-MultiSelect-input").first().click();
    await page.getByRole("option", { name: "Adelie" }).click();
    await page.keyboard.press("Escape");

    await table.scrollIntoViewIfNeeded();
    await expect(table.getByText("151 rows")).toBeVisible({ timeout: 30_000 });
    await expect(cell(table, 0, "species")).toHaveText("Adelie");

    expect(attempts).toEqual([]);
  });
});
