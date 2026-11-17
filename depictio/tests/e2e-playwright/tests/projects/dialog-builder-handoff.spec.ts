/**
 * The New project dialog and the Project Builder agree on what a project of a
 * recognised pipeline contains.
 *
 * The dialog reads a folder against the pipeline's template and, when only
 * some of the template's collections have files there, offers "Only the N
 * found" (the default) or "Whole template". "Adjust in the builder" hands that
 * choice (the removals, the variables) over to the builder, which must then
 * open on exactly what the dialog's own Create would have sent.
 *
 * Every test asserts what the page SENDS (the bodies of the stubbed
 * `POST /projects/from_run`) and the key state on screen. The session is real;
 * everything about folders, templates and the builder is stubbed, like
 * project-builder.spec.ts.
 */

import { Page, Route } from "@playwright/test";
import { test, expect, getAuthMode } from "@fixtures/auth";
import {
  detected,
  inspection,
  mockTemplates,
  openRunTab,
  setRunFolderFlags,
  stubByParam,
} from "@fixtures/runFolder";

const ROOT = "s3://depictio-e2e/ampliseq/partial-run";
const RUNS_ROOT = "s3://depictio-e2e/ampliseq/two-runs";
const TEMPLATE_ID = "nf-core/ampliseq/2.16.0";
const PROJECT_ID = "665f0f3c1e4a2d7f8e5b8cc1";
const RUN_ID = "run-handoff-1";
const DRAFT_KEY = (root: string) => `depictio:project-builder:draft:v1:${root}`;

type Json = Record<string, unknown>;

// ── Payloads ────────────────────────────────────────────────────────────────

function baseCollection(overrides: Json): Json {
  return {
    tag: "unnamed",
    type: "table",
    description: null,
    optional: false,
    kind: "file",
    location: null,
    wildcards: [],
    variables: [],
    edit: null,
    recipe: null,
    sources: [],
    needs: [],
    ...overrides,
  };
}

/** `POST /projects/builder/from_template` for ampliseq: a MultiQC scan, a
 *  table file, and a table derived from that file. */
const TEMPLATE_DESCRIPTION = {
  template_id: TEMPLATE_ID,
  title: "nf-core/ampliseq",
  version: "1.3.3",
  description: "Microbial community analysis",
  workflows: [
    {
      name: "ampliseq",
      engine: "nextflow",
      engine_version: null,
      version: "2.16.0",
      repository_url: "https://github.com/nf-core/ampliseq",
      catalog: null,
      structure: "flat",
      runs_regex: null,
      collections: [
        baseCollection({
          tag: "multiqc_data",
          type: "multiqc",
          kind: "scan",
          location: String.raw`^multiqc/multiqc_data/multiqc\.parquet$`,
          edit: "regex",
        }),
        baseCollection({
          tag: "alpha",
          kind: "file",
          location: "qiime2/alpha_diversity.tsv",
          edit: "path",
        }),
        baseCollection({ tag: "alpha_summary", kind: "derived", needs: ["alpha"] }),
      ],
    },
  ],
  links: [{ source_tag: "alpha", target_tag: "multiqc_data" }],
  dashboards: ["dashboards/overview.yaml"],
  variables: [
    { name: "DATA_ROOT", description: "The run folder", required: true, default: null },
    { name: "GROUP_COL", description: "Metadata column for grouping", required: false, default: null },
  ],
  conditionals: 0,
};

const CAPABILITIES = {
  mode: "server",
  dc_types: ["table", "multiqc", "image", "indexed_file", "geojson", "phylogeny"].map((type) => ({
    type,
    available: true,
    reason: null,
  })),
  table_formats: ["csv", "tsv", "parquet", "feather", "xls", "xlsx"],
  reader_options: ["separator", "has_header", "skip_rows", "comment_prefix", "null_values", "quote_char", "decimal_comma"],
  link_target_types: ["table", "multiqc", "image"],
  realtime: { events_enabled: true, reason: null },
  genomic_tracks: null,
  bioimage: null,
};

