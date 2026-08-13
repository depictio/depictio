/**
 * Admin groups management (React /admin → Groups tab).
 *
 * Covers the sysadmin lifecycle of a group end-to-end against the seeded
 * dev stack:
 *   create group → add the seeded test user → promote them to group admin
 *   → delete the group.
 *
 * Uses a unique throwaway group name per run so the test is idempotent and
 * retry-safe; the final step deletes it. Only runs in standard auth mode —
 * single-user/public/demo stacks don't have the seeded admin login.
 */

import { test, expect, getAuthMode } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

test.describe("Admin Groups", () => {
  test.beforeEach(async () => {
    const mode = await getAuthMode();
    test.skip(
      mode.is_single_user_mode || mode.is_public_mode || mode.is_demo_mode,
      "Groups administration requires the standard-mode seeded admin user.",
    );
  });

  test("create, add member, promote to group admin, delete", async ({
    page,
    loginAsAdmin,
  }) => {
    const groupName = `e2e-group-${Date.now()}`;
    const memberEmail = credentials.testUser.email;

    await loginAsAdmin();
    await page.goto("/admin");

    // Open the Groups tab.
    await page.getByRole("tab", { name: "Groups" }).click();
    await expect(
      page.locator("[data-testid='admin-create-group-btn']"),
    ).toBeVisible({ timeout: 15_000 });

    // ---- Create ----
    await page.locator("[data-testid='admin-create-group-btn']").click();
    await page.locator("[data-testid='create-group-name']").fill(groupName);
    await page
      .locator("[data-testid='create-group-description']")
      .fill("Throwaway e2e group");
    await page.locator("[data-testid='create-group-submit']").click();

    const item = page.locator("[data-testid='admin-group-item']", {
      hasText: groupName,
    });
    await expect(item).toBeVisible({ timeout: 15_000 });

    // ---- Expand + add member ----
    await item.getByRole("button", { name: new RegExp(groupName) }).click();
    const addInput = item.locator("[data-testid='group-add-member-input']");
    await expect(addInput).toBeVisible({ timeout: 15_000 });
    await addInput.fill(memberEmail);
    await item.locator("[data-testid='group-add-member-btn']").click();

    const memberRow = item.locator("[data-testid='group-member-row']", {
      hasText: memberEmail,
    });
    await expect(memberRow).toBeVisible({ timeout: 15_000 });

    // ---- Promote to group admin ----
    await memberRow
      .locator("[data-testid='group-admin-toggle'] label", { hasText: "Admin" })
      .click();
    // The SegmentedControl re-renders from the refetched detail — the
    // "admin" radio ends up checked and the Admin badge appears.
    await expect(
      item
        .locator("[data-testid='group-member-row']", { hasText: memberEmail })
        .locator("input[value='admin']"),
    ).toBeChecked({ timeout: 15_000 });

    // ---- Delete ----
    await item.locator("[data-testid='admin-delete-group-btn']").click();
    await page.locator("[data-testid='delete-group-confirm']").click();
    await expect(
      page.locator("[data-testid='admin-group-item']", { hasText: groupName }),
    ).toHaveCount(0, { timeout: 15_000 });
  });

  test("seeded groups hide the delete button", async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    await page.goto("/admin");
    await page.getByRole("tab", { name: "Groups" }).click();

    const adminGroup = page
      .locator("[data-testid='admin-group-item']")
      .filter({ has: page.getByText("admin", { exact: true }) });
    await expect(adminGroup.first()).toBeVisible({ timeout: 15_000 });
    await adminGroup.first().getByRole("button").first().click();
    // Management card renders, but no delete button for the protected group.
    await expect(
      adminGroup.first().locator("[data-testid='group-management-card']"),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      adminGroup.first().locator("[data-testid='admin-delete-group-btn']"),
    ).toHaveCount(0);
  });
});
