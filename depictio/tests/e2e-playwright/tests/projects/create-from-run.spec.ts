/**
 * "From a run folder" project creation (CreateProjectModal, run tab).
 *
 * Every test drives the real UI against stubbed folder reads
 * (`/projects/folder_inspect`), a stubbed `/projects/from_run` and, for the
 * create flow, a stubbed poll endpoint: the flow's value is what it shows the
 * user (which pipeline and version made the run, which template is used and
 * how well it matches, the per-collection plan, the paths that were not
 * found, the live ingestion run), and none of that needs a real S3 bucket.
 * The template catalog is stubbed too, so the picker holds the same
 * pipelines and versions whatever the deployment ships.
 */

import { Page, Route } from "@playwright/test";
import { test, expect, getAuthMode } from "@fixtures/auth";
import {
  AMPLISEQ,
  detected,
  inspection,
  mockTemplates,
  openRunTab,
  setRunFolderFlags,
  stubByParam,
} from "@fixtures/runFolder";

const TEMPLATE_ID = "nf-core/ampliseq/2.16.0";
const DATA_ROOT = "s3://depictio-e2e/ampliseq/run-42";

/** The run folder as `folder_inspect` reads it: an nf-core/ampliseq 2.16.0
 *  run, for which the catalog has a template of the same version. */
const AMPLISEQ_RUN = inspection(DATA_ROOT, {
  looks_like_run: true,
  markers: ["pipeline_info", "multiqc"],
  folders: { count: 4, names: ["input", "multiqc", "pipeline_info", "qiime2"] },
  detected: detected(),
});

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
    project_name: AMPLISEQ,
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

/** Stub `/projects/from_run`, answering every call with `answer(body)`.
 *  Returns the request bodies, in order. */
async function stubFromRun(
  page: Page,
  answer: (body: { template_id?: string | null; dry_run?: boolean }) => {
    status?: number;
    json: unknown;
  },
): Promise<Array<{ template_id?: string | null; dry_run?: boolean }>> {
  const bodies: Array<{ template_id?: string | null; dry_run?: boolean }> = [];
  await page.route("**/api/v1/projects/from_run", (route: Route) => {
    const body = (route.request().postDataJSON() ?? {}) as {
      template_id?: string | null;
      dry_run?: boolean;
    };
    bodies.push(body);
    const { status, json } = answer(body);
    return route.fulfill({ status: status ?? 200, json });
  });
  return bodies;
}

/** Open the run tab and type the run folder; the tab reads it on its own. */
async function openWithFolder(page: Page, folder = DATA_ROOT): Promise<void> {
  await openRunTab(page);
  await page.locator("[data-testid='run-data-root-input']").fill(folder);
}

const versionRadio = (page: Page, templateId: string) =>
  page.locator(`[data-testid='run-version-control'] input[value='${templateId}']`);