/** The template the builder makes of the edited draft (only its presence matters). */
const BUILT_TEMPLATE = {
  template: { template: { template_id: TEMPLATE_ID, version: "1" }, name: "built", workflows: [] },
  yaml: "template:\n  template_id: nf-core/ampliseq/2.16.0\n",
  template_id: TEMPLATE_ID,
  warnings: [],
};

function dcRow(tag: string, matched: number, status: "ok" | "missing", location: string): Json {
  return {
    data_collection_tag: tag,
    kind: "scan",
    mode: "s3_prefix",
    location,
    matched,
    missing_sources: [],
    optional: false,
    status,
    rule: null,
    samples: [],
    found_in: null,
    recipe: null,
  };
}

/** What the template finds in a partial run: MultiQC is there, the QIIME2
 *  table and the summary built from it are not. */
function plan(root: string, overrides: Json = {}): Json {
  return {
    project_id: null,
    project_name: "Ampliseq Microbial Community Analysis",
    template_id: TEMPLATE_ID,
    detected_template: null,
    data_root: root,
    detected_runs: [],
    resolved_variables: { DATA_ROOT: root },
    data_collections: [
      dcRow("multiqc_data", 1, "ok", `${root}/multiqc`),
      dcRow("alpha", 0, "missing", `${root}/qiime2/alpha_diversity.tsv`),
      dcRow("alpha_summary", 0, "missing", `${root}/qiime2`),
    ],
    dashboards: [],
    pruned_optional_dcs: [],
    truncated: false,
    run_info: null,
    input_files: [],
    run_id: null,
    storage_saved: false,
    dry_run: true,
    success: true,
    ...overrides,
  };
}

// ── Stubs ───────────────────────────────────────────────────────────────────

async function fulfil(route: Route, json: unknown, status = 200): Promise<void> {
  try {
    await route.fulfill({ status, json });
  } catch {
    // Cancelled by the page.
  }
}

interface Stubbed {
  /** Every `POST /projects/from_run` body, in order. */
  fromRun: Json[];
  /** Every `POST /projects/builder/template` body. */
  built: Json[];
}

/** Stub the templates, the folder reads, the builder routes and `from_run`
 *  for one scenario. `plan` answers a dry run. */
async function stubScenario(
  page: Page,
  scenario: { inspections: Record<string, Json>; plan: (root: string, body: Json) => Json },
): Promise<Stubbed> {
  const calls: Stubbed = { fromRun: [], built: [] };
  await mockTemplates(page);
  await setRunFolderFlags(page, { local: true, remote: false });
  await stubByParam(
    page,
    "**/api/v1/projects/folder_inspect**",
    "location",
    Object.fromEntries(Object.entries(scenario.inspections).map(([root, json]) => [root, { json }])),
  );

  await page.route("**/api/v1/projects/builder/capabilities", (route) => fulfil(route, CAPABILITIES));
  await page.route("**/api/v1/projects/builder/tree", (route) => {
    const root = ((route.request().postDataJSON() ?? {}) as Json).root as Json | undefined;
    return fulfil(route, {
      path: "",
      entries: [],
      truncated: false,
      is_remote: true,
      root_label: String(root?.data_root ?? ""),
    });
  });
  await page.route("**/api/v1/projects/builder/from_template", (route) =>
    fulfil(route, TEMPLATE_DESCRIPTION),
  );
  await page.route("**/api/v1/projects/builder/template", (route) => {
    calls.built.push((route.request().postDataJSON() ?? {}) as Json);
    return fulfil(route, BUILT_TEMPLATE);
  });
  await page.route("**/api/v1/projects/from_run", (route) => {
    const body = (route.request().postDataJSON() ?? {}) as Json;
    calls.fromRun.push(body);
    const root = String(body.data_root);
    const report = scenario.plan(root, body);
    return fulfil(
      route,
      body.dry_run
        ? report
        : { ...report, project_id: PROJECT_ID, run_id: RUN_ID, dry_run: false, success: true },
    );
  });
  await page.route(`**/api/v1/projects/refresh_manifest/${RUN_ID}`, (route) =>
    fulfil(route, {
      project_id: PROJECT_ID,
      refreshed: [
        {
          data_collection_tag: "multiqc_data",
          data_collection_id: null,
          entries: 1,
          status: "ingested",
          message: null,
        },
      ],
      run_id: RUN_ID,
      dry_run: false,
      success: true,
    }),
  );
  return calls;
}

