/**
 * Storage section of the project settings (StoragePanel.tsx inside
 * ProjectSettingsModal.tsx, opened from "Project settings" on /projects/{id}).
 *
 * Per-project S3 credentials for remote data collections. The secret is
 * write-only end to end: the backend stores it encrypted and only reports
 * `has_secret`, so the section shows a "Secret set" badge and an edit that
 * leaves the secret field empty keeps the stored value. The bucket is
 * required, and the connection test checks that bucket.
 *
 * The endpoint used is the instance's own S3 service (SeaweedFS, compose
 * service `s3`): the API exempts it from the gate that rejects other private
 * hosts, so this works on any stack without an allowlist. The instance's own
 * bucket is refused for project storage, and a stock stack holds no other
 * bucket, so by default the connection test is expected to report a missing
 * bucket; set PLAYWRIGHT_STORAGE_BUCKET to an existing bucket to expect a
 * working connection instead. Override via env when the stack differs:
 *   PLAYWRIGHT_STORAGE_ENDPOINT   (default http://s3:9000, as seen by the API)
 *   PLAYWRIGHT_STORAGE_BUCKET     (default depictio-e2e-storage, absent)
 *   PLAYWRIGHT_INSTANCE_BUCKET    (default depictio-bucket, the instance's own)
 *   PLAYWRIGHT_STORAGE_ACCESS_KEY / PLAYWRIGHT_STORAGE_SECRET_KEY
 *                                 (default: the committed docker-compose/.env
 *                                 S3 root credentials)
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

const STORAGE_ENDPOINT = process.env.PLAYWRIGHT_STORAGE_ENDPOINT ?? "http://s3:9000";
const STORAGE_BUCKET = process.env.PLAYWRIGHT_STORAGE_BUCKET ?? "depictio-e2e-storage";
/** Only an explicitly provided bucket is expected to exist. */
const EXPECT_CONNECTION_OK = Boolean(process.env.PLAYWRIGHT_STORAGE_BUCKET);
const INSTANCE_BUCKET = process.env.PLAYWRIGHT_INSTANCE_BUCKET ?? "depictio-bucket";
const STORAGE_ACCESS_KEY = process.env.PLAYWRIGHT_STORAGE_ACCESS_KEY ?? "depictio_dev";
const STORAGE_SECRET_KEY =
  process.env.PLAYWRIGHT_STORAGE_SECRET_KEY ?? "dev_minio_secret_x3uG7q9Wz2";

const PROJECT_URL = `/projects/${IRIS_PROJECT_ID}`;
const STORAGE_API = `${API_URL}${API_PREFIX}/projects/${IRIS_PROJECT_ID}/storage`;

/** DELETE is idempotent on the backend: 200 whether or not a config exists,
 *  404 only when the project itself is missing. */
