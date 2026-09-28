/**
 * "From a run folder" project creation (CreateProjectModal, run tab).
 *
 * Both tests drive the real UI against a stubbed `/projects/from_run` and a
 * stubbed poll endpoint: the flow's value is what it shows the user (the
 * per-collection plan, the paths that were not found, the live ingestion
 * run), and none of that needs a real S3 bucket to exercise. The template
 * listing is stubbed too so the picker holds a known option whatever
 * templates the deployment ships.
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

/** Open /projects, launch the create modal, switch to the run tab and fill in
 *  the template plus the run folder. Leaves the project name empty so nothing
 *  collides with the deployment's existing projects. */
async function openRunTab(page: Page): Promise<void> {
  await page.goto("/projects");
  await page.locator("[data-tour-id='projects-create']").click();
  await page.getByRole("tab", { name: "From a run folder" }).click();

  // Mantine Select: click the input to open, then pick the option from the
  // listbox portal. Options render name + template_id, so match on the id.
  await page.locator("[data-testid='run-template-select']").click();
  await page
    .locator("[role='option']")
    .filter({ hasText: TEMPLATE_ID })
    .first()
    .click();
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
    ).toContainText("No data collection matched anything under this prefix");
  });

  test("creates the project and watches the ingestion run finish", async ({
    loginAsAdmin,
    page,
  }) => {
    const RUN_ID = "run-abc123";
    const DASHBOARD_ID = "665f0f3c1e4a2d7f8e5b8ca9";
    const matchedCollections = [
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

    let created = false;
    await page.route("**/api/v1/projects/from_run", (route: Route) => {
      const body = route.request().postDataJSON() as { dry_run?: boolean };
      if (body?.dry_run) {
        route.fulfill({ json: report({ data_collections: matchedCollections }) });
        return;
      }
      created = true;
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