/** A run of ampliseq at `root`, recognised. */
function partialRun(root: string): Json {
  return inspection(root, {
    looks_like_run: true,
    markers: ["pipeline_info", "multiqc"],
    folders: { count: 3, names: ["multiqc", "pipeline_info", "qiime2"] },
    detected: detected(),
  });
}

// ── Page helpers ────────────────────────────────────────────────────────────

const byTestId = (page: Page, id: string) => page.locator(`[data-testid='${id}']`);
const row = (page: Page, tag: string) =>
  page.locator(`[data-testid='builder-base-collection'][data-tag='${tag}']`);

/** Open the create dialog on a folder and wait until the tile knows which
 *  collections the folder has files for. */
async function readFolder(page: Page, root: string): Promise<void> {
  await openRunTab(page);
  await byTestId(page, "run-data-root-input").fill(root);
  await expect(byTestId(page, "read-level-choice")).toBeVisible({ timeout: 20_000 });
  await expect(byTestId(page, "read-level-template")).toHaveAttribute("data-active", "true");
  await expect(byTestId(page, "read-level-template-scope")).toBeVisible({ timeout: 20_000 });
}

/** "Adjust in the builder", once the template was read. */
async function adjustInBuilder(page: Page, root: string): Promise<void> {
  const edit = byTestId(page, "read-level-template-edit");
  await expect(edit).not.toHaveAttribute("aria-disabled", "true", { timeout: 20_000 });
  await edit.click();
  await expect(page).toHaveURL(/\/projects\/build$/);
  await expect(byTestId(page, "builder-root-input")).toHaveValue(root);
  await expect(byTestId(page, "builder-template-start")).toHaveAttribute("data-state", "loaded", {
    timeout: 20_000,
  });
}

/** Source -> Preview -> Create, in the dialog. */
async function createFromDialog(page: Page): Promise<void> {
  const submit = byTestId(page, "create-from-run-submit");
  await expect(submit).toBeEnabled({ timeout: 20_000 });
  await submit.click();
  await expect(byTestId(page, "run-preview-report")).toBeVisible({ timeout: 20_000 });
  await submit.click();
  await expect(byTestId(page, "run-summary-card")).toBeVisible();
  await submit.click();
  await expect(byTestId(page, "run-created-modal")).toBeVisible({ timeout: 20_000 });
}

/** In the builder: the data collections step, then review, preview, Create. */
async function createFromBuilder(page: Page): Promise<void> {
  await byTestId(page, "builder-next").click();
  await expect(byTestId(page, "builder-template-workflow")).toBeVisible({ timeout: 20_000 });
  await byTestId(page, "builder-next").click();
  const plan = byTestId(page, "builder-plan");
  await expect(plan).toBeEnabled({ timeout: 20_000 });
  await plan.click();
  await expect(byTestId(page, "builder-plan-report")).toBeVisible({ timeout: 20_000 });
  const create = byTestId(page, "builder-create");
  await expect(create).toBeEnabled({ timeout: 20_000 });
  await create.click();
  await expect(byTestId(page, "run-created-modal")).toBeVisible({ timeout: 20_000 });
}

/** The non dry-run bodies sent, in order. */
const creates = (bodies: Json[]) => bodies.filter((b) => b.dry_run === false);

