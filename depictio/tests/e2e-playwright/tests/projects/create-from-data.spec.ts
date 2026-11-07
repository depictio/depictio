/**
 * The create-project chooser: two large cards (Upload files, A folder or
 * bucket), a quiet "Other" row, and the optional pipeline line of the folder
 * flow. UI only: no project is created.
 */

import { Page } from "@playwright/test";
import { test, expect, getAuthMode } from "@fixtures/auth";

async function openChooser(page: Page): Promise<void> {
  await page.goto("/projects");
  await page.locator("[data-tour-id='projects-create']").click();
}

test.describe("Create project chooser", () => {
  test.beforeEach(async () => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Project creation is not exercised in public mode.");
  });

  test("offers files and folder cards, with manifest and empty project in a quiet row", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await openChooser(page);
    await expect(page.getByTestId("create-source-files")).toBeVisible();
    await expect(page.getByTestId("create-source-folder")).toBeVisible();
    await expect(page.getByTestId("create-source-data")).toHaveCount(0);
    await expect(page.getByTestId("create-source-pipeline")).toHaveCount(0);
    await expect(page.getByTestId("create-source-manifest")).toBeVisible();
    await expect(page.getByTestId("create-source-empty")).toBeVisible();
    await expect(page.getByTestId("create-source-run")).toHaveCount(0);
  });

  test("the two cards open the files flow and the folder flow", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await openChooser(page);
    await page.getByTestId("create-source-files").click();

    // Files: a drop zone, and Next waits for at least one file.
    await expect(page.getByTestId("files-dropzone")).toBeVisible();
    await expect(page.getByTestId("files-next")).toHaveAttribute("aria-disabled", "true");

    await expect(page.getByTestId("data-mode-folder")).toHaveCount(0);

    await page.getByTestId("create-source-back").click();
    await page.getByTestId("create-source-folder").click();
    await expect(page.getByTestId("run-data-root-input")).toBeVisible();
    // The pipeline is optional: no picker until the folder was read.
    await expect(page.getByTestId("run-pipeline-select")).toHaveCount(0);
  });

  test("the folder flow offers the pipeline only after the folder was read", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await openChooser(page);
    await page.getByTestId("create-source-folder").click();
    await expect(page.getByTestId("run-data-root-input")).toBeVisible();
    await expect(page.getByTestId("folder-know-pipeline")).toHaveCount(0);
    await expect(page.getByTestId("run-pipeline-select")).toHaveCount(0);
  });
});
