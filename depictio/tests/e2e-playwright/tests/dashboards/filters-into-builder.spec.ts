/**
 * Regression spec for #329 + #196 — dashboard filter propagation across the
 * component builder's full-page round-trip.
 *
 * #329: with a dashboard filter active, the component design view's data
 *       previews must reflect that filter (they used to always show the
 *       unfiltered dataset — the builder never received filter state).
 * #196: a component added while filters are active must render already
 *       filtered when the editor comes back (filters used to die on the
 *       page navigation, so the whole grid reloaded unfiltered).
 *
 * One flow covers both: build a fresh dashboard on the seeded Iris project
 * (150 rows, `variety` ∈ {Setosa, Versicolor, Virginica} × 50), add a
 * MultiSelect filter on `variety` through the builder, select Setosa, then
 * add a Table component — the builder preview must say "of 50 rows" (#329,
 * togglable back to 150), and the saved table must come up showing 50 rows
 * with the Setosa filter still applied (#196).
 */

import { test, expect } from "@fixtures/auth";
import { createDashboard, deleteDashboard } from "@fixtures/dashboard";
import type { Page } from "@playwright/test";

/** Pick an option from an open Mantine Select/MultiSelect portal listbox. */
async function pickOption(page: Page, text: string | RegExp): Promise<void> {
  await page
    .locator("[role='option']")
    .filter({ hasText: text })
    .first()
    .click();
}

/** Open the component builder from the editor chrome.
 *  "Add" is a menu (Component / Section), not a direct link, so reaching the
 *  builder takes two clicks — the button, then the entry. */
