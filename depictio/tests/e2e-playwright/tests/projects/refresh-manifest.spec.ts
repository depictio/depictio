/**
 * The "Refresh data" panel on the project detail page (ManifestRefreshPanel).
 *
 * Needs a Data Manifest reachable from the API: set MANIFEST_E2E_URL, exactly
 * like the full-flow test in create-from-manifest.spec.ts. A project is
 * created from that manifest through the UI first, then refreshed from its
 * detail page, and every manifest collection is expected to come back
 * ingested.
 */

import { APIRequestContext, Page } from "@playwright/test";
import {
  test,
  expect,
  getAuthMode,
  loginAsTestUserWithToken,
  API_URL,
  API_PREFIX,
} from "@fixtures/auth";

const MANIFEST_TEMPLATE_ID = "generic/manifest-tables/1";

/** Create a project from MANIFEST_E2E_URL via the modal. Ends either on the
 *  dashboard redirect (clean report) or on the post-create review modal
 *  (something unmatched, pruned or failed), both of which mean the project
 *  exists. */
async function createManifestProject(page: Page, name: string): Promise<void> {
  await page.goto("/projects");
  await page.locator("[data-tour-id='projects-create']").click();
  await page.getByRole("tab", { name: "From Manifest" }).click();

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
  await page.locator("[data-testid='manifest-project-name-input']").fill(name);

  const submit = page.locator("[data-testid='create-from-manifest-submit']");

  // Source -> Preview: the dry-run plan must render before advancing.
  await submit.click();
  await expect(
    page.locator("[data-testid='manifest-preview-report']"),
  ).toBeVisible({ timeout: 30_000 });

  // Preview -> Create, then submit for real.
  await submit.click();
  await submit.click();

  const reviewModal = page.locator("[data-testid='manifest-created-modal']");
  await expect
    .poll(
      async () => /\/dashboard\//.test(page.url()) || (await reviewModal.isVisible()),
      { timeout: 60_000 },
    )
    .toBe(true);
}

/** Resolve a project's id by name through the API: the create flow lands on
 *  the dashboard, which does not expose the project id. */
async function findProjectId(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<string> {
  const res = await request.get(`${API_URL}${API_PREFIX}/projects/get/all`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(res.ok(), `list projects: ${res.status()}`).toBeTruthy();
  const projects = (await res.json()) as Array<{ _id?: string; id?: string; name: string }>;
  const created = projects.find((p) => p.name === name);
  expect(created, `project "${name}" is listed after creation`).toBeTruthy();
  return (created!._id ?? created!.id) as string;
}

test.describe("Refresh a project from its Data Manifest", () => {
  // Runs for admins in standard AND single-user mode; skipped in public mode
  // (CI's public-demo leg), where the refresh endpoint refuses non-admins
  // and creating a project as admin is not the path under test.
  test.beforeEach(async () => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Manifest refresh is not exercised in public mode.");
  });

  test("re-ingests every manifest collection", async ({ page, request }) => {
    test.skip(
      !process.env.MANIFEST_E2E_URL,
      "set MANIFEST_E2E_URL to a manifest reachable from the API",
    );
    // Creation plus a worker-side refresh: allow for a cold Celery worker.
    test.setTimeout(300_000);

    const tokens = await loginAsTestUserWithToken(page, request, "adminUser");

    // Unique name so re-runs don't 409 on the duplicate-name check.
    const name = `Manifest refresh E2E ${new Date().toISOString().replace(/:/g, "-")}`;
    await createManifestProject(page, name);
    const projectId = await findProjectId(request, tokens.access_token, name);

    await page.goto(`/projects/${projectId}`);
    const panel = page.locator("[data-testid='manifest-refresh-panel']");
    await expect(panel).toBeVisible({ timeout: 15_000 });

    // Enabled once the project and the current user have loaded (the admin
    // owns the project it just created).
    const button = panel.locator("[data-testid='manifest-refresh-button']");
    await expect(button).toBeEnabled({ timeout: 15_000 });
    await button.click();

    // The status line flips to a terminal state once no row is queued or
    // running any more; a failed run still ends the wait so the rows below
    // report which collection broke.
    const status = panel.locator("[data-testid='manifest-refresh-status']");
    await expect(status).toHaveAttribute("data-state", /^(success|failed)$/, {
      timeout: 180_000,
    });
    await expect(status).toHaveAttribute("data-state", "success");

    const rows = panel.locator("[data-testid^='manifest-refresh-row-']");
    expect(await rows.count()).toBeGreaterThan(0);
    for (const row of await rows.all()) {
      await expect(row).toHaveAttribute("data-status", "ingested");
      await expect(row).toContainText("Ingested");
    }
  });
});
