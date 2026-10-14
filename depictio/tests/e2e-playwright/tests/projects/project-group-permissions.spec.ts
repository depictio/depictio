/**
 * Group sharing on the project permissions page (PermissionsApp.tsx).
 *
 * The page renders a "Groups" section below the members:
 *   - groups are added via an Autocomplete + "Add group" button, defaulting
 *     to Viewer;
 *   - a group holds exactly one role — enabling one clears the others on the
 *     same row (setGroupRole / handleGroupCellChange);
 *   - delete = per-row ActionIcon (title "Remove group").
 *   - two markups, like the members: the default (Glass) look lists groups as
 *     `permissions-group-row` items with a segmented role control; Classic
 *     (?chrome=base) keeps an ag-grid with one checkbox column per role. The
 *     helpers below drive whichever renders.
 *
 * All locators are scoped to [data-testid='permissions-groups-grid'] so they
 * can never collide with the members list/grid above.
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

type Page = import("@playwright/test").Page;
type Role = "Owner" | "Editor" | "Viewer";

/** Which chrome style renders: Glass (default) or Classic (`base`). */
async function isGlass(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.dataset.chrome === "glass");
}

/** The groups container (Glass list or Classic ag-grid). */
function groupsGrid(page: Page) {
  return page.locator("[data-testid='permissions-groups-grid']");
}

/** Row for a given group name, whichever markup renders. */
function groupRow(page: Page, name: string) {
  return groupsGrid(page)
    .locator(`[data-testid='permissions-group-row'][data-name*="${name}"]`)
    .or(groupsGrid(page).locator(".ag-row", { hasText: name }));
}

/** Assert whether `role` is the one set on a group's row. */
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

/** Switch a group to `role` (the others clear: roles are exclusive). */
async function setRole(
  page: Page,
  row: import("@playwright/test").Locator,
  role: Role,
) {
  if (await isGlass(page)) {
    await row.locator("label", { hasText: new RegExp(`^${role}$`) }).click();
  } else {
    await row.locator(`[col-id='${role}'] input[type='checkbox']`).click({ force: true });
  }
}

/** Remove the group from the list if present (idempotent cleanup). */
async function removeGroupIfPresent(page: Page) {
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
    // The page root (`permissions-page`) is the same in both chromes.
    const pageRoot = page.locator("[data-testid='permissions-page']");
    const loadError = page.getByText(/failed to load|back to projects/i);
    await expect(pageRoot.or(loadError).first()).toBeVisible({ timeout: 15_000 });
    test.skip(
      !(await pageRoot.isVisible()),
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
    await expectRole(page, row, "Viewer");

    // Promote to Editor: roles are exclusive, Viewer must clear.
    await setRole(page, row, "Editor");
    await expectRole(page, row, "Editor");
    await expectRole(page, row, "Viewer", false);

    // Reload — the Editor role must have been persisted server-side.
    await page.reload();
    const rowAfterReload = groupRow(page, GROUP_NAME);
    await expect(rowAfterReload).toBeVisible({ timeout: 15_000 });
    await expectRole(page, rowAfterReload, "Editor");
    await expectRole(page, rowAfterReload, "Viewer", false);

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