async function openComponentBuilder(page: Page): Promise<void> {
  await page.locator("[data-tour-id='editor-add-component']").click();
  await page.locator("[data-testid='add-component']").click();
  await page.waitForURL(/\/component\/add\//, { timeout: 15_000 });
}

/** StepType: pick a component type card by its type, not by its text.
 *  Several cards mention another card's label in their description (Figure is
 *  "Interactive data visualizations", Image is an "Interactive image grid"), so
 *  filtering .component-selection-card by text matches three cards, not one. */
async function pickComponentType(page: Page, type: string): Promise<void> {
  await page.locator(`[data-testid='component-type-${type}']`).click();
}

/** A Mantine Select's field label is wired to both the input and the popup
 *  listbox (`aria-labelledby`), so getByLabel() resolves to two elements and
 *  every call on it fails Playwright's strict mode. Address the input by role:
 *  the listbox is role="listbox", so only the input matches. */
function selectInput(page: Page, label: string) {
  return page.getByRole("textbox", { name: label });
}

/** Mantine's Switch forwards data-testid to its real <input>, which it keeps
 *  visually hidden (1×1 and clipped). Clicking that input fails with "Element
 *  is outside of the viewport" — `force` skips the actionability checks but
 *  still clicks at the element's coordinates. Click the <label> bound to it
 *  instead: that is the visible track, and what a user actually hits. */
async function flipSwitch(page: Page, testId: string): Promise<void> {
  const id = await page.locator(`[data-testid='${testId}']`).getAttribute("id");
  await page.locator(`label[for='${id}']`).click();
}

/** StepData: choose the Iris data collection. Basic projects render a single
 *  "Data Collection" select; advanced ones add a "Workflow" select first. */
async function pickIrisDataCollection(page: Page): Promise<void> {
  const workflowSelect = selectInput(page, "Workflow");
  if (await workflowSelect.isVisible().catch(() => false)) {
    await workflowSelect.click();
    await page.locator("[role='option']").first().click();
  }
  const dcSelect = selectInput(page, "Data Collection");
  await expect(dcSelect).toBeEnabled({ timeout: 15_000 });
  await dcSelect.click();
  await page.locator("[role='option']").first().click();
  // The DC info card fetch confirms the pick registered before Next.
  await expect(page.getByText("Data Collection Information").first()).toBeVisible({
    timeout: 15_000,
  });
}

test.describe("Active filters propagate into the builder and new components", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "Component creation requires an authenticated dashboard owner.",
  );

  test("filter → builder preview is filtered (#329) → new component pre-filtered (#196)", async ({
    loginAsAdmin,
    page,
  }) => {
    test.setTimeout(240_000);
    await loginAsAdmin();
    await page.goto("/dashboards");

    const uniqueTitle = `Filter Propagation ${new Date()
      .toISOString()
      .replace(/:/g, "-")}`;
    await createDashboard(page, uniqueTitle);

    // Open the new dashboard and switch to edit mode.
    await page
      .locator("[data-testid='dashboard-card']")
      .filter({ hasText: uniqueTitle })
      .first()
      .click();
    await page.waitForURL(/\/dashboard\//, { timeout: 15_000 });
    await page.locator("[data-tour-id='enter-edit-mode']").click();
    await page.waitForURL(/\/dashboard-edit\//, { timeout: 15_000 });

    // --- Add a MultiSelect interactive filter on `variety` via the builder ---
    await openComponentBuilder(page);
    await pickComponentType(page, "interactive");
    await pickIrisDataCollection(page);
    await page.getByRole("button", { name: "Next Step" }).click();

    await selectInput(page, "Select your column").click();
    await pickOption(page, "variety");
    await selectInput(page, "Select your interactive component").click();
    await pickOption(page, "Multi-select");
    await page.locator("[data-tour-id='component-save']").click();
    await page.waitForURL(/\/dashboard-edit\/[^/]+$/, { timeout: 20_000 });

    // --- Apply the filter: variety = Setosa ---
    const filterInput = page.getByPlaceholder(/Select variety/).first();
    await expect(filterInput).toBeVisible({ timeout: 20_000 });
    await filterInput.click();
    await pickOption(page, "Setosa");
    await page.keyboard.press("Escape");

    // --- Add a Table component while the filter is active ---
    await openComponentBuilder(page);
    await pickComponentType(page, "table");
    await pickIrisDataCollection(page);
    await page.getByRole("button", { name: "Next Step" }).click();

    // #329 — the design view carries the dashboard's active filter and the
    // data preview reflects it: 50 Setosa rows, not the full 150.
    const banner = page.locator("[data-testid='builder-filter-banner']");
    await expect(banner).toBeVisible({ timeout: 15_000 });
    await expect(banner).toContainText("1 active dashboard filter");
    await expect(page.getByText(/of 50 rows/)).toBeVisible({ timeout: 30_000 });

    // The toggle flips the preview back to the unfiltered dataset and back.
    await flipSwitch(page, "builder-filter-toggle");
    await expect(page.getByText(/of 150 rows/)).toBeVisible({ timeout: 30_000 });
    await flipSwitch(page, "builder-filter-toggle");
    await expect(page.getByText(/of 50 rows/)).toBeVisible({ timeout: 30_000 });

    await page.locator("[data-tour-id='component-save']").click();
    await page.waitForURL(/\/dashboard-edit\/[^/]+$/, { timeout: 20_000 });

    // #196 — back in the editor, the filter survived the round-trip…
    await expect(page.getByText("Setosa").first()).toBeVisible({ timeout: 20_000 });

    // …and the freshly added table renders pre-filtered. The grid's table carries
    // its total in the pager, not in a "N rows" badge — that wording only exists
    // in the builder's preview. "1 to 50 of 50" on a single page is the filtered
    // set; unfiltered, the same table reads "of 150" across three pages.
    // (Row-content assertions would be unsound here — iris.csv lists all 50
    // Setosa rows first, so page one of an UNfiltered table also shows only
    // Setosa. The total is what discriminates.)
    await expect(page.getByText(/1 to 50 of 50/).first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText(/of 150/)).toHaveCount(0);

    // Cleanup.
    await page.goto("/dashboards");
    await deleteDashboard(page, uniqueTitle);
  });
});
