/**
 * Admin groups management (React /admin → Groups tab).
 *
 * The tab renders a master-detail workspace (GroupsWorkspace.tsx): a
 * searchable ag-grid of every group on the left, the selected group's
 * management panel (rename, members grid, add member, P.I., delete) on the
 * right. Covers the sysadmin lifecycle end-to-end against the seeded dev
 * stack:
 *   create group → add the seeded test user → promote them to group admin
 *   → delete the group.
 *
 * A second test covers designating a P.I. by email before that person has an
 * account (parked as ``pending_pi_email``, claimed at their first sign-in).
 *
 * Uses a unique throwaway group name per run so the test is idempotent and
 * retry-safe; the final step deletes it. Skipped on public/demo stacks,
 * which have no real admin account to drive the mutations with.
 */

import { test, expect, getAuthMode } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

type Page = import("@playwright/test").Page;

/** Master list of groups (left pane). */
function groupsGrid(page: Page) {
  return page.locator("[data-testid='groups-list-grid']");
}

/** Row in the master list for a given group name. */
function groupRow(page: Page, name: string) {
  return groupsGrid(page).locator(".ag-row", { hasText: name });
}

/** Members grid inside the detail pane (right). */
function membersGrid(page: Page) {
  return page.locator("[data-testid='group-members-grid']");
}

function memberRow(page: Page, email: string) {
  return membersGrid(page).locator(".ag-row", { hasText: email });
}

async function openGroupsTab(page: Page) {
  await page.goto("/admin");
  await page.getByRole("tab", { name: "Groups" }).click();
  await expect(page.locator("[data-testid='admin-create-group-btn']")).toBeVisible({
    timeout: 15_000,
  });
  await expect(groupsGrid(page)).toBeVisible({ timeout: 15_000 });
}

test.describe("Admin Groups", () => {
  test.beforeEach(async () => {
    const mode = await getAuthMode();
    test.skip(
      mode.is_public_mode || mode.is_demo_mode,
      "Groups administration requires a real admin account.",
    );
  });

  test("create, add member, promote to group admin, delete", async ({
    page,
    loginAsAdmin,
  }) => {
    const groupName = `e2e-group-${Date.now()}`;
    const memberEmail = credentials.testUser.email;

    await loginAsAdmin();
    await openGroupsTab(page);

    // ---- Create — the new group is selected automatically ----
    await page.locator("[data-testid='admin-create-group-btn']").click();
    await page.locator("[data-testid='create-group-name']").fill(groupName);
    await page
      .locator("[data-testid='create-group-description']")
      .fill("Throwaway e2e group");
    await page.locator("[data-testid='create-group-submit']").click();

    await expect(groupRow(page, groupName)).toBeVisible({ timeout: 15_000 });
    const detail = page.locator("[data-testid='group-detail-pane']");
    await expect(
      detail.locator("[data-testid='group-rename-input']"),
    ).toHaveValue(groupName, { timeout: 15_000 });

    // ---- Add member ----
    await page.locator("[data-testid='group-add-member-input']").fill(memberEmail);
    await page.locator("[data-testid='group-add-member-btn']").click();
    await expect(memberRow(page, memberEmail)).toBeVisible({ timeout: 15_000 });

    // ---- Promote to group admin (checkbox column) ----
    await memberRow(page, memberEmail)
      .locator("[col-id='is_group_admin'] input[type='checkbox']")
      .click({ force: true });
    // The grid re-renders from the refetched detail — the checkbox stays on.
    await expect(
      memberRow(page, memberEmail).locator(
        "[col-id='is_group_admin'] input[type='checkbox']",
      ),
    ).toBeChecked({ timeout: 15_000 });

    // ---- Search narrows the master list to the new group ----
    await page.locator("[data-testid='groups-search']").fill(groupName);
    await expect(groupsGrid(page).locator(".ag-row")).toHaveCount(1, {
      timeout: 10_000,
    });

    // ---- Delete ----
    await page.locator("[data-testid='admin-delete-group-btn']").click();
    await page.locator("[data-testid='delete-group-confirm']").click();
    await expect(groupRow(page, groupName)).toHaveCount(0, { timeout: 15_000 });
  });

  test("designates a P.I. by email before that person has an account", async ({
    page,
    loginAsAdmin,
  }) => {
    const groupName = `e2e-pi-group-${Date.now()}`;
    // Deliberately an address with no Depictio account: the designation is
    // parked on the group and applied at that person's first sign-in.
    const futurePi = `future-pi-${Date.now()}@example.org`;

    await loginAsAdmin();
    await openGroupsTab(page);

    await page.locator("[data-testid='admin-create-group-btn']").click();
    await page.locator("[data-testid='create-group-name']").fill(groupName);
    await page.locator("[data-testid='create-group-pi']").fill(futurePi);
    await page.locator("[data-testid='create-group-submit']").click();

    // The detail pane reports the parked designation, not a member row.
    const pending = page.locator("[data-testid='group-pending-pi']");
    await expect(pending).toBeVisible({ timeout: 15_000 });
    await expect(pending).toContainText(futurePi);
    await expect(memberRow(page, futurePi)).toHaveCount(0);

    // Clearing removes it and brings the designation input back.
    await page.locator("[data-testid='group-clear-pending-pi']").click();
    await expect(page.locator("[data-testid='group-pending-pi-input']")).toBeVisible({
      timeout: 15_000,
    });

    // Cleanup — this group is throwaway.
    await page.locator("[data-testid='admin-delete-group-btn']").click();
    await page.locator("[data-testid='delete-group-confirm']").click();
    await expect(groupRow(page, groupName)).toHaveCount(0, { timeout: 15_000 });
  });

  test("seeded groups hide the delete button", async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    await openGroupsTab(page);

    await groupRow(page, "admin").first().click();
    // Management panel renders, but no delete button for the protected group.
    await expect(page.locator("[data-testid='group-management-card']")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.locator("[data-testid='admin-delete-group-btn']")).toHaveCount(0);
  });
});
