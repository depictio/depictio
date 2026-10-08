/**
 * Local folder browser of the "From a run folder" tab (CreateProjectModal,
 * LocalFolderBrowserModal).
 *
 * The browser only exists when the server reads run folders from its own disk
 * (`depictio local`), which CI's stack does not do. So the capability flag is
 * switched on by rewriting the real `/auth/me/optional` answer (the session
 * stays real), and `/projects/local_dirs` and `/projects/from_run` are
 * stubbed with a small folder tree: what is under test is the walk through
 * it, the run-folder badge, and the path the field ends up with.
 */

import { Page, Route } from "@playwright/test";
import { test, expect, getAuthMode } from "@fixtures/auth";

const ROOT = "/Users/e2e";
const RUN_FOLDER = `${ROOT}/results/run42`;

/** Listing per `?path=`; the key "" is the roots listing (no path). */
const LISTINGS: Record<string, unknown> = {
  "": {
    path: null,
    root: null,
    parent: null,
    entries: [{ name: "e2e", path: ROOT, looks_like_run: false }],
    truncated: false,
  },
  [ROOT]: {
    path: ROOT,
    root: ROOT,
    parent: null,
    entries: [
      { name: "Documents", path: `${ROOT}/Documents`, looks_like_run: false },
      { name: "results", path: `${ROOT}/results`, looks_like_run: false },
    ],
    truncated: false,
  },
  [`${ROOT}/results`]: {
    path: `${ROOT}/results`,
    root: ROOT,
    parent: ROOT,
    entries: [
      { name: "run41", path: `${ROOT}/results/run41`, looks_like_run: false },
      { name: "run42", path: RUN_FOLDER, looks_like_run: true },
    ],
    truncated: false,
  },
  [RUN_FOLDER]: {
    path: RUN_FOLDER,
    root: ROOT,
    parent: `${ROOT}/results`,
    entries: [
      { name: "multiqc", path: `${RUN_FOLDER}/multiqc`, looks_like_run: false },
      { name: "pipeline_info", path: `${RUN_FOLDER}/pipeline_info`, looks_like_run: false },
    ],
    truncated: false,
  },
};

/** Pass the real `/auth/me/optional` answer through, with the local-folders
 *  flag forced to `enabled`. */
async function setLocalFolders(page: Page, enabled: boolean): Promise<void> {
  await page.route("**/api/v1/auth/me/optional**", async (route: Route) => {
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown> | null;
    await route.fulfill({
      response,
      json: { ...(body ?? {}), local_data_roots_enabled: enabled },
    });
  });
}

async function openRunTab(page: Page): Promise<void> {
  await page.goto("/projects");
  await page.locator("[data-tour-id='projects-create']").click();
  await page.getByRole("tab", { name: "From a run folder" }).click();
}

