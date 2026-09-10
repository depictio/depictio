/**
 * Project storage panel (StoragePanel.tsx on /projects/{id}).
 *
 * Per-project S3 credentials for remote data collections. The secret is
 * write-only end to end: the backend stores it encrypted and only reports
 * `has_secret`, so the panel shows a "Secret set" badge and an edit that
 * leaves the secret field empty keeps the stored value.
 *
 * The endpoint used is the instance's own MinIO: the API exempts it from the
 * SSRF gate that rejects other private hosts, so this works on any stack
 * without an allowlist. Override via env when the stack differs:
 *   PLAYWRIGHT_STORAGE_ENDPOINT   (default http://minio:9000, as seen by the API)
 *   PLAYWRIGHT_STORAGE_ACCESS_KEY / PLAYWRIGHT_STORAGE_SECRET_KEY
 *                                 (default: the committed docker-compose/.env
 *                                 MinIO root credentials)
 *
 * Runs for admins in standard AND single-user mode; skipped in public mode
 * (temporary users own no project). Targets the seeded Iris project and
 * skips when that seed is absent, like project-permissions.spec.ts.
 */

import { Page, APIRequestContext } from "@playwright/test";
import {
  test,
  expect,
  getAuthMode,
  loginAsTestUserWithToken,
  API_URL,
  API_PREFIX,
} from "@fixtures/auth";
import { IRIS_PROJECT_ID } from "@fixtures/projects";

const STORAGE_ENDPOINT = process.env.PLAYWRIGHT_STORAGE_ENDPOINT ?? "http://minio:9000";
const STORAGE_ACCESS_KEY = process.env.PLAYWRIGHT_STORAGE_ACCESS_KEY ?? "depictio_dev";
const STORAGE_SECRET_KEY =
  process.env.PLAYWRIGHT_STORAGE_SECRET_KEY ?? "dev_minio_secret_x3uG7q9Wz2";

const PROJECT_URL = `/projects/${IRIS_PROJECT_ID}`;
const STORAGE_API = `${API_URL}${API_PREFIX}/projects/${IRIS_PROJECT_ID}/storage`;

/** DELETE is idempotent on the backend: 200 whether or not a config exists. */
async function clearStorage(request: APIRequestContext, token: string): Promise<void> {
  const res = await request.delete(STORAGE_API, {
    headers: { Authorization: `Bearer ${token}` },
  });
  // 404 only when the project itself is missing; the seed check below skips then.
  expect([200, 404]).toContain(res.status());
}

function panel(page: Page) {
  return page.locator("[data-testid='storage-panel']");
}

test.describe("Project storage panel", () => {
  let token = "";

  test.beforeEach(async ({ page, request }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Storage credentials need a project owner account.");

    token = (await loginAsTestUserWithToken(page, request, "adminUser")).access_token;
    await clearStorage(request, token);
    await page.goto(PROJECT_URL);

    // Skip (not fail) on stacks without the Iris reference seed.
    const loadError = page.getByText(/failed to load|back to projects/i);
    await expect(panel(page).or(loadError).first()).toBeVisible({ timeout: 15_000 });
    test.skip(
      !(await panel(page).isVisible()),
      "Iris reference project not seeded in this stack.",
    );
    // Fresh state: nothing configured, the configure affordance is offered.
    await expect(page.locator("[data-testid='storage-configure-button']")).toBeVisible({
      timeout: 15_000,
    });
  });

  test.afterEach(async ({ request }) => {
    if (token) await clearStorage(request, token);
  });

  test("configures the instance endpoint, keeps the secret on edit, then removes it", async ({
    page,
  }) => {
    const storagePanel = panel(page);

    // Configure: endpoint + credentials.
    await page.locator("[data-testid='storage-configure-button']").click();
    await page.locator("[data-testid='storage-endpoint-input']").fill(STORAGE_ENDPOINT);
    await storagePanel.getByLabel("Access key ID").fill(STORAGE_ACCESS_KEY);
    await page.locator("[data-testid='storage-secret-input']").fill(STORAGE_SECRET_KEY);
    await page.locator("[data-testid='storage-save-button']").click();

    // Configured state: badge, summary row, and the owner actions.
    await expect(storagePanel.getByText("Secret set")).toBeVisible({ timeout: 10_000 });
    await expect(storagePanel.getByText(STORAGE_ENDPOINT)).toBeVisible();
    await expect(page.locator("[data-testid='storage-test-button']")).toBeEnabled();

    // Edit without retyping the secret: the field advertises "unchanged" and
    // saving with it empty keeps the stored secret (write-only semantics).
    await storagePanel.getByRole("button", { name: "Edit" }).click();
    const secretInput = page.locator("[data-testid='storage-secret-input']");
    await expect(secretInput).toHaveAttribute("placeholder", "unchanged");
    await expect(secretInput).toHaveValue("");
    await storagePanel.getByLabel("Bucket").fill("");
    await page.locator("[data-testid='storage-save-button']").click();
    await expect(storagePanel.getByText("Secret set")).toBeVisible({ timeout: 10_000 });
    await expect(storagePanel.getByText("No secret")).toHaveCount(0);

    // The stored credentials reach the instance's own object store.
    await page.locator("[data-testid='storage-test-button']").click();
    await expect(page.getByText("Storage connection OK")).toBeVisible({ timeout: 20_000 });

    // Remove: confirm in the modal, panel returns to the unconfigured state.
    await storagePanel.getByRole("button", { name: "Remove" }).click();
    const confirm = page.getByRole("dialog", { name: "Remove storage configuration?" });
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Remove" }).click();
    await expect(page.locator("[data-testid='storage-configure-button']")).toBeVisible({
      timeout: 10_000,
    });
    await expect(storagePanel.getByText("Secret set")).toHaveCount(0);
    await expect(storagePanel.getByText(STORAGE_ENDPOINT)).toHaveCount(0);
  });

  test("surfaces the backend rejection of a private endpoint inline", async ({ page }) => {
    // A private address that is not the instance's own endpoint: the API's
    // host gating refuses it (either the private-range rule or, on stacks
    // running with an allowlist, the allowlist rule) and the form shows why.
    await page.locator("[data-testid='storage-configure-button']").click();
    await page.locator("[data-testid='storage-endpoint-input']").fill("http://10.0.0.5:9000");
    await page.locator("[data-testid='storage-save-button']").click();

    await expect(panel(page).getByRole("alert")).toContainText(
      /non-public|rejected|allowlist|not allowed/i,
      { timeout: 10_000 },
    );
    // Still in the form, nothing saved.
    await expect(page.locator("[data-testid='storage-endpoint-input']")).toBeVisible();
    await expect(panel(page).getByText("Secret set")).toHaveCount(0);
  });
});