const removals = (body: Json | undefined): string[] =>
  [...(((body?.edits as Json | undefined)?.remove as string[] | undefined) ?? [])].sort();

// ── Tests ───────────────────────────────────────────────────────────────────

test.describe("New project dialog hands its choice to the Project Builder", () => {
  test.beforeEach(async () => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Project creation is not exercised in public mode.");
  });

  test("a partial run: the dialog, its Create and the builder send the same removals", async ({
    loginAsAdmin,
    page,
  }) => {
    const calls = await stubScenario(page, {
      inspections: { [ROOT]: partialRun(ROOT) },
      plan: (root) => plan(root),
    });
    await loginAsAdmin();

    // The tile offers the two scopes, "only the found" preselected.
    await readFolder(page, ROOT);
    const foundOption = byTestId(page, "read-level-template-scope-found");
    await expect(foundOption).toHaveText("Only the 1 found");
    await expect(foundOption).toHaveAttribute("data-active", "true");
    await expect(byTestId(page, "read-level-template-scope-all")).not.toHaveAttribute(
      "data-active",
      "true",
    );

    // (a) The dialog's own Create takes the two missing collections out.
    await createFromDialog(page);
    const fromDialog = creates(calls.fromRun);
    expect(fromDialog, "one real create").toHaveLength(1);
    expect(fromDialog[0].template_id).toBe(TEMPLATE_ID);
    expect(removals(fromDialog[0])).toEqual(["alpha", "alpha_summary"]);
    expect(fromDialog[0].edits).toMatchObject({ additions: null });
    // The preview showed what Create sent.
    const previewed = calls.fromRun.filter((b) => b.dry_run === true && b.edits);
    expect(previewed.length).toBeGreaterThan(0);
    expect(removals(previewed.at(-1))).toEqual(["alpha", "alpha_summary"]);

    // (b) A fresh page, "Adjust in the builder": the builder opens on the same removals.
    await page.goto("/projects");
    await readFolder(page, ROOT);
    const before = calls.fromRun.length;
    await adjustInBuilder(page, ROOT);
    await expect(byTestId(page, "builder-template-changes")).toContainText("2 collections removed");

    await byTestId(page, "builder-next").click();
    await expect(byTestId(page, "builder-template-workflow")).toBeVisible({ timeout: 20_000 });
    await expect(row(page, "multiqc_data")).not.toHaveAttribute("data-removed", "true");
    await expect(row(page, "alpha")).toHaveAttribute("data-removed", "true");
    await expect(row(page, "alpha_summary")).toHaveAttribute("data-removed", "true");
    await expect(byTestId(page, "builder-template-collections")).toContainText("1 of 3 kept, 2 removed");
    // The selector reads the folder the same way: "found", with the badges to match.
    await expect(byTestId(page, "builder-template-scope-control")).toHaveAttribute("data-value", "found");
    await expect(
      row(page, "multiqc_data").locator("[data-testid='builder-base-folder-status']"),
    ).toHaveAttribute("data-status", "found");
    await expect(
      row(page, "alpha").locator("[data-testid='builder-base-folder-status']"),
    ).toHaveAttribute("data-status", "empty");
    await expect(
      row(page, "alpha_summary").locator("[data-testid='builder-base-folder-status']"),
    ).toHaveAttribute("data-status", "empty");
    await expect(byTestId(page, "builder-workflow-runs")).toHaveText("1 run");

    await byTestId(page, "builder-next").click();
    await expect(byTestId(page, "builder-plan")).toBeEnabled({ timeout: 20_000 });
    await byTestId(page, "builder-plan").click();
    await expect(byTestId(page, "builder-plan-report")).toBeVisible({ timeout: 20_000 });
    const create = byTestId(page, "builder-create");
    await expect(create).toBeEnabled({ timeout: 20_000 });
    await create.click();
    await expect(byTestId(page, "run-created-modal")).toBeVisible({ timeout: 20_000 });

    const fromBuilder = creates(calls.fromRun.slice(before));
    expect(fromBuilder, "one real create from the builder").toHaveLength(1);
    expect(fromBuilder[0].template_id).toBe(TEMPLATE_ID);
    expect(removals(fromBuilder[0])).toEqual(removals(fromDialog[0]));
    expect(fromBuilder[0]).not.toHaveProperty("template");
    expect(fromBuilder[0]).not.toHaveProperty("runs");
  });

  test("'Whole template' sends no removals, from the dialog and from the builder", async ({
    loginAsAdmin,
    page,
  }) => {
    const calls = await stubScenario(page, {
      inspections: { [ROOT]: partialRun(ROOT) },
      plan: (root) => plan(root),
    });
    await loginAsAdmin();

    await readFolder(page, ROOT);
    await byTestId(page, "read-level-template-scope-all").click();
    await expect(byTestId(page, "read-level-template-scope-all")).toHaveAttribute("data-active", "true");
    await expect(byTestId(page, "read-level-template-scope-found")).not.toHaveAttribute(
      "data-active",
      "true",
    );
    await createFromDialog(page);
    const fromDialog = creates(calls.fromRun);
    expect(fromDialog).toHaveLength(1);
    expect(fromDialog[0].template_id).toBe(TEMPLATE_ID);
    expect(removals(fromDialog[0]), "the whole template takes nothing out").toEqual([]);

    // The builder opens on the whole template too.
    await page.goto("/projects");
    await readFolder(page, ROOT);
    await byTestId(page, "read-level-template-scope-all").click();
    const before = calls.fromRun.length;
    await adjustInBuilder(page, ROOT);
    await expect(byTestId(page, "builder-template-changes")).toContainText("Nothing changed yet.");
    await byTestId(page, "builder-next").click();
    await expect(byTestId(page, "builder-template-workflow")).toBeVisible({ timeout: 20_000 });
    await expect(byTestId(page, "builder-template-collections")).toContainText("3 of 3 kept");
    await expect(byTestId(page, "builder-template-scope-control")).toHaveAttribute("data-value", "whole");
    await byTestId(page, "builder-previous").click();
    await createFromBuilder(page);
    const fromBuilder = creates(calls.fromRun.slice(before));
    expect(fromBuilder).toHaveLength(1);
    expect(removals(fromBuilder[0])).toEqual([]);
  });

  test("a saved draft of the folder does not override the dialog's choice, and can be restored", async ({
    loginAsAdmin,
    page,
  }) => {
    await stubScenario(page, {
      inspections: { [ROOT]: partialRun(ROOT) },
      plan: (root) => plan(root),
    });
    await loginAsAdmin();

    // A draft is saved for the folder: the builder, with MultiQC taken out too.
    await readFolder(page, ROOT);
    await adjustInBuilder(page, ROOT);
    await byTestId(page, "builder-next").click();
    await expect(byTestId(page, "builder-template-workflow")).toBeVisible({ timeout: 20_000 });
    await row(page, "multiqc_data").locator("[data-testid='builder-base-remove']").click();
    await expect(row(page, "multiqc_data")).toHaveAttribute("data-removed", "true");
    await expect
      .poll(() =>
        page.evaluate((key) => {
          try {
            const draft = JSON.parse(window.localStorage.getItem(key) ?? "null");
            return draft?.base?.remove ?? null;
          } catch {
            return null;
          }
        }, DRAFT_KEY(ROOT)),
      )
      .toContain("multiqc_data");

    // The dialog says "Whole template": that is what the builder opens on.
    await page.goto("/projects");
    await readFolder(page, ROOT);
    await byTestId(page, "read-level-template-scope-all").click();
    await adjustInBuilder(page, ROOT);
    const replaced = byTestId(page, "builder-template-replaced");
    await expect(replaced).toBeVisible();
    await expect(byTestId(page, "builder-template-restore")).toBeVisible();
    await expect(byTestId(page, "builder-template-changes")).toContainText("Nothing changed yet.");
    await byTestId(page, "builder-next").click();
    await expect(byTestId(page, "builder-template-workflow")).toBeVisible({ timeout: 20_000 });
    for (const tag of ["multiqc_data", "alpha", "alpha_summary"]) {
      await expect(row(page, tag)).not.toHaveAttribute("data-removed", "true");
    }
    await expect(byTestId(page, "builder-template-collections")).toContainText("3 of 3 kept");

    // Restore puts the saved draft back.
    await byTestId(page, "builder-previous").click();
    await byTestId(page, "builder-template-restore").click();
    await expect(byTestId(page, "builder-template-replaced")).toHaveCount(0);
    await byTestId(page, "builder-next").click();
    await expect(byTestId(page, "builder-template-workflow")).toBeVisible({ timeout: 20_000 });
    await expect(row(page, "multiqc_data")).toHaveAttribute("data-removed", "true");
  });

  test("a folder of two runs: the builder reads both, as the dialog does", async ({
    loginAsAdmin,
    page,
  }) => {
    const RUNS = ["run_a", "run_b"];
    const calls = await stubScenario(page, {
      inspections: {
        [RUNS_ROOT]: inspection(RUNS_ROOT, {
          looks_like_run: false,
          child_runs: RUNS,
          folders: { count: 2, names: RUNS },
          detected: detected(),
        }),
      },
      plan: (root, body) =>
        plan(root, {
          // The template read both runs: MultiQC found one file in each.
          data_collections: [
            dcRow("multiqc_data", 2, "ok", `${root}/${RUNS[0]}/multiqc`),
            dcRow("alpha", 0, "missing", `${root}/${RUNS[0]}/qiime2/alpha_diversity.tsv`),
            dcRow("alpha_summary", 0, "missing", `${root}/${RUNS[0]}/qiime2`),
          ],
          runs: body.runs ?? null,
        }),
    });
    await loginAsAdmin();

    await readFolder(page, RUNS_ROOT);
    // The runs are named in the Folder check, and none shares a sample.
    await expect(page.locator("[data-testid$='-check-folder']").first()).toContainText(
      "2 runs, read together",
    );
    await expect(page.locator("[data-testid$='-check-samples']").first()).toHaveAttribute(
      "data-status",
      "ok",
    );
    // The dialog's plan reads both runs.
    await expect
      .poll(() => calls.fromRun.some((b) => b.dry_run === true && JSON.stringify(b.runs) === JSON.stringify(RUNS)))
      .toBe(true);

    const before = calls.fromRun.length;
    await adjustInBuilder(page, RUNS_ROOT);
    await byTestId(page, "builder-next").click();
    await expect(byTestId(page, "builder-template-workflow")).toBeVisible({ timeout: 20_000 });
    await expect(byTestId(page, "builder-workflow-runs").first()).toHaveText("2 runs");
    // A collection of the reader's own cannot be read across runs yet.
    await expect(byTestId(page, "builder-template-add-dc")).toBeDisabled();
    // The folder status comes from the plan of both runs, so the same removals apply.
    await expect(byTestId(page, "builder-template-scope-control")).toHaveAttribute("data-value", "found");
    await expect(row(page, "alpha")).toHaveAttribute("data-removed", "true");
    await expect(row(page, "multiqc_data")).not.toHaveAttribute("data-removed", "true");

    // The plan the builder asks for carries the runs.
    await expect
      .poll(() =>
        calls.fromRun
          .slice(before)
          .some((b) => b.dry_run === true && JSON.stringify(b.runs) === JSON.stringify(RUNS)),
      )
      .toBe(true);
    for (const b of calls.fromRun.slice(before)) {
      expect(b.runs, "no builder plan reads the parent as one run").toEqual(RUNS);
    }

    await byTestId(page, "builder-next").click();
    await expect(byTestId(page, "builder-plan")).toBeEnabled({ timeout: 20_000 });
    await byTestId(page, "builder-plan").click();
    await expect(byTestId(page, "builder-plan-report")).toBeVisible({ timeout: 20_000 });
    const preview = calls.fromRun.slice(before).filter((b) => b.dry_run === true && b.edits);
    expect(preview.at(-1)?.runs).toEqual(RUNS);
    await byTestId(page, "builder-create").click();
    await expect(byTestId(page, "run-created-modal")).toBeVisible({ timeout: 20_000 });

    const created = creates(calls.fromRun.slice(before));
    expect(created).toHaveLength(1);
    expect(created[0].runs).toEqual(RUNS);
    expect(created[0].template_id).toBe(TEMPLATE_ID);
    expect(removals(created[0])).toEqual(["alpha", "alpha_summary"]);
  });

  test("runs naming the same MultiQC samples: the check fails and Next waits", async ({
    loginAsAdmin,
    page,
  }) => {
    const RUNS = ["run_a", "run_b"];
    await stubScenario(page, {
      inspections: {
        [RUNS_ROOT]: inspection(RUNS_ROOT, {
          looks_like_run: false,
          child_runs: RUNS,
          folders: { count: 2, names: RUNS },
          detected: detected(),
        }),
      },
      plan: (root, body) =>
        plan(root, {
          data_collections: [dcRow("multiqc_data", 2, "ok", `${root}/${RUNS[0]}/multiqc`)],
          runs: body.runs ?? null,
          shared_samples: [
            { data_collection_tag: "multiqc_data", runs: RUNS, count: 2, samples: ["S2", "S3"] },
          ],
        }),
    });
    await loginAsAdmin();

    await readFolder(page, RUNS_ROOT);
    const samples = page.locator("[data-testid$='-check-samples']").first();
    await expect(samples).toHaveAttribute("data-status", "fail");
    await expect(samples).toContainText("2 samples in run_a and run_b: S2, S3");
    await expect(byTestId(page, "create-from-run-submit")).toHaveAttribute("aria-disabled", "true");
    await expect(byTestId(page, "run-submit-disabled-reason")).toContainText("same samples");
  });

  test("a template variable set in the dialog reaches the builder's Create", async ({
    loginAsAdmin,
    page,
  }) => {
    const calls = await stubScenario(page, {
      inspections: { [ROOT]: partialRun(ROOT) },
      plan: (root) => plan(root),
    });
    await loginAsAdmin();

    await readFolder(page, ROOT);
    await byTestId(page, "run-template-settings-toggle").click();
    await byTestId(page, "run-variable-input-GROUP_COL").fill("habitat");

    const before = calls.fromRun.length;
    await adjustInBuilder(page, ROOT);
    await byTestId(page, "builder-next").click();
    await expect(byTestId(page, "builder-template-workflow")).toBeVisible({ timeout: 20_000 });
    // The template's variables are listed, folded; the dialog's value is in.
    await byTestId(page, "builder-template-variables").getByText("Template variables").click();
    await expect(
      page.locator("[data-testid='builder-template-variable'][data-name='GROUP_COL']"),
    ).toHaveValue("habitat");

    await byTestId(page, "builder-next").click();
    await expect(byTestId(page, "builder-plan")).toBeEnabled({ timeout: 20_000 });
    await byTestId(page, "builder-plan").click();
    await expect(byTestId(page, "builder-plan-report")).toBeVisible({ timeout: 20_000 });
    await byTestId(page, "builder-create").click();
    await expect(byTestId(page, "run-created-modal")).toBeVisible({ timeout: 20_000 });

    const created = creates(calls.fromRun.slice(before));
    expect(created).toHaveLength(1);
    expect(created[0].variables).toEqual({ GROUP_COL: "habitat" });
    expect(created[0].template_id).toBe(TEMPLATE_ID);
    expect(removals(created[0])).toEqual(["alpha", "alpha_summary"]);
  });
});
