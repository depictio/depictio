/**
 * Group sharing on the project permissions page (PermissionsApp.tsx).
 *
 * The page renders a second ag-grid ("Groups" card) below the members grid:
 *   - groups are added via an Autocomplete + "Add group" button, defaulting
 *     to Viewer;
 *   - a group holds exactly one role — enabling one clears the others on the
 *     same row (handleGroupCellChange);
 *   - delete = per-row trash ActionIcon (title "Remove group").
 *
 * All locators are scoped to [data-testid='permissions-groups-grid'] so they
 * can never collide with the members grid above.
 *
 * Targets the seeded Iris reference project and the built-in "users" group
 * (created by db_init.py on every stack). Skipped in public mode.
 */

import { test, expect, getAuthMode } from "@fixtures/auth";

// Seeded Iris reference project (same id project-permissions.spec.ts targets).
const IRIS_PROJECT_ID = "646b0f3c1e4a2d7f8e5b8c9a";
const PERMISSIONS_URL = `/projects/${IRIS_PROJECT_ID}/permissions`;

// Built-in group seeded by db_init.py on every deployment.
const GROUP_NAME = "users";

/** The groups ag-grid container. */
function groupsGrid(page: import("@playwright/test").Page) {
  return page.locator("[data-testid='permissions-groups-grid']");
}

/** Row in the groups ag-grid for a given group name. */
function groupRow(page: import("@playwright/test").Page, name: string) {
  return groupsGrid(page).locator(".ag-row", { hasText: name });
}

/** Remove the group from the grid if present (idempotent cleanup). */
async function removeGroupIfPresent(page: import("@playwright/test").Page) {
  const row = groupRow(page, GROUP_NAME);
  if ((await row.count()) > 0) {
    await row.locator("button[title='Remove group']").click();
    await expect(row).toHaveCount(0, { timeout: 10_000 });
  }
}

test.describe("Project Group Permissions", () => {
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
    // The groups card renders even when the project has no groups yet.
    await expect(groupsGrid(page)).toBeVisible({ timeout: 15_000 });
  });

  test("admin sees the group controls enabled", async ({ page }) => {
    await expect(
      page.locator("[data-testid='permissions-add-group-input']"),
    ).toBeVisible();
    // Add button is disabled until a group name is typed.
    await expect(
      page.locator("[data-testid='permissions-add-group-btn']"),
    ).toBeDisabled();
  });

  test("adds a group (Viewer by default), promotes to Editor, persists across reload, then removes", async ({
    page,
  }) => {
    await removeGroupIfPresent(page);

    // Add the built-in "users" group — defaults to Viewer.
    await page
      .locator("[data-testid='permissions-add-group-input']")
      .fill(GROUP_NAME);
    await page.locator("[data-testid='permissions-add-group-btn']").click();

    const row = groupRow(page, GROUP_NAME);
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(
      row.locator("[col-id='Viewer'] input[type='checkbox']"),
    ).toBeChecked();

    // Promote to Editor: roles are exclusive, Viewer must clear.
    await row
      .locator("[col-id='Editor'] input[type='checkbox']")
      .click({ force: true });
    await expect(
      row.locator("[col-id='Editor'] input[type='checkbox']"),
    ).toBeChecked({ timeout: 10_000 });
    await expect(
      row.locator("[col-id='Viewer'] input[type='checkbox']"),
    ).not.toBeChecked();

    // Reload — the Editor role must have been persisted server-side.
    await page.reload();
    const rowAfterReload = groupRow(page, GROUP_NAME);
    await expect(rowAfterReload).toBeVisible({ timeout: 15_000 });
    await expect(
      rowAfterReload.locator("[col-id='Editor'] input[type='checkbox']"),
    ).toBeChecked({ timeout: 10_000 });
    await expect(
      rowAfterReload.locator("[col-id='Viewer'] input[type='checkbox']"),
    ).not.toBeChecked();

    // Remove the group and verify the removal persists too.
    await rowAfterReload.locator("button[title='Remove group']").click();
    await expect(rowAfterReload).toHaveCount(0, { timeout: 10_000 });

    await page.reload();
    await expect(groupsGrid(page)).toBeVisible({ timeout: 15_000 });
    await expect(groupRow(page, GROUP_NAME)).toHaveCount(0);
  });

  test("rejects adding an unknown group", async ({ page }) => {
    await page
      .locator("[data-testid='permissions-add-group-input']")
      .fill(`no-such-group-${Date.now()}`);
    await page.locator("[data-testid='permissions-add-group-btn']").click();

    // Error notification, and no row added.
    await expect(page.getByText(/Add failed/i)).toBeVisible({ timeout: 10_000 });
    await expect(groupRow(page, "no-such-group-")).toHaveCount(0);
  });
});
