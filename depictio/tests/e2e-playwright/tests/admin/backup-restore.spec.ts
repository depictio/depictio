import { test, expect, getAuthMode } from "@fixtures/auth";

/**
 * Admin > Backups: full backup & restore loop.
 *
 * create → newest row appears → download the file → re-upload it (server
 * validates on upload) → typed RESTORE confirmation → destructive restore
 * succeeds. Restoring a seconds-old snapshot of the live database is
 * near-idempotent, which is what makes the destructive step safe to run
 * against the shared CI stack; everything happens inside one test to keep
 * the snapshot→restore window minimal.
 *
 * The Backups tab is gated like the Log & Task tab: hidden on pure
 * public/demo instances (and restore would destroy the demo DB), so the
 * spec skips there.
 */

test.describe.configure({ mode: "serial" });

test.describe("admin backup & restore", () => {
  test.beforeEach(async () => {
    const mode = await getAuthMode();
    test.skip(
      (mode.is_public_mode || mode.is_demo_mode) && !mode.is_single_user_mode,
      "Backups tab is hidden in public/demo mode",
    );
  });

  test("create, download, upload, validate and restore a backup", async ({
    page,
    loginAsAdmin,
  }) => {
    await loginAsAdmin();
    await page.goto("/admin");

    await page.getByTestId("admin-tab-backups").click();
    await expect(page.getByTestId("backup-create-button")).toBeVisible({ timeout: 20_000 });

    // -- create ----------------------------------------------------------
    const rows = page.locator("[data-testid^='backup-row-']");
    // Wait for the initial list fetch to settle before counting.
    await expect(
      page.getByTestId("backup-list-table").or(page.getByText("No backups on the server yet.")),
    ).toBeVisible({ timeout: 20_000 });
    const rowsBefore = await rows.count();

    await page.getByTestId("backup-create-button").click();
    await expect(rows).toHaveCount(rowsBefore + 1, { timeout: 60_000 });

    // Rows are sorted newest-first, so the created backup is the first row.
    const rowTestId = await rows.first().getAttribute("data-testid");
    const backupId = rowTestId!.replace("backup-row-", "");
    expect(backupId).toMatch(/^\d{8}_\d{6}$/);

    // -- download --------------------------------------------------------
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId(`backup-download-${backupId}`).click(),
    ]);
    expect(download.suggestedFilename()).toBe(`depictio_backup_${backupId}.json`);
    const filePath = await download.path();
    expect(filePath).toBeTruthy();

    // -- upload the downloaded file --------------------------------------
    await page
      .locator("[data-testid='backup-upload-zone'] input[type='file']")
      .setInputFiles(filePath!);

    // Upload runs validation server-side and opens the restore modal on the
    // results step directly.
    await expect(page.getByTestId("backup-restore-modal")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("backup-validation-valid")).toBeVisible();
    await expect(page.getByTestId("backup-validation-table")).toBeVisible();

    // -- typed confirmation + destructive restore ------------------------
    const confirmButton = page.getByTestId("backup-restore-confirm-button");
    await expect(confirmButton).toBeDisabled();
    await page.getByTestId("backup-restore-confirm-input").fill("RESTORE");
    await expect(confirmButton).toBeEnabled();
    await confirmButton.click();

    await expect(page.getByTestId("backup-restore-success")).toBeVisible({ timeout: 120_000 });
    await page.getByRole("button", { name: "Close" }).click();

    // The app is still functional after the restore (the admin session
    // survives because tokens are never part of backups).
    await page.goto("/dashboards");
    await expect(page).toHaveURL(/\/dashboards/);
  });
});
