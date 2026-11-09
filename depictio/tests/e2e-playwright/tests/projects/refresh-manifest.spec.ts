/**
 * The Data refresh section of the project settings (ManifestRefreshPanel
 * inside ProjectSettingsModal, opened from "Project settings" on the project
 * detail page).
 *
 * Needs a Data Manifest reachable from the API: set MANIFEST_E2E_URL, exactly
 * A project is created from that manifest through the API first, then
 * refreshed from its settings, and every manifest collection is expected to come back ingested.
 */

import { APIRequestContext } from "@playwright/test";
import {
  test,
  expect,
  getAuthMode,
  loginAsTestUserWithToken,
  API_URL,
  API_PREFIX,
} from "@fixtures/auth";

const MANIFEST_TEMPLATE_ID = "generic/manifest-tables/1";

/** Create a project from MANIFEST_E2E_URL through the API: the new-project
 *  dialog does not offer manifests, the route and the refresh stay. */
async function createManifestProject(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<void> {
  const res = await request.post(`${API_URL}${API_PREFIX}/projects/from_manifest`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      manifest_url: process.env.MANIFEST_E2E_URL,
      template_id: MANIFEST_TEMPLATE_ID,
      project_name: name,
    },
    timeout: 120_000,
  });
  expect(res.ok(), `create from manifest: ${res.status()}`).toBeTruthy();
}

/** Resolve a project's id by name through the API: the creation report
 *  is not read here. */
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
    await createManifestProject(request, tokens.access_token, name);
    const projectId = await findProjectId(request, tokens.access_token, name);

    await page.goto(`/projects/${projectId}`);
    const settingsButton = page.locator("[data-testid='project-settings-button']");
    await expect(settingsButton).toBeEnabled({ timeout: 15_000 });
    await settingsButton.click();
    // The dialog remembers the last section per browser: pick it explicitly.
    await page.locator("[data-testid='project-settings-nav-refresh']").click();
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
