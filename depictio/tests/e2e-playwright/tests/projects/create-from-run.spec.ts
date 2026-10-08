/**
 * "From a run folder" project creation (CreateProjectModal, run tab).
 *
 * Every test drives the real UI against a stubbed `/projects/from_run` (and,
 * for the create flow, a stubbed poll endpoint): the flow's value is what it
 * shows the user (the template it recognised, the per-collection plan, the
 * paths that were not found, the live ingestion run), and none of that needs
 * a real S3 bucket to exercise. The template listing is stubbed too so the
 * picker holds a known option whatever templates the deployment ships.
 */

import { Page, Route } from "@playwright/test";
import { test, expect, getAuthMode } from "@fixtures/auth";

const TEMPLATE_ID = "nf-core/ampliseq/2.16.0";
const DATA_ROOT = "s3://depictio-e2e/ampliseq/run-42";

/** A template listing with one NON manifest-capable entry: the run tab must
 *  offer exactly the templates the manifest tab filters out. */
const TEMPLATES = {
  templates: [
    {
      template_id: TEMPLATE_ID,
      name: "Ampliseq Microbial Community Analysis",
      description: "nf-core/ampliseq amplicon sequencing template",
      version: "1.1.0",
      manifest_capable: false,
      variables: [
        {
          name: "DATA_ROOT",
          description: "Root directory containing ampliseq output",
          required: true,
          default: null,
        },
        {
          name: "GROUP_COL",
          description: "Metadata column for grouping",
          required: false,
          default: null,
        },
      ],
      dashboards: ["dashboards/base.yaml"],
    },
  ],
};

function dcRow(overrides: Record<string, unknown>) {
  return {
    data_collection_tag: "unnamed",
    kind: "scan",
    mode: "s3_prefix",
    location: `${DATA_ROOT}/somewhere`,
    matched: 0,
    missing_sources: [],
    optional: false,
    status: "ok",
    ...overrides,
  };
}

function report(overrides: Record<string, unknown>) {
  return {
    project_id: null,
    project_name: "Ampliseq Microbial Community Analysis",
    template_id: TEMPLATE_ID,
    detected_template: null,
    data_root: DATA_ROOT,
    detected_runs: ["run_1", "run_2"],
    resolved_variables: { DATA_ROOT, GROUP_COL: "habitat" },
    data_collections: [],
    dashboards: [],
    pruned_optional_dcs: [],
    truncated: false,
    run_id: null,
    dry_run: true,
    success: true,
    ...overrides,
  };
}

/** Two collections that found their inputs and one optional one the
 *  template pruned. */
const MATCHED_COLLECTIONS = [
  dcRow({
    data_collection_tag: "multiqc_data",
    location: `${DATA_ROOT}/multiqc`,
    matched: 1,
    status: "ok",
  }),
  dcRow({
    data_collection_tag: "asv_table",
    kind: "recipe",
    mode: null,
    location: `${DATA_ROOT}/qiime2`,
    matched: 3,
    status: "ok",
  }),
  dcRow({
    data_collection_tag: "metadata",
    location: `${DATA_ROOT}/input`,
    matched: 0,
    optional: true,
    status: "pruned",
  }),
];

/** Open /projects, launch the create modal, switch to the run tab and fill in
 *  the run folder, plus the template unless `detect` keeps the default
 *  "Detect from the folder" choice. Leaves the project name empty so nothing
 *  collides with the deployment's existing projects. */
async function openRunTab(page: Page, { detect = false } = {}): Promise<void> {
  await page.goto("/projects");
  await page.locator("[data-tour-id='projects-create']").click();
  await page.getByRole("tab", { name: "From a run folder" }).click();

  const select = page.locator("[data-testid='run-template-select']");
  // Detection is the default choice, so nothing has to be picked for it.
  await expect(select).toHaveValue("Detect from the folder");
  if (!detect) {
    // Mantine Select: click the input to open, then pick the option from the
    // listbox portal. Options render name + template_id, so match on the id.
    await select.click();
    await page
      .locator("[role='option']")
      .filter({ hasText: TEMPLATE_ID })
      .first()
      .click();
  }
  await page.locator("[data-testid='run-data-root-input']").fill(DATA_ROOT);
}