async function clearStorage(request: APIRequestContext, token: string): Promise<number> {
  const res = await request.delete(STORAGE_API, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect([200, 404]).toContain(res.status());
  return res.status();
}

/** Open the project settings on its Storage section. */
async function openStorageSection(page: Page): Promise<void> {
  const settingsButton = page.locator("[data-testid='project-settings-button']");
  await expect(settingsButton).toBeEnabled({ timeout: 15_000 });
  await settingsButton.click();
  // The dialog remembers the last section per browser: pick Storage explicitly.
  await page.locator("[data-testid='project-settings-nav-storage']").click();
  await expect(panel(page)).toBeVisible();
}

function panel(page: Page) {
  return page.locator("[data-testid='storage-panel']");
}

test.describe("Project storage settings", () => {
  let token = "";

  test.beforeEach(async ({ page, request }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Storage credentials need a project owner account.");

    token = (await loginAsTestUserWithToken(page, request, "adminUser")).access_token;
    // Skip (not fail) on stacks without the Iris reference seed.
    test.skip(
      (await clearStorage(request, token)) === 404,
      "Iris reference project not seeded in this stack.",
    );
    await page.goto(PROJECT_URL);
    await openStorageSection(page);

    // Fresh state: nothing configured, the configure affordance is offered
    // (enabled once the current user is known to own the project).
    await expect(page.locator("[data-testid='storage-configure-button']")).toBeEnabled({
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
    const saveButton = page.locator("[data-testid='storage-save-button']");

    // Configure: endpoint, bucket and credentials.
    await page.locator("[data-testid='storage-configure-button']").click();
    await page.locator("[data-testid='storage-endpoint-input']").fill(STORAGE_ENDPOINT);
    await page.locator("[data-testid='storage-bucket-input']").fill(STORAGE_BUCKET);
    await page.locator("[data-testid='storage-access-key-input']").fill(STORAGE_ACCESS_KEY);
    await page.locator("[data-testid='storage-secret-input']").fill(STORAGE_SECRET_KEY);
    await saveButton.click();

    // Configured state: badge, bucket, and the owner actions. The endpoint
    // sits in the folded connection details.
    await expect(storagePanel.getByText("Secret set")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("[data-testid='storage-bucket-value']")).toHaveText(STORAGE_BUCKET);
    await page.locator("[data-testid='storage-details-toggle']").click();
    await expect(storagePanel.getByText(STORAGE_ENDPOINT)).toBeVisible();
    await expect(page.locator("[data-testid='storage-test-button']")).toBeEnabled();

    // Edit without retyping the secret: the field advertises "unchanged" and
    // saving with it empty keeps the stored secret (write-only semantics).
    await page.locator("[data-testid='storage-edit-button']").click();
    const secretInput = page.locator("[data-testid='storage-secret-input']");
    await expect(secretInput).toHaveAttribute("placeholder", "unchanged");
    await expect(secretInput).toHaveValue("");
    // The bucket is required: an empty one is refused before anything is sent.
    const bucketInput = page.locator("[data-testid='storage-bucket-input']");
    await bucketInput.fill("");
    await saveButton.click();
    await expect(storagePanel.getByText("Enter the bucket name.")).toBeVisible();
    await bucketInput.fill(STORAGE_BUCKET);
    await saveButton.click();
    await expect(storagePanel.getByText("Secret set")).toBeVisible({ timeout: 10_000 });
    await expect(storagePanel.getByText("No secret")).toHaveCount(0);

    // The stored credentials reach the instance's object store, and the
    // outcome (a working connection, or a bucket that is not there) is shown
    // in the section rather than only as a toast.
    await page.locator("[data-testid='storage-test-button']").click();
    const result = page.locator("[data-testid='storage-test-result']");
    await expect(result).toHaveAttribute(
      "data-success",
      EXPECT_CONNECTION_OK ? "true" : "false",
      { timeout: 20_000 },
    );
    if (EXPECT_CONNECTION_OK) await expect(result).toContainText("Storage connection OK");

    // Remove: confirm inline, the section returns to the unconfigured state.
    await page.locator("[data-testid='storage-remove-button']").click();
    await expect(page.locator("[data-testid='storage-remove-confirm']")).toBeVisible();
    await page.locator("[data-testid='storage-remove-confirm-button']").click();
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
    await page.locator("[data-testid='storage-bucket-input']").fill(STORAGE_BUCKET);
    await page.locator("[data-testid='storage-save-button']").click();

    await expect(page.locator("[data-testid='storage-save-error']")).toContainText(
      /non-public|rejected|allowlist|not allowed/i,
      { timeout: 10_000 },
    );
    // Still in the form, nothing saved.
    await expect(page.locator("[data-testid='storage-endpoint-input']")).toBeVisible();
    await expect(panel(page).getByText("Secret set")).toHaveCount(0);
  });

  test("refuses the instance's own bucket", async ({ page }) => {
    // Every project's data lives in that bucket: project keys pointed at it
    // would read other projects' tables, so the API refuses it on save.
    await page.locator("[data-testid='storage-configure-button']").click();
    await page.locator("[data-testid='storage-endpoint-input']").fill(STORAGE_ENDPOINT);
    await page.locator("[data-testid='storage-bucket-input']").fill(INSTANCE_BUCKET);
    await page.locator("[data-testid='storage-access-key-input']").fill(STORAGE_ACCESS_KEY);
    await page.locator("[data-testid='storage-secret-input']").fill(STORAGE_SECRET_KEY);
    await page.locator("[data-testid='storage-save-button']").click();

    await expect(page.locator("[data-testid='storage-save-error']")).toContainText(
      INSTANCE_BUCKET,
      { timeout: 10_000 },
    );
    await expect(page.locator("[data-testid='storage-bucket-input']")).toBeVisible();
    await expect(panel(page).getByText("Secret set")).toHaveCount(0);
  });
});
