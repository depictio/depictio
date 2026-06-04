/**
 * Port of: cypress/e2e/projects/project-permissions.cy.js
 *
 * React-stack route: /projects/<id>/permissions (PermissionsApp.tsx).
 * Semantics that changed vs the Dash UI:
 *   - Users are added via an email Autocomplete + "Add user" button, always
 *     defaulting to Viewer (no per-add role checkboxes anymore).
 *   - Roles are mutually exclusive: enabling one role in the ag-grid clears
 *     the others on the same row (handleCellChange) — replaces the Dash
 *     "exactly one checkbox" validation test.
 *   - Delete = per-row trash ActionIcon (title "Remove user").
 *   - Visibility toggle opens a confirm modal ("Make Public"/"Make Private").
 *
 * Runs for admins in standard AND single-user mode; skipped in public mode
 * (temporary users cannot manage permissions).
 */

import { test, expect, getAuthMode } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";
import { clickMantineSwitch } from "@fixtures/ui";

// Seeded Iris reference project (same id the Cypress suite targeted).
const IRIS_PROJECT_ID = "646b0f3c1e4a2d7f8e5b8c9a";
const PERMISSIONS_URL = `/projects/${IRIS_PROJECT_ID}/permissions`;

const TEST_EMAIL = credentials.testUser.email;

/** Row in the ag-grid for a given member email. */
function gridRow(page: import("@playwright/test").Page, email: string) {
  return page.locator(".ag-row", { hasText: email });
}

/** Remove the test user from the grid if present (idempotent cleanup). */
async function removeIfPresent(page: import("@playwright/test").Page) {
  const row = gridRow(page, TEST_EMAIL);
  if ((await row.count()) > 0) {
    await row.locator("button[title='Remove user']").click();
    await expect(row).toHaveCount(0, { timeout: 10_000 });
  }
}

test.describe("Project Permissions", () => {
  test.beforeEach(async ({ loginAsAdmin, page }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Permissions management requires a real account.");

    await loginAsAdmin();
    await page.goto(PERMISSIONS_URL);

    // Stacks without the Iris reference seeds show the load-error state —
    // skip rather than fail (CI boots a bare backend).
    const title = page.getByText("Roles & Permissions");
    const loadError = page.getByText(/failed to load|back to projects/i);
    await expect(title.or(loadError).first()).toBeVisible({ timeout: 15_000 });
    test.skip(
      !(await title.isVisible()),
      "Iris reference project not seeded in this stack.",
    );
    // Wait for the members grid to render rows (the seeded owner at minimum).
    await expect(page.locator(".ag-row").first()).toBeVisible({ timeout: 15_000 });
  });

  test("admin sees management controls enabled", async ({ page }) => {
    await expect(page.locator("[data-testid='project-visibility-switch']")).toBeEnabled();
    await expect(page.locator("[data-testid='permissions-add-user-input']")).toBeVisible();
    // Add button is disabled until an email is typed.
    await expect(page.locator("[data-testid='permissions-add-user-btn']")).toBeDisabled();
  });

  test("adds a user (Viewer by default), promotes to Editor, then removes", async ({
    page,
  }) => {
    await removeIfPresent(page);

    // Add the test user by email — defaults to Viewer.
    await page.locator("[data-testid='permissions-add-user-input']").fill(TEST_EMAIL);
    await page.locator("[data-testid='permissions-add-user-btn']").click();

    const row = gridRow(page, TEST_EMAIL);
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(row.locator("[col-id='Viewer'] input[type='checkbox']")).toBeChecked();

    // Promote to Editor: roles are mutually exclusive, Viewer must clear.
    // ag-grid checkbox cells toggle on a click on the checkbox input itself.
    await row.locator("[col-id='Editor'] input[type='checkbox']").click({ force: true });
    await expect(row.locator("[col-id='Editor'] input[type='checkbox']")).toBeChecked({
      timeout: 10_000,
    });
    await expect(
      row.locator("[col-id='Viewer'] input[type='checkbox']"),
    ).not.toBeChecked();

    // Remove the user again.
    await row.locator("button[title='Remove user']").click();
    await expect(row).toHaveCount(0, { timeout: 10_000 });
  });

  test("rejects adding an unknown email", async ({ page }) => {
    await page
      .locator("[data-testid='permissions-add-user-input']")
      .fill(`nobody-${Date.now()}@nowhere.invalid`);
    await page.locator("[data-testid='permissions-add-user-btn']").click();

    // Error notification, and no row added.
    await expect(page.getByText(/Add failed/i)).toBeVisible({ timeout: 10_000 });
    await expect(gridRow(page, "@nowhere.invalid")).toHaveCount(0);
  });

  test("rejects adding a duplicate member", async ({ page }) => {
    await removeIfPresent(page);

    await page.locator("[data-testid='permissions-add-user-input']").fill(TEST_EMAIL);
    await page.locator("[data-testid='permissions-add-user-btn']").click();
    await expect(gridRow(page, TEST_EMAIL)).toBeVisible({ timeout: 10_000 });

    // Second add of the same user must fail.
    await page.locator("[data-testid='permissions-add-user-input']").fill(TEST_EMAIL);
    await page.locator("[data-testid='permissions-add-user-btn']").click();
    await expect(page.getByText(/already in this project/i)).toBeVisible({
      timeout: 10_000,
    });

    // Cleanup.
    await removeIfPresent(page);
  });

  test("visibility toggle opens the confirm modal and cancel keeps state", async ({
    page,
  }) => {
    const visibilitySwitch = page.locator("[data-testid='project-visibility-switch']");
    // The switch enables only once the current user + project have loaded
    // and the canManage gate passes.
    await expect(visibilitySwitch).toBeEnabled({ timeout: 15_000 });
    const wasChecked = await visibilitySwitch.isChecked();

    await clickMantineSwitch(page, "project-visibility-switch");
    await expect(page.getByText("Change Project Visibility")).toBeVisible({
      timeout: 10_000,
    });
    // The confirm button names the target state.
    await expect(page.locator("[data-testid='confirm-visibility-btn']")).toContainText(
      wasChecked ? /Make Private/ : /Make Public/,
    );

    // Cancel: no change is persisted.
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByText("Change Project Visibility")).toBeHidden();
    expect(await visibilitySwitch.isChecked()).toBe(wasChecked);
  });
});
