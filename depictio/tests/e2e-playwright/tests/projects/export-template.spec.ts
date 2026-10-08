/**
 * The Export template section of the project settings (ExportTemplatePanel
 * inside ProjectSettingsModal, opened from "Project settings" on the project
 * detail page).
 *
 * The section validates the template id client-side (same rule as the
 * backend: slash-separated `[A-Za-z0-9][A-Za-z0-9._-]*` segments) and, on
 * success, hands the zip from POST /projects/{id}/export_template to the
 * browser as a download. The download is captured and its central directory
 * read here so the assertion is on the bundle's contents, not just on a file
 * name.
 *
 * Runs for admins in standard AND single-user mode; skipped in public mode.
 * Targets the seeded Iris project and skips when that seed is absent.
 */

import { readFileSync } from "node:fs";
import { Page } from "@playwright/test";
import { test, expect, getAuthMode } from "@fixtures/auth";
import { IRIS_PROJECT_ID } from "@fixtures/projects";

const PROJECT_URL = `/projects/${IRIS_PROJECT_ID}`;

/**
 * Entry names of a zip archive, read from its central directory (no
 * dependency needed). Signatures: end-of-central-directory 0x06054b50,
 * central file header 0x02014b50.
 */
function zipEntryNames(archive: Buffer): string[] {
  let eocd = -1;
  for (let i = archive.length - 22; i >= Math.max(0, archive.length - 65_557); i--) {
    if (archive.readUInt32LE(i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("not a zip archive: no end-of-central-directory record");
  const entryCount = archive.readUInt16LE(eocd + 10);
  let offset = archive.readUInt32LE(eocd + 16);
  const names: string[] = [];
  for (let n = 0; n < entryCount; n++) {
    if (archive.readUInt32LE(offset) !== 0x02014b50) {
      throw new Error(`corrupt central directory at byte ${offset}`);
    }
    const nameLength = archive.readUInt16LE(offset + 28);
    const extraLength = archive.readUInt16LE(offset + 30);
    const commentLength = archive.readUInt16LE(offset + 32);
    names.push(archive.toString("utf8", offset + 46, offset + 46 + nameLength));
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return names;
}

/** Open the project settings on the Export template section. */
async function openExportSection(page: Page) {
  await page.locator("[data-testid='project-settings-button']").click();
  // The dialog remembers the last section per browser: pick it explicitly.
  await page.locator("[data-testid='project-settings-nav-export']").click();
  const idInput = page.locator("[data-testid='export-template-id-input']");
  await expect(idInput).toBeVisible();
  return idInput;
}

test.describe("Export project as template", () => {
  test.beforeEach(async ({ loginAsAdmin, page }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Exporting a template needs edit permission on a project.");

    await loginAsAdmin();
    await page.goto(PROJECT_URL);

    // Skip (not fail) on stacks without the Iris reference seed: the
    // settings button enables once the project has loaded, and a missing
    // project shows the load error instead.
    const settingsButton = page.locator("[data-testid='project-settings-button']");
    const loadError = page.getByText(/failed to (load|fetch) project/i);
    await expect
      .poll(async () => (await settingsButton.isEnabled()) || (await loadError.isVisible()), {
        timeout: 15_000,
      })
      .toBe(true);
    test.skip(
      !(await settingsButton.isEnabled()),
      "Iris reference project not seeded in this stack.",
    );
  });

  test("rejects an empty or malformed template id inline", async ({ page }) => {
    const idInput = await openExportSection(page);
    const submit = page.locator("[data-testid='export-template-submit']");
    const dialog = page.getByRole("dialog");
    // Enabled once the current user is known to be allowed to export.
    await expect(submit).toBeEnabled({ timeout: 15_000 });

    await submit.click();
    await expect(dialog.getByText("Template ID is required.")).toBeVisible();

    // A path-escaping id never reaches the server: the client mirrors the
    // backend's segment rule and explains it.
    await idInput.fill("../escape");
    await submit.click();
    await expect(dialog.getByText(/invalid format/i)).toBeVisible();
    await expect(dialog).toBeVisible(); // still open for correction

    // Typing again clears the error.
    await idInput.fill("e2e");
    await expect(dialog.getByText(/invalid format/i)).toHaveCount(0);
  });

  test("downloads a zip bundle whose root holds template.yaml", async ({ page }) => {
    const idInput = await openExportSection(page);
    await expect(page.locator("[data-testid='export-template-submit']")).toBeEnabled({
      timeout: 15_000,
    });
    await idInput.fill("e2e/iris-export/1");

    const downloadPromise = page.waitForEvent("download", { timeout: 60_000 });
    await page.locator("[data-testid='export-template-submit']").click();
    const download = await downloadPromise;

    // File name mirrors the template id with slashes flattened.
    expect(download.suggestedFilename()).toMatch(/\.zip$/);
    expect(download.suggestedFilename()).toBe("e2e_iris-export_1.zip");

    const archivePath = await download.path();
    expect(archivePath).toBeTruthy();
    const names = zipEntryNames(readFileSync(archivePath!));
    expect(names).toContain("template.yaml");
    // The seeded project has dashboards, exported as tag-based YAML.
    expect(names.some((name) => /^dashboards\/[^/]+\.yaml$/.test(name))).toBeTruthy();

    // The outcome is shown in the section, which stays open on the result.
    const success = page.locator("[data-testid='export-template-success']");
    await expect(success).toBeVisible({ timeout: 10_000 });
    await expect(success).toContainText("Template exported");
    await expect(success).toContainText("e2e_iris-export_1.zip");
  });
});
