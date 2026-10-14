/**
 * Port of: cypress/e2e/projects/project-permissions.cy.js
 *
 * React-stack route: /projects/<id>/permissions (PermissionsApp.tsx).
 * Semantics that changed vs the Dash UI:
 *   - Users are added via an email Autocomplete + "Add user" button, always
 *     defaulting to Viewer (no per-add role checkboxes anymore).
 *   - Roles are mutually exclusive: enabling one role clears the others on
 *     the same row (setRole) — replaces the Dash "exactly one checkbox"
 *     validation test.
 *   - Two markups: the default (Glass/Paper) look lists members as
 *     `permissions-member-row` items with a `permissions-role-control`
 *     segmented control; Classic (?chrome=base) keeps the ag-grid with one
 *     checkbox column per role. The helpers below drive whichever renders.
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

type Page = import("@playwright/test").Page;
type Role = "Owner" | "Editor" | "Viewer";

/** Which chrome style renders: Glass (default) or Classic (`base`). */
async function isGlass(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.dataset.chrome === "glass");
}

/** Classic markup: the members ag-grid. Scoped to the users grid container —
 *  the page renders a second (groups) ag-grid below it. */
function usersGridRows(page: Page) {
  return page.locator("[data-testid='permissions-users-grid']").locator(".ag-row");
}

/** Every member row on the page, whichever markup renders. */
function memberRows(page: Page) {
  return page
    .locator("[data-testid='permissions-member-row']")
    .or(usersGridRows(page));
}

/** Row for a given member email (substring match, like ag-grid's hasText). */
function gridRow(page: Page, email: string) {
  return page
    .locator(`[data-testid='permissions-member-row'][data-email*="${email}"]`)
    .or(usersGridRows(page).filter({ hasText: email }));
}

/** Assert whether `role` is the one set on a member's row. */
async function expectRole(
  page: Page,
  row: import("@playwright/test").Locator,
  role: Role,
  on = true,
) {
  const control = (await isGlass(page))
    ? row.locator(`input[type='radio'][value='${role}']`)
    : row.locator(`[col-id='${role}'] input[type='checkbox']`);
  if (on) await expect(control).toBeChecked({ timeout: 10_000 });
  else await expect(control).not.toBeChecked({ timeout: 10_000 });
}

/** Switch a member to `role` (the others clear: roles are exclusive). */
async function setRole(
  page: Page,
  row: import("@playwright/test").Locator,
  role: Role,
) {
  if (await isGlass(page)) {
    await row.locator("label", { hasText: new RegExp(`^${role}$`) }).click();
  } else {
    // ag-grid checkbox cells toggle on a click on the checkbox input itself.
    await row.locator(`[col-id='${role}'] input[type='checkbox']`).click({ force: true });
  }
}

/** Remove the test user from the grid if present (idempotent cleanup). */
async function removeIfPresent(page: Page) {
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
    // skip rather than fail (CI boots a bare backend). Only that state skips:
    // the page root (`permissions-page`) is the same in both chromes, so a
    // missing title can no longer hide a broken page behind a skip.
    const pageRoot = page.locator("[data-testid='permissions-page']");
    const loadError = page.getByText(/failed to load|back to projects/i);
    await expect(pageRoot.or(loadError).first()).toBeVisible({ timeout: 15_000 });
    test.skip(
      !(await pageRoot.isVisible()),
      "Iris reference project not seeded in this stack.",
    );
    // Wait for the members to render (the seeded owner at minimum).
    await expect(memberRows(page).first()).toBeVisible({ timeout: 15_000 });
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
    await expectRole(page, row, "Viewer");

    // Promote to Editor: roles are mutually exclusive, Viewer must clear.
    await setRole(page, row, "Editor");
    await expectRole(page, row, "Editor");
    await expectRole(page, row, "Viewer", false);

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
