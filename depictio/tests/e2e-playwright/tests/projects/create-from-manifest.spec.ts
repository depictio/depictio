/**
 * "From Manifest" project creation (CreateProjectModal, manifest tab).
 *
 * The first test exercises the UI only. The full-flow test additionally needs
 * a Data Manifest reachable from the API — set MANIFEST_E2E_URL to enable it.
 */

import { Page } from "@playwright/test";
import { test, expect, getAuthMode } from "@fixtures/auth";

const MANIFEST_TEMPLATE_ID = "generic/manifest-tables/1";

/** Open /projects, launch the create modal, switch to the manifest tab. */
async function openManifestTab(page: Page): Promise<void> {
  await page.goto("/projects");
  await page.locator("[data-tour-id='projects-create']").click();
  await page.getByRole("tab", { name: "From Manifest" }).click();
}

test.describe("Create project from a Data Manifest", () => {
  // Runs for admins in standard AND single-user mode; skipped in public mode
  // (CI's public-demo leg), where creating a project as admin is not the
  // path under test. Same probe as project-permissions.spec.ts.
  test.beforeEach(async () => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Project creation is not exercised in public mode.");
  });

  test("manifest tab exposes its form and gates the submit", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await openManifestTab(page);

    await expect(page.locator("[data-testid='manifest-url-input']")).toBeVisible();
    await expect(
      page.locator("[data-testid='manifest-template-select']"),
    ).toBeVisible();
    await expect(
      page.locator("[data-testid='manifest-project-name-input']"),
    ).toBeVisible();

    // Submit stays disabled until both the URL and a template are provided.
    const submit = page.locator("[data-testid='create-from-manifest-submit']");
    await expect(submit).toBeDisabled();
    await page
      .locator("[data-testid='manifest-url-input']")
      .fill("https://example.org/data/manifest.json");
    await expect(submit).toBeDisabled();
  });

  test("creates a project + dashboard from a manifest", async ({
    loginAsAdmin,
    page,
  }) => {
    test.skip(
      !process.env.MANIFEST_E2E_URL,
      "set MANIFEST_E2E_URL to a manifest reachable from the API",
    );

    await loginAsAdmin();
    await openManifestTab(page);

    await page
      .locator("[data-testid='manifest-url-input']")
      .fill(process.env.MANIFEST_E2E_URL!);

    // Mantine Select: click the input to open, then pick the option from the
    // listbox portal. Options render name + template_id, so match on the id.
    await page.locator("[data-testid='manifest-template-select']").click();
    await page
      .locator("[role='option']")
      .filter({ hasText: MANIFEST_TEMPLATE_ID })
      .first()
      .click();

    // Unique name so re-runs don't 409 on the duplicate-name check.
    await page
      .locator("[data-testid='manifest-project-name-input']")
      .fill(`Manifest E2E ${new Date().toISOString().replace(/:/g, "-")}`);

    const submit = page.locator("[data-testid='create-from-manifest-submit']");

    // Source → Preview: the dry-run plan must render before advancing.
    await submit.click();
    await expect(
      page.locator("[data-testid='manifest-preview-report']"),
    ).toBeVisible({ timeout: 30_000 });

    // Preview → Create, then submit for real and expect the dashboard redirect.
    await submit.click();
    await submit.click();
    await expect(page).toHaveURL(/\/dashboard\//, { timeout: 60_000 });
  });
});