test.describe("Create project from a run folder", () => {
  // Runs for admins in standard AND single-user mode; skipped in public mode
  // (CI's public-demo leg), where creating a project as admin is not the
  // path under test. Same probe as create-from-manifest.spec.ts.
  test.beforeEach(async ({ page }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Project creation is not exercised in public mode.");
    await page.route("**/api/v1/projects/templates**", (route) =>
      route.fulfill({ json: TEMPLATES }),
    );
  });

  test("preview names the missing sources and blocks Create when nothing matched", async ({
    loginAsAdmin,
    page,
  }) => {
    // The wrong-prefix case: the run folder is one level too high, so every
    // collection resolves to a path that does not exist.
    await page.route("**/api/v1/projects/from_run", (route: Route) =>
      route.fulfill({
        json: report({
          data_collections: [
            dcRow({
              data_collection_tag: "multiqc_data",
              location: `${DATA_ROOT}/multiqc`,
              status: "missing",
              missing_sources: [`${DATA_ROOT}/multiqc/multiqc_data/multiqc.parquet`],
            }),
            dcRow({
              data_collection_tag: "asv_table",
              kind: "recipe",
              mode: null,
              location: `${DATA_ROOT}/qiime2`,
              status: "missing",
              missing_sources: [
                `${DATA_ROOT}/qiime2/abundance_tables/feature-table.tsv`,
                `${DATA_ROOT}/qiime2/rel_abundance_tables/rel-table-ASV.tsv`,
              ],
            }),
          ],
          truncated: true,
        }),
      }),
    );

    await loginAsAdmin();
    await openRunTab(page);

    const submit = page.locator("[data-testid='create-from-run-submit']");
    await submit.click();

    const preview = page.locator("[data-testid='run-preview-report']");
    await expect(preview).toBeVisible({ timeout: 20_000 });

    // A row per data collection, each carrying its resolved status.
    await expect(
      preview.locator("[data-testid='run-preview-row-multiqc_data']"),
    ).toHaveAttribute("data-status", "missing");
    await expect(
      preview.locator("[data-testid='run-preview-row-asv_table']"),
    ).toHaveAttribute("data-status", "missing");

    // The point of the screen: every path the server looked for, in full.
    const missing = preview.locator("[data-testid='run-missing-sources-asv_table']");
    await expect(missing).toContainText(
      `${DATA_ROOT}/qiime2/abundance_tables/feature-table.tsv`,
    );
    await expect(missing).toContainText(
      `${DATA_ROOT}/qiime2/rel_abundance_tables/rel-table-ASV.tsv`,
    );
    await expect(
      preview.locator("[data-testid='run-missing-sources-multiqc_data']"),
    ).toContainText(`${DATA_ROOT}/multiqc/multiqc_data/multiqc.parquet`);

    // Resolved variables and detected runs are on the screen too.
    await expect(
      preview.locator("[data-testid='run-resolved-variables']"),
    ).toContainText("GROUP_COL = habitat");
    await expect(preview).toContainText("run_1");

    // A truncated listing says the counts are a lower bound.
    await expect(
      preview.locator("[data-testid='run-truncated-warning']"),
    ).toBeVisible();

    // Nothing matched, so Create is refused with the reason visible.
    await expect(page.locator("[data-testid='run-no-match-warning']")).toBeVisible();
    await expect(submit).toBeDisabled();
    await expect(
      page.locator("[data-testid='run-submit-disabled-reason']"),
    ).toContainText("No data collection matched anything in this folder");
  });

  test("recognises the template from the folder and pre-selects it", async ({
    loginAsAdmin,
    page,
  }) => {
    const sentTemplates: Array<string | null> = [];
    await page.route("**/api/v1/projects/from_run", (route: Route) => {
      const body = route.request().postDataJSON() as { template_id?: string | null };
      const templateId = body?.template_id ?? null;
      sentTemplates.push(templateId);
      route.fulfill({
        json: report({
          data_collections: MATCHED_COLLECTIONS,
          // Set only when the server ran detection, i.e. no template was sent.
          detected_template:
            templateId === null
              ? {
                  template_id: TEMPLATE_ID,
                  pipeline: "nf-core/ampliseq",
                  version: "2.16.0",
                  engine: "nextflow",
                }
              : null,
        }),
      });
    });

    await loginAsAdmin();
    await openRunTab(page, { detect: true });

    const submit = page.locator("[data-testid='create-from-run-submit']");
    await submit.click();

    // The preview asked the server to detect, and says what it recognised.
    const detected = page.locator("[data-testid='run-detected-template']");
    await expect(detected).toBeVisible({ timeout: 20_000 });
    expect(sentTemplates[0], "detection sends no template").toBeNull();
    await expect(detected.locator("[data-testid='run-detected-pipeline']")).toHaveText(
      "nf-core/ampliseq",
    );
    await expect(detected.locator("[data-testid='run-detected-version']")).toHaveText(
      "2.16.0",
    );
    await expect(detected.locator("[data-testid='run-detected-engine']")).toHaveText(
      "nextflow",
    );
    await expect(
      detected.locator("[data-testid='run-detected-template-id']"),
    ).toHaveText(TEMPLATE_ID);
    await expect(submit).toBeEnabled();

    // Back on the first step the recognised template is the choice, and it
    // stays editable.
    await page.locator("[data-testid='run-previous']").click();
    const select = page.locator("[data-testid='run-template-select']");
    await expect(select).toHaveValue("Ampliseq Microbial Community Analysis");
    await expect(select).toBeEditable();

    // The next preview uses that template rather than detecting again.
    await submit.click();
    await expect(page.locator("[data-testid='run-preview-report']")).toBeVisible({
      timeout: 20_000,
    });
    await expect.poll(() => sentTemplates.length).toBe(2);
    expect(sentTemplates[1]).toBe(TEMPLATE_ID);
    await expect(page.locator("[data-testid='run-detected-template']")).toHaveCount(0);

    // A different folder may hold another pipeline: the choice detection made
    // goes back to detecting.
    await page.locator("[data-testid='run-previous']").click();
    await page.locator("[data-testid='run-data-root-input']").fill(`${DATA_ROOT}-bis`);
    await expect(select).toHaveValue("Detect from the folder");
  });

  test("an unrecognised folder asks for a template instead of failing", async ({
    loginAsAdmin,
    page,
  }) => {
    await page.route("**/api/v1/projects/from_run", (route: Route) =>
      route.fulfill({
        status: 422,
        json: {
          detail:
            "No installed template matches the pipeline that produced this folder.",
          code: "template_not_detected",
        },
      }),
    );

    await loginAsAdmin();
    await openRunTab(page, { detect: true });

    const submit = page.locator("[data-testid='create-from-run-submit']");
    await submit.click();

    const notDetected = page.locator("[data-testid='run-template-not-detected']");
    await expect(notDetected).toBeVisible({ timeout: 20_000 });
    await expect(notDetected).toContainText("No installed template matches");
    // Not shown as a read failure: the folder was read, only the template is
    // missing.
    await expect(page.locator("[data-testid='run-preview-error']")).toHaveCount(0);
    await expect(submit).toBeDisabled();
    await expect(
      page.locator("[data-testid='run-submit-disabled-reason']"),
    ).toContainText("pick a template");

    // The way out leads back to the template picker, still on detection.
    await notDetected.locator("[data-testid='run-pick-template']").click();
    const select = page.locator("[data-testid='run-template-select']");
    await expect(select).toBeVisible();
    await expect(select).toHaveValue("Detect from the folder");
  });

  test("creates the project and watches the ingestion run finish", async ({
    loginAsAdmin,
    page,
  }) => {
    const RUN_ID = "run-abc123";
    const DASHBOARD_ID = "665f0f3c1e4a2d7f8e5b8ca9";
    const matchedCollections = MATCHED_COLLECTIONS;

    let created = false;
    let createdWithTemplate: string | null | undefined;
    await page.route("**/api/v1/projects/from_run", (route: Route) => {
      const body = route.request().postDataJSON() as {
        dry_run?: boolean;
        template_id?: string | null;
      };
      if (body?.dry_run) {
        route.fulfill({ json: report({ data_collections: matchedCollections }) });
        return;
      }
      created = true;
      createdWithTemplate = body?.template_id;
      route.fulfill({
        json: report({
          project_id: "665f0f3c1e4a2d7f8e5b8ca1",
          data_collections: matchedCollections,
          dashboards: [
            {
              path: "dashboards/base.yaml",
              success: true,
              dashboard_id: DASHBOARD_ID,
              title: "Ampliseq overview",
              error: null,
            },
          ],
          pruned_optional_dcs: ["metadata"],
          run_id: RUN_ID,
          dry_run: false,
        }),
      });
    });

    // The run is dispatched first and ingested on the next poll, so the modal
    // has to move from "running" to a terminal state on its own.
    let polls = 0;
    await page.route(`**/api/v1/projects/refresh_manifest/${RUN_ID}`, (route: Route) => {
      polls += 1;
      const done = polls > 1;
      route.fulfill({
        json: {
          project_id: "665f0f3c1e4a2d7f8e5b8ca1",
          refreshed: ["multiqc_data", "asv_table"].map((tag) => ({
            data_collection_tag: tag,
            data_collection_id: null,
            entries: done ? 3 : 0,
            status: done ? "ingested" : "dispatched",
            message: null,
          })),
          run_id: RUN_ID,
          dry_run: false,
          success: done,
        },
      });
    });

    await loginAsAdmin();
    await openRunTab(page);

    const submit = page.locator("[data-testid='create-from-run-submit']");

    // Source -> Preview: the dry-run plan must render before advancing.
    await submit.click();
    await expect(page.locator("[data-testid='run-preview-report']")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.locator("[data-testid='run-match-summary']")).toContainText(
      "2 of 2 collections matched",
    );
    await expect(submit).toBeEnabled();

    // Preview -> Create, then create for real.
    await submit.click();
    await submit.click();

    // No redirect: the project exists but its collections are still ingesting,
    // so the user stays here and watches the run.
    const modal = page.locator("[data-testid='run-created-modal']");
    await expect(modal).toBeVisible({ timeout: 20_000 });
    expect(created, "the real (non dry-run) create was sent").toBe(true);
    // An explicitly picked template is sent as is.
    expect(createdWithTemplate).toBe(TEMPLATE_ID);
    await expect(page).not.toHaveURL(/\/dashboard\//);

    const status = modal.locator("[data-testid='run-created-status']");
    await expect(status).toHaveAttribute("data-state", "running");
    await expect(status).toHaveAttribute("data-state", "success", {
      timeout: 30_000,
    });

    for (const tag of ["multiqc_data", "asv_table"]) {
      await expect(
        modal.locator(`[data-testid='run-progress-row-${tag}']`),
      ).toHaveAttribute("data-status", "ingested");
    }

    // The imported dashboard is reachable once the user chooses to go there.
    await expect(
      modal.locator("[data-testid='run-created-open-dashboard']"),
    ).toBeEnabled();
  });
});