test.describe("Create project from a run folder", () => {
  // Runs for admins in standard AND single-user mode; skipped in public mode
  // (CI's public-demo leg), where creating a project as admin is not the
  // path under test. Same probe as create-from-manifest.spec.ts.
  test.beforeEach(async ({ page }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Project creation is not exercised in public mode.");
    await mockTemplates(page);
    // The folder browser has its own spec; here the field is typed.
    await setRunFolderFlags(page, { local: false, remote: false });
  });

  test("reads the folder as it is typed and fills in the pipeline and template version", async ({
    loginAsAdmin,
    page,
  }) => {
    await stubByParam(page, "**/api/v1/projects/folder_inspect**", "location", {
      [DATA_ROOT]: { json: AMPLISEQ_RUN },
    });
    const bodies = await stubFromRun(page, (body) => ({
      json: report({
        template_id: body.template_id ?? TEMPLATE_ID,
        data_collections: MATCHED_COLLECTIONS,
      }),
    }));

    await loginAsAdmin();
    await openRunTab(page);

    // Nothing typed: no detection card, the pipeline is left to detection.
    const card = page.locator("[data-testid='run-detection-card']");
    await expect(card).toHaveCount(0);
    const pipelineSelect = page.locator("[data-testid='run-pipeline-select']");
    await expect(pipelineSelect).toHaveValue("");
    await expect(page.locator("[data-testid='run-version-empty']")).toBeVisible();
    await expect(page.locator("[data-testid='run-browse-local']")).toHaveCount(0);

    await page.locator("[data-testid='run-data-root-input']").fill(DATA_ROOT);

    // The card says what made the run and which template is used, each
    // version on its own side.
    await expect(card).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
    await expect(card.locator("[data-testid='run-detected-pipeline']")).toHaveText(
      "nf-core/ampliseq",
    );
    await expect(card.locator("[data-testid='run-detected-version']")).toHaveText("v2.16.0");
    await expect(card.locator("[data-testid='run-detected-engine']")).toHaveText("Nextflow");
    await expect(card.locator("[data-testid='run-detected-template']")).toHaveText(AMPLISEQ);
    await expect(card.locator("[data-testid='run-detected-template']")).toHaveAttribute(
      "data-template-id",
      TEMPLATE_ID,
    );
    await expect(card.locator("[data-testid='run-detected-template-version']")).toHaveText(
      "v2.16.0",
    );
    const match = card.locator("[data-testid='run-detected-match']");
    await expect(match).toHaveAttribute("data-match", "exact");
    await expect(match).toHaveText("Exact match");
    await expect(card).toContainText("Pipeline version of the run");
    await expect(card).toContainText("Template version: the pipeline version it was written for");

    // Both fields are filled in from the folder and say so.
    await expect(pipelineSelect).toHaveValue(AMPLISEQ);
    await expect(page.locator("[data-testid='run-pipeline-detected']")).toBeVisible();
    await expect(page.locator("[data-testid='run-version-detected']")).toBeVisible();
    await expect(versionRadio(page, TEMPLATE_ID)).toBeChecked();

    // Versions newest first; the latest and the run's own version marked.
    const options = page.locator("[data-testid^='run-version-option-']");
    await expect(options).toHaveCount(3);
    expect(
      await options.evaluateAll((els) => els.map((el) => el.getAttribute("data-testid"))),
    ).toEqual([
      "run-version-option-2.18.0",
      "run-version-option-2.16.0",
      "run-version-option-2.14.0",
    ]);
    await expect(page.locator("[data-testid='run-version-option-2.18.0']")).toContainText(
      "Latest",
    );
    await expect(page.locator("[data-testid='run-version-option-2.16.0']")).toContainText(
      "Matches this run",
    );
    await expect(page.locator("[data-testid='run-version-option-2.14.0']")).not.toContainText(
      "Matches this run",
    );

    // One entry per pipeline, grouped by source; a manifest-only template is
    // not offered for a run folder.
    await pipelineSelect.click();
    const listbox = page.getByRole("listbox");
    await expect(
      listbox.locator("[data-testid='run-pipeline-option-nf-core/ampliseq']"),
    ).toHaveCount(1);
    await expect(listbox.locator("[data-testid='run-pipeline-option-nf-core/ampliseq']")).toContainText(
      "3 versions",
    );
    await expect(listbox.locator("[data-testid='run-pipeline-option-nf-core/rnaseq']")).toBeVisible();
    await expect(
      listbox.locator("[data-testid='run-pipeline-option-generic/folder-tables']"),
    ).toBeVisible();
    await expect(listbox).not.toContainText("Manifest Tables");
    const groupLabels = listbox.locator("[class*='groupLabel']");
    await expect(groupLabels).toHaveText(["nf-core", "Generic"]);
    // Close the dropdown without picking anything.
    await card.click();
    await expect(listbox).toBeHidden();

    // The preview uses the template detection filled in.
    const submit = page.locator("[data-testid='create-from-run-submit']");
    await submit.click();
    await expect(page.locator("[data-testid='run-preview-report']")).toBeVisible({
      timeout: 20_000,
    });
    expect(bodies[0]?.template_id).toBe(TEMPLATE_ID);
    await expect(page.locator("[data-testid='run-summary-match']")).toHaveAttribute(
      "data-match",
      "exact",
    );

    // Back on the first step, a different folder may hold another pipeline:
    // what detection filled in is cleared.
    await page.locator("[data-testid='run-previous']").click();
    await page.locator("[data-testid='run-data-root-input']").fill(`${DATA_ROOT}-bis`);
    await expect(pipelineSelect).toHaveValue("");
    await expect(card).toHaveAttribute("data-state", "error", { timeout: 20_000 });
  });

  test("another template version is marked as such, and the detected one is one click away", async ({
    loginAsAdmin,
    page,
  }) => {
    await stubByParam(page, "**/api/v1/projects/folder_inspect**", "location", {
      [DATA_ROOT]: { json: AMPLISEQ_RUN },
    });
    const bodies = await stubFromRun(page, (body) => ({
      json: report({
        template_id: body.template_id ?? TEMPLATE_ID,
        data_collections: MATCHED_COLLECTIONS,
      }),
    }));

    await loginAsAdmin();
    await openWithFolder(page);

    const card = page.locator("[data-testid='run-detection-card']");
    await expect(card).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
    await expect(versionRadio(page, TEMPLATE_ID)).toBeChecked();

    await page.locator("[data-testid='run-version-option-2.14.0']").click();
    await expect(versionRadio(page, "nf-core/ampliseq/2.14.0")).toBeChecked();

    // The run is still 2.16.0; the template is now the 2.14.0 one.
    await expect(card.locator("[data-testid='run-detected-version']")).toHaveText("v2.16.0");
    await expect(card.locator("[data-testid='run-detected-template-version']")).toHaveText(
      "v2.14.0",
    );
    const match = card.locator("[data-testid='run-detected-match']");
    await expect(match).toHaveAttribute("data-match", "other-version");
    await expect(match).toHaveText("Different version");
    const detail = card.locator("[data-testid='run-detection-match-detail']");
    await expect(detail).toContainText("v2.16.0");
    await expect(detail).toContainText("v2.14.0");
    // The pipeline is still the detected one; the version no longer is.
    await expect(page.locator("[data-testid='run-pipeline-detected']")).toBeVisible();
    await expect(page.locator("[data-testid='run-version-detected']")).toHaveCount(0);

    // One click puts the detected template back.
    await card.locator("[data-testid='run-use-detected']").click();
    await expect(versionRadio(page, TEMPLATE_ID)).toBeChecked();
    await expect(match).toHaveAttribute("data-match", "exact");
    await expect(card.locator("[data-testid='run-use-detected']")).toHaveCount(0);

    // A picked version is what the preview asks for, and the preview says
    // it differs from the run.
    await page.locator("[data-testid='run-version-option-2.14.0']").click();
    await page.locator("[data-testid='create-from-run-submit']").click();
    await expect(page.locator("[data-testid='run-preview-report']")).toBeVisible({
      timeout: 20_000,
    });
    expect(bodies[0]?.template_id).toBe("nf-core/ampliseq/2.14.0");
    const summaryMatch = page.locator("[data-testid='run-summary-match']");
    await expect(summaryMatch).toHaveAttribute("data-match", "other-version");
    await expect(page.locator("[data-testid='run-summary-version']")).toHaveText("v2.16.0");
    await expect(page.locator("[data-testid='run-summary-template-version']")).toHaveText(
      "v2.14.0",
    );
  });

  test("a run with no template of its own version gets the closest one, said plainly", async ({
    loginAsAdmin,
    page,
  }) => {
    await stubByParam(page, "**/api/v1/projects/folder_inspect**", "location", {
      [DATA_ROOT]: {
        json: inspection(DATA_ROOT, {
          looks_like_run: true,
          markers: ["pipeline_info"],
          detected: detected({ version: "2.17.0", match: "closest" }),
        }),
      },
    });

    await loginAsAdmin();
    await openWithFolder(page);

    const card = page.locator("[data-testid='run-detection-card']");
    await expect(card).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
    await expect(card.locator("[data-testid='run-detected-version']")).toHaveText("v2.17.0");
    await expect(card.locator("[data-testid='run-detected-template-version']")).toHaveText(
      "v2.16.0",
    );
    const match = card.locator("[data-testid='run-detected-match']");
    await expect(match).toHaveAttribute("data-match", "closest");
    await expect(match).toHaveText("Closest available version");
    const detail = card.locator("[data-testid='run-detection-match-detail']");
    await expect(detail).toContainText("v2.17.0");
    await expect(detail).toContainText("v2.16.0");

    // The detected (closest) version is the one filled in, and no template
    // version claims to match the run.
    await expect(versionRadio(page, TEMPLATE_ID)).toBeChecked();
    await expect(page.locator("[data-testid='run-version-detected']")).toBeVisible();
    await expect(page.locator("[data-testid='run-version-control']")).not.toContainText(
      "Matches this run",
    );
  });

  test("preview groups what was not found first, relative to the run folder, and blocks Create when nothing matched", async ({
    loginAsAdmin,
    page,
  }) => {
    await stubByParam(page, "**/api/v1/projects/folder_inspect**", "location", {
      [DATA_ROOT]: { json: AMPLISEQ_RUN },
    });
    // The wrong-prefix case: every collection resolves to a path that does
    // not exist.
    await stubFromRun(page, () => ({
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
    }));

    await loginAsAdmin();
    await openWithFolder(page);
    await expect(page.locator("[data-testid='run-detection-card']")).toHaveAttribute(
      "data-state",
      "ready",
      { timeout: 20_000 },
    );

    const submit = page.locator("[data-testid='create-from-run-submit']");
    await submit.click();

    const preview = page.locator("[data-testid='run-preview-report']");
    await expect(preview).toBeVisible({ timeout: 20_000 });

    // The header names the run folder once, in full on hover and copy.
    await expect(preview.locator("[data-testid='run-summary-title']")).toHaveText(AMPLISEQ);
    await expect(preview.locator("[data-testid='run-preview-data-root']")).toHaveAttribute(
      "data-full-path",
      DATA_ROOT,
    );
    await expect(preview.locator("[data-testid='run-match-summary']")).toHaveText(
      "0 of 2 collections ready",
    );

    // Both collections sit in the open "Not found" section.
    const missingSection = preview.locator("[data-testid='run-section-missing']");
    await expect(missingSection).toBeVisible();
    await expect(preview.locator("[data-testid='run-section-ready']")).toHaveCount(0);
    for (const tag of ["multiqc_data", "asv_table"]) {
      const row = missingSection.locator(`[data-testid='run-preview-row-${tag}']`);
      await expect(row).toBeVisible();
      await expect(row).toHaveAttribute("data-status", "missing");
    }

    // Every path the server looked for, written relative to the run folder.
    await expect(preview.locator("[data-testid='run-preview-path-multiqc_data']")).toHaveText(
      "multiqc",
    );
    const missing = preview.locator("[data-testid='run-missing-sources-asv_table']");
    await expect(missing).toContainText("qiime2/abundance_tables/feature-table.tsv");
    await expect(missing).toContainText("qiime2/rel_abundance_tables/rel-table-ASV.tsv");
    await expect(missing).not.toContainText("s3://");
    await expect(
      preview.locator("[data-testid='run-missing-sources-multiqc_data']"),
    ).toContainText("multiqc/multiqc_data/multiqc.parquet");

    // Template settings and detected runs are on the screen too.
    await expect(preview.locator("[data-testid='run-resolved-variables']")).toContainText(
      "GROUP_COL = habitat",
    );
    await expect(preview.locator("[data-testid='run-resolved-variables']")).not.toContainText(
      "DATA_ROOT",
    );
    await expect(preview.locator("[data-testid='run-detected-runs']")).toContainText("run_1");

    // A truncated listing says the counts are a lower bound.
    await expect(preview.locator("[data-testid='run-truncated-warning']")).toBeVisible();

    // Nothing matched, so Create is refused with the reason visible.
    await expect(page.locator("[data-testid='run-no-match-warning']")).toBeVisible();
    await expect(submit).toBeDisabled();
    await expect(page.locator("[data-testid='run-submit-disabled-reason']")).toContainText(
      "No data collection matched anything in this folder",
    );
  });

  test("preview lists missing, then ready, then optional collections, the optional ones folded", async ({
    loginAsAdmin,
    page,
  }) => {
    await stubByParam(page, "**/api/v1/projects/folder_inspect**", "location", {
      [DATA_ROOT]: { json: AMPLISEQ_RUN },
    });
    await stubFromRun(page, () => ({
      json: report({
        data_collections: [
          dcRow({
            data_collection_tag: "multiqc_data",
            location: `${DATA_ROOT}/multiqc`,
            matched: 1,
            status: "ok",
          }),
          dcRow({
            data_collection_tag: "taxonomy",
            location: `${DATA_ROOT}/dada2`,
            status: "missing",
            missing_sources: [`${DATA_ROOT}/dada2/ASV_tax.tsv`],
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
            data_collection_tag: "phylogeny",
            location: `${DATA_ROOT}/qiime2/phylogenetic_tree`,
            optional: true,
            status: "missing",
            missing_sources: [`${DATA_ROOT}/qiime2/phylogenetic_tree/tree.nwk`],
          }),
          dcRow({
            data_collection_tag: "metadata",
            location: `${DATA_ROOT}/input`,
            optional: true,
            status: "pruned",
          }),
        ],
      }),
    }));

    await loginAsAdmin();
    await openWithFolder(page);
    await expect(page.locator("[data-testid='run-detection-card']")).toHaveAttribute(
      "data-state",
      "ready",
      { timeout: 20_000 },
    );
    const submit = page.locator("[data-testid='create-from-run-submit']");
    await submit.click();

    const preview = page.locator("[data-testid='run-preview-report']");
    await expect(preview).toBeVisible({ timeout: 20_000 });

    const sections = preview.locator("[data-testid^='run-section-']");
    expect(
      await sections.evaluateAll((els) => els.map((el) => el.getAttribute("data-testid"))),
    ).toEqual(["run-section-missing", "run-section-ready", "run-section-optional"]);

    // The pruned collection does not count; the optional missing one does.
    await expect(preview.locator("[data-testid='run-match-summary']")).toHaveText(
      "2 of 4 collections ready",
    );

    await expect(
      preview.locator("[data-testid='run-section-missing'] [data-testid='run-preview-row-taxonomy']"),
    ).toBeVisible();
    for (const tag of ["multiqc_data", "asv_table"]) {
      await expect(
        preview.locator(`[data-testid='run-section-ready'] [data-testid='run-preview-row-${tag}']`),
      ).toBeVisible();
    }
    await expect(preview.locator("[data-testid='run-preview-count-asv_table']")).toHaveText(
      "3 inputs",
    );
    await expect(preview.locator("[data-testid='run-preview-count-multiqc_data']")).toHaveText(
      "1 file",
    );

    // Optional collections start folded (a folded panel has no height but
    // stays in the page, so its region's aria-hidden says it is shut).
    const optional = preview.locator("[data-testid='run-section-optional']");
    const optionalToggle = optional.locator("button[aria-expanded]");
    const optionalPanel = optional.getByRole("region", { includeHidden: true });
    await expect(optionalToggle).toHaveAttribute("aria-expanded", "false");
    await expect(optionalPanel).toHaveAttribute("aria-hidden", "true");
    await expect(
      preview.locator("[data-testid='run-section-missing']").getByRole("region"),
    ).toHaveAttribute("aria-hidden", "false");
    await optionalToggle.click();
    await expect(optionalPanel).toHaveAttribute("aria-hidden", "false");
    await expect(optional.locator("[data-testid='run-preview-row-phylogeny']")).toBeVisible();
    await expect(optional.locator("[data-testid='run-preview-row-metadata']")).toBeVisible();
    await expect(
      optional.locator("[data-testid='run-missing-sources-phylogeny']"),
    ).toContainText("qiime2/phylogenetic_tree/tree.nwk");

    // Some collections are ready, so Create is allowed.
    await expect(page.locator("[data-testid='run-no-match-warning']")).toHaveCount(0);
    await expect(submit).toBeEnabled();
  });

  test("a folder no template matches asks for the pipeline before going on", async ({
    loginAsAdmin,
    page,
  }) => {
    await stubByParam(page, "**/api/v1/projects/folder_inspect**", "location", {
      [DATA_ROOT]: {
        json: inspection(DATA_ROOT, {
          looks_like_run: true,
          markers: ["pipeline_info"],
          detected: null,
        }),
      },
    });
    const bodies = await stubFromRun(page, (body) => ({
      json: report({
        template_id: body.template_id ?? TEMPLATE_ID,
        data_collections: MATCHED_COLLECTIONS,
      }),
    }));

    await loginAsAdmin();
    await openWithFolder(page);

    const card = page.locator("[data-testid='run-detection-card']");
    await expect(card).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
    await expect(card).toContainText("No pipeline recognised in this folder");

    // Previewing would only come back with "not recognised": the pipeline is
    // asked for now.
    const submit = page.locator("[data-testid='create-from-run-submit']");
    await expect(submit).toBeDisabled();
    await expect(page.locator("[data-testid='run-submit-disabled-reason']")).toContainText(
      "No template matches this folder: pick the pipeline below.",
    );

    // A pipeline with a single template version: picked, it is the choice.
    await page.locator("[data-testid='run-pipeline-select']").click();
    await page.locator("[data-testid='run-pipeline-option-nf-core/rnaseq']").click();
    await expect(page.locator("[data-testid='run-pipeline-select']")).toHaveValue(
      "RNA-seq Expression Analysis",
    );
    await expect(page.locator("[data-testid='run-pipeline-detected']")).toHaveCount(0);
    await expect(versionRadio(page, "nf-core/rnaseq/3.26.0")).toBeChecked();
    await expect(submit).toBeEnabled();

    await submit.click();
    await expect(page.locator("[data-testid='run-preview-report']")).toBeVisible({
      timeout: 20_000,
    });
    expect(bodies[0]?.template_id).toBe("nf-core/rnaseq/3.26.0");
  });

  test("an unreadable folder still previews, and an unrecognised pipeline asks for a template", async ({
    loginAsAdmin,
    page,
  }) => {
    await stubByParam(page, "**/api/v1/projects/folder_inspect**", "location", {
      [DATA_ROOT]: {
        status: 502,
        json: { detail: "The storage did not answer in time.", code: "s3_unreachable" },
      },
    });
    const bodies = await stubFromRun(page, () => ({
      status: 422,
      json: {
        detail: "No installed template matches the pipeline that produced this folder.",
        code: "template_not_detected",
      },
    }));

    await loginAsAdmin();
    await openWithFolder(page);

    const card = page.locator("[data-testid='run-detection-card']");
    await expect(card).toHaveAttribute("data-state", "error", { timeout: 20_000 });
    await expect(card.locator("[data-testid='run-detection-error']")).toHaveText(
      "The storage did not answer in time.",
    );

    // The server gets to recognise the pipeline when the plan is previewed.
    const submit = page.locator("[data-testid='create-from-run-submit']");
    await expect(submit).toBeEnabled();
    await submit.click();

    const notDetected = page.locator("[data-testid='run-template-not-detected']");
    await expect(notDetected).toBeVisible({ timeout: 20_000 });
    expect(bodies[0]?.template_id ?? null, "detection sends no template").toBeNull();
    await expect(notDetected).toContainText("No installed template matches");
    // Not shown as a read failure: the folder was read, only the template is
    // missing.
    await expect(page.locator("[data-testid='run-preview-error']")).toHaveCount(0);
    await expect(submit).toBeDisabled();
    await expect(page.locator("[data-testid='run-submit-disabled-reason']")).toContainText(
      "pick a template",
    );

    // The way out leads back to the pipeline picker, still empty.
    await notDetected.locator("[data-testid='run-pick-template']").click();
    const select = page.locator("[data-testid='run-pipeline-select']");
    await expect(select).toBeVisible();
    await expect(select).toHaveValue("");
  });

  test("creates the project and watches the ingestion run finish", async ({
    loginAsAdmin,
    page,
  }) => {
    const RUN_ID = "run-abc123";
    const DASHBOARD_ID = "665f0f3c1e4a2d7f8e5b8ca9";

    await stubByParam(page, "**/api/v1/projects/folder_inspect**", "location", {
      [DATA_ROOT]: { json: AMPLISEQ_RUN },
    });
    const bodies = await stubFromRun(page, (body) =>
      body.dry_run
        ? { json: report({ data_collections: MATCHED_COLLECTIONS }) }
        : {
            json: report({
              project_id: "665f0f3c1e4a2d7f8e5b8ca1",
              data_collections: MATCHED_COLLECTIONS,
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
          },
    );

    // The run is dispatched first and ingested on the next poll, so the modal
    // has to move from "running" to a terminal state on its own.
    let polls = 0;
    await page.route(`**/api/v1/projects/refresh_manifest/${RUN_ID}`, (route: Route) => {
      polls += 1;
      const done = polls > 1;
      return route.fulfill({
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
    await openWithFolder(page);
    await expect(page.locator("[data-testid='run-detection-card']")).toHaveAttribute(
      "data-state",
      "ready",
      { timeout: 20_000 },
    );

    const submit = page.locator("[data-testid='create-from-run-submit']");

    // Source -> Preview: the dry-run plan must render before advancing.
    await submit.click();
    await expect(page.locator("[data-testid='run-preview-report']")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.locator("[data-testid='run-match-summary']")).toHaveText(
      "2 of 2 collections ready",
    );
    await expect(submit).toBeEnabled();

    // Preview -> Create: the summary stays on screen, then create for real.
    await submit.click();
    await expect(page.locator("[data-testid='run-summary-card']")).toBeVisible();
    await submit.click();

    // No redirect: the project exists but its collections are still ingesting,
    // so the user stays here and watches the run.
    const modal = page.locator("[data-testid='run-created-modal']");
    await expect(modal).toBeVisible({ timeout: 20_000 });
    const created = bodies.find((body) => body.dry_run === false);
    expect(created, "the real (non dry-run) create was sent").toBeTruthy();
    // The template detection filled in is the one created with.
    expect(created?.template_id).toBe(TEMPLATE_ID);
    await expect(page).not.toHaveURL(/\/dashboard\//);

    const status = modal.locator("[data-testid='run-created-status']");
    await expect(status).toHaveAttribute("data-state", "running");
    await expect(status).toHaveAttribute("data-state", "success", { timeout: 30_000 });

    for (const tag of ["multiqc_data", "asv_table"]) {
      await expect(modal.locator(`[data-testid='run-progress-row-${tag}']`)).toHaveAttribute(
        "data-status",
        "ingested",
      );
    }

    // The plan is restated with the run's identity.
    await expect(modal.locator("[data-testid='run-summary-title']")).toHaveText(AMPLISEQ);
    await expect(modal.locator("[data-testid='run-summary-pipeline']")).toHaveText(
      "nf-core/ampliseq",
    );

    // The imported dashboard is reachable once the user chooses to go there.
    await expect(modal.locator("[data-testid='run-created-open-dashboard']")).toBeEnabled();
  });
});