test.describe("Browse local folders for a run folder", () => {
  // Same gate as create-from-run.spec.ts: creating a project as admin is not
  // the path under test in public mode.
  test.beforeEach(async ({ page }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Project creation is not exercised in public mode.");
    await page.route("**/api/v1/projects/templates**", (route) =>
      route.fulfill({ json: { templates: [] } }),
    );
  });

  test("walks down to a run folder, selects it, and previews it", async ({
    loginAsAdmin,
    page,
  }) => {
    await setLocalFolders(page, true);
    const listed: string[] = [];
    await page.route("**/api/v1/projects/local_dirs**", (route: Route) => {
      const path = new URL(route.request().url()).searchParams.get("path") ?? "";
      listed.push(path);
      const listing = LISTINGS[path];
      if (!listing) {
        route.fulfill({ status: 404, json: { detail: "This folder does not exist." } });
        return;
      }
      route.fulfill({ json: listing });
    });
    let previewBody: { data_root?: string; template_id?: string | null } | null = null;
    await page.route("**/api/v1/projects/from_run", (route: Route) => {
      previewBody = route.request().postDataJSON();
      route.fulfill({
        status: 422,
        json: {
          detail: "The pipeline that produced this folder was not recognised.",
          code: "template_not_detected",
        },
      });
    });

    await loginAsAdmin();
    await openRunTab(page);

    // Local mode: the field takes a path, and offers the browser.
    const field = page.locator("[data-testid='run-data-root-input']");
    await expect(field).toHaveAttribute("placeholder", "~/results/run42");
    await page.locator("[data-testid='run-browse-local']").click();

    const browser = page.locator("[data-testid='local-browse-modal']");
    await expect(browser).toBeVisible();
    // The field was empty, so the walk starts at the allowed roots, where
    // there is no folder to select yet.
    const select = browser.locator("[data-testid='local-browse-select']");
    await expect(browser.locator("[data-testid='local-browse-entry-e2e']")).toBeVisible();
    await expect(select).toBeDisabled();

    // Drill down: root, results, run42. Only run42 is badged a run folder.
    await browser.locator("[data-testid='local-browse-entry-e2e']").click();
    await browser.locator("[data-testid='local-browse-entry-results']").click();
    const run41 = browser.locator("[data-testid='local-browse-entry-run41']");
    const run42 = browser.locator("[data-testid='local-browse-entry-run42']");
    await expect(run42).toHaveAttribute("data-run-folder", "true");
    await expect(run42).toContainText("run folder");
    await expect(run41).not.toHaveAttribute("data-run-folder", "true");
    await run42.click();

    // Breadcrumbs lead from the roots to the folder being listed.
    const crumbs = browser.locator("[data-testid='local-browse-breadcrumbs']");
    await expect(crumbs).toContainText("All folders");
    await expect(crumbs).toContainText(ROOT);
    await expect(crumbs).toContainText("results");
    await expect(crumbs).toContainText("run42");
    await expect(browser.locator("[data-testid='local-browse-current']")).toHaveText(
      RUN_FOLDER,
    );
    expect(listed).toEqual(["", ROOT, `${ROOT}/results`, RUN_FOLDER]);

    // A breadcrumb goes back up without losing the way down.
    await browser.locator("[data-testid='local-browse-crumb-2']").click();
    await expect(run42).toBeVisible();
    await run42.click();
    await expect(browser.locator("[data-testid='local-browse-current']")).toHaveText(
      RUN_FOLDER,
    );

    await select.click();
    await expect(browser).toBeHidden();
    await expect(field).toHaveValue(RUN_FOLDER);

    // The selected path is what the preview sends, with detection on.
    await page.locator("[data-testid='create-from-run-submit']").click();
    await expect(page.locator("[data-testid='run-template-not-detected']")).toBeVisible({
      timeout: 20_000,
    });
    expect(previewBody).toMatchObject({ data_root: RUN_FOLDER, template_id: null });
  });

  test("a folder the server refuses shows why and keeps the listing", async ({
    loginAsAdmin,
    page,
  }) => {
    await setLocalFolders(page, true);
    await page.route("**/api/v1/projects/local_dirs**", (route: Route) => {
      const path = new URL(route.request().url()).searchParams.get("path") ?? "";
      if (path === `${ROOT}/Documents`) {
        route.fulfill({
          status: 404,
          json: { detail: "This folder is outside the folders Depictio may read." },
        });
        return;
      }
      route.fulfill({ json: LISTINGS[path] ?? LISTINGS[""] });
    });

    await loginAsAdmin();
    await openRunTab(page);
    await page.locator("[data-testid='run-browse-local']").click();

    const browser = page.locator("[data-testid='local-browse-modal']");
    await browser.locator("[data-testid='local-browse-entry-e2e']").click();
    await browser.locator("[data-testid='local-browse-entry-Documents']").click();

    await expect(browser.locator("[data-testid='local-browse-error']")).toContainText(
      "outside the folders Depictio may read",
    );
    // Still on the folder above, so the reader can pick another one.
    await expect(browser.locator("[data-testid='local-browse-current']")).toHaveText(ROOT);
    await expect(
      browser.locator("[data-testid='local-browse-entry-results']"),
    ).toBeVisible();

    // Cancel leaves the field untouched.
    await browser.locator("[data-testid='local-browse-cancel']").click();
    await expect(browser).toBeHidden();
    await expect(page.locator("[data-testid='run-data-root-input']")).toHaveValue("");
  });

  test("without local folders there is no Browse button and the field wants s3://", async ({
    loginAsAdmin,
    page,
  }) => {
    await setLocalFolders(page, false);

    await loginAsAdmin();
    await openRunTab(page);

    const field = page.locator("[data-testid='run-data-root-input']");
    await expect(field).toHaveAttribute("placeholder", "s3://bucket/results/run42/");
    await expect(page.locator("[data-testid='run-browse-local']")).toHaveCount(0);

    // A local path is refused before anything is sent.
    await field.fill("~/results/run42");
    await expect(
      page.locator("[data-testid='run-submit-disabled-reason']"),
    ).toContainText("must be an s3:// location");
    await expect(page.locator("[data-testid='create-from-run-submit']")).toBeDisabled();
  });
});
