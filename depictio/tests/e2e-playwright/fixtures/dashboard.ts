import { expect, Page } from "@playwright/test";
import { IRIS_PROJECT_LABEL } from "./projects";

/**
 * Opens the "New Dashboard" modal, fills title + project, submits,
 * and waits for the new card to appear. Returns the unique title used.
 */
export async function createDashboard(page: Page, title: string): Promise<void> {
  await page.locator("[data-testid='new-dashboard-btn']").click();
  await page.locator("[data-testid='dashboard-title-input']").fill(title);

  // Mantine Select: click the input to open, then pick the option from the
  // listbox portal (not from badges/text elsewhere on the page).
  await page.locator("[data-testid='dashboard-projects']").click();
  await page
    .locator("[role='option']")
    .filter({ hasText: IRIS_PROJECT_LABEL })
    .first()
    .click();

  await page.locator("[data-testid='create-dashboard-submit']").click();

  // Wait for the card with this title to appear.
  await expect(
    page.locator("[data-testid='dashboard-card']").filter({ hasText: title }).first(),
  ).toBeVisible({ timeout: 15_000 });
}

/**
 * Clicks the actions menu on the card matching `title`, then confirms delete.
 * Waits for the card to disappear.
 */
export async function deleteDashboard(page: Page, title: string): Promise<void> {
  const card = page
    .locator("[data-testid='dashboard-card']")
    .filter({ hasText: title })
    .first();

  // Open the ⋮ actions menu.
  await card.locator("[data-tour-id='dashboard-actions']").click();

  // Wait for the dropdown to be visible then click delete.
  const deleteItem = page.locator("[data-testid='delete-dashboard-btn']");
  await expect(deleteItem).toBeVisible({ timeout: 8_000 });
  await deleteItem.click();

  // Confirm in the modal.
  await page.locator("[data-testid='confirm-delete-btn']").click();

  // Wait for the card to vanish.
  // Use the card selector to avoid strict-mode violations when the title
  // appears in notifications or confirmation dialogs too.
  await expect(
    page.locator("[data-testid='dashboard-card']").filter({ hasText: title }),
  ).toHaveCount(0, { timeout: 15_000 });
}
