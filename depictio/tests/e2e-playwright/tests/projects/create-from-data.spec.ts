/**
 * The new-project dialog: one screen for files and a folder, a quiet "Other"
 * row, the pipeline offered only once a folder was read. UI only, except the
 * last test, where a dropped file becomes a project.
 */

import { Page } from "@playwright/test";
import { test, expect, getAuthMode } from "@fixtures/auth";

async function openDialog(page: Page): Promise<void> {
  await page.goto("/projects?no-walkthrough=1");
  await page.locator("[data-tour-id='projects-create']").click();
  await page.getByTestId("create-project-name").fill(`e2e-data-${Date.now()}`);
  await page.getByTestId("create-project-next").click();
  await expect(page.getByTestId("data-source-fields")).toBeVisible();
}

test.describe("New project dialog", () => {
  test.beforeEach(async () => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Project creation is not exercised in public mode.");
  });

  test("asks for files or a folder on one screen; manifests are gone", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await openDialog(page);
    await expect(page.getByTestId("files-dropzone")).toBeVisible();
    await expect(page.getByTestId("run-data-root-input")).toBeVisible();
    await expect(page.getByTestId("create-source-manifest")).toHaveCount(0);
    // Nothing given yet: Next waits, and says for what.
    await expect(page.getByTestId("create-from-run-submit")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await expect(page.getByTestId("run-submit-disabled-reason")).toContainText("Drop files");
  });

  test("Import has moved from the page header to the dialog", async ({ loginAsAdmin, page }) => {
    await loginAsAdmin();
    await page.goto("/projects");
    await expect(page.locator("[data-tour-id='projects-create']")).toBeVisible();
    await expect(page.getByTestId("import-project-button")).toHaveCount(0);
  });

  test("the pipeline is offered only after a folder was read", async ({ loginAsAdmin, page }) => {
    await loginAsAdmin();
    await openDialog(page);
    await expect(page.getByTestId("folder-know-pipeline")).toHaveCount(0);
    await expect(page.getByTestId("run-pipeline-select")).toHaveCount(0);
  });

  test("a dropped file needs no folder", async ({ loginAsAdmin, page }) => {
    await loginAsAdmin();
    await openDialog(page);
    await page.getByTestId("files-input").setInputFiles({
      name: "sample_sheet.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("sample,condition\nS1,treated\nS2,control\n"),
    });
    await expect(page.getByTestId("files-item-0")).toContainText("sample_sheet.csv");
    await page.getByTestId("create-from-run-submit").click();
    await expect(page.getByTestId("files-found-card")).toBeVisible();
    await expect(page.getByTestId("files-found-0")).toContainText("2 columns");
  });
});
