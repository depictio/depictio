/**
 * Folder browser of the "From a run folder" tab (FolderBrowserModal).
 *
 * The browser only exists when the server reads run folders from its own
 * disk (`depictio local`) or may browse S3 locations, which CI's stack does
 * neither of. So the capability flags are switched on by rewriting the real
 * `/auth/me/optional` answer (the session stays real), and the folder calls
 * (`local_dirs`, `s3_dirs`, `folder_inspect`, `find_runs`) are stubbed with
 * a small folder tree. What is under test is the walk through it: lazy
 * expansion, the detail pane, the path bar, the run search (its hits first,
 * each saying who made the run), the recent folders, and the path the run
 * folder field ends up with.
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
  stubFolderRoute,
  StubAnswer,
} from "@fixtures/runFolder";

const ROOT = "/Users/e2e";
const DOCUMENTS = `${ROOT}/Documents`;
const RESULTS = `${ROOT}/results`;
const BATCH = `${RESULTS}/batch`;
const YEAR = `${BATCH}/2026`;
const RUN41 = `${RESULTS}/run41`;
const RUN42 = `${RESULTS}/run42`;
const RUN77 = `${YEAR}/run77`;

const S3_BUCKET = "s3://depictio-runs/";
const S3_PIPELINE = `${S3_BUCKET}ampliseq/`;
const S3_RUN = `${S3_PIPELINE}run-42/`;

function entry(path: string, extra: Record<string, unknown> = {}) {
  const name = path.replace(/\/+$/, "").split("/").pop();
  return { name, path, looks_like_run: false, has_children: true, ...extra };
}

function listing(path: string, root: string, entries: unknown[], extra: Record<string, unknown> = {}) {
  return {
    json: { path, root, parent: null, entries, truncated: false, looks_like_run: false, ...extra },
  };
}

/** `local_dirs` per `?path=`; "" is the roots listing. */
const LOCAL: Record<string, StubAnswer> = {
  "": { json: { path: null, root: null, parent: null, entries: [entry(ROOT)], truncated: false } },
  [ROOT]: listing(ROOT, ROOT, [
    entry(DOCUMENTS, { has_children: false }),
    entry(RESULTS),
  ]),
  [DOCUMENTS]: listing(DOCUMENTS, ROOT, []),
  [RESULTS]: listing(RESULTS, ROOT, [
    entry(BATCH),
    entry(RUN41, { has_children: false }),
    entry(RUN42, { looks_like_run: true }),
  ]),
  [RUN41]: listing(RUN41, ROOT, []),
  [RUN42]: listing(
    RUN42,
    ROOT,
    [
      entry(`${RUN42}/multiqc`, { has_children: false }),
      entry(`${RUN42}/pipeline_info`, { has_children: false }),
    ],
    { looks_like_run: true },
  ),
  [`${RUN42}/multiqc`]: listing(`${RUN42}/multiqc`, ROOT, []),
  [BATCH]: listing(BATCH, ROOT, [entry(YEAR)]),
  // More than the server lists: the tree says so.
  [YEAR]: listing(YEAR, ROOT, [entry(RUN77, { looks_like_run: true })], { truncated: true }),
  [RUN77]: listing(RUN77, ROOT, [entry(`${RUN77}/multiqc`, { has_children: false })], {
    looks_like_run: true,
  }),
};

/** `s3_dirs` per `?url=`; "" is the allowed locations. */
const S3: Record<string, StubAnswer> = {
  "": { json: { path: null, root: null, parent: null, entries: [entry(S3_BUCKET)], truncated: false } },
  [S3_BUCKET]: listing(S3_BUCKET, S3_BUCKET, [entry(S3_PIPELINE)]),
  [S3_PIPELINE]: listing(S3_PIPELINE, S3_BUCKET, [entry(S3_RUN)]),
  [S3_RUN]: listing(
    S3_RUN,
    S3_BUCKET,
    [entry(`${S3_RUN}multiqc/`), entry(`${S3_RUN}pipeline_info/`)],
    { looks_like_run: true },
  ),
};

const RNASEQ = detected({
  template_id: "nf-core/rnaseq/3.26.0",
  template_version: "3.26.0",
  pipeline: "nf-core/rnaseq",
  version: "3.26.0",
});

/** What run42's pipeline_info says about the run. */
const RUN_INFO = {
  engine: "nextflow",
  engine_version: "25.04.6",
  run_name: "tender_curie",
  homepage: "https://nf-co.re/ampliseq",
  params: { outdir: "results", input: "samplesheet.tsv", skip_qiime: false },
  params_total: 3,
  tools_executed: ["cutadapt", "dada2", "fastqc"],
  reports: [
    {
      kind: "execution_report",
      location: `${RUN42}/pipeline_info/execution_report.html`,
      name: "execution_report.html",
      size: 2_400_000,
    },
  ],
  extra: {},
};

/** The dry run behind "What this template finds here". */
function findingsReport(dataRoot: string) {
  return {
    project_id: null,
    project_name: "run42",
    template_id: "nf-core/ampliseq/2.16.0",
    detected_template: null,
    data_root: dataRoot,
    detected_runs: [],
    resolved_variables: {},
    data_collections: [
      {
        data_collection_tag: "multiqc_data",
        kind: "scan",
        mode: "recursive",
        location: dataRoot,
        matched: 7,
        missing_sources: [],
        optional: false,
        status: "ok",
        rule: "multiqc_data\\.json",
        samples: [`${dataRoot}/multiqc/multiqc_data/multiqc_data.json`],
        recipe: null,
      },
      {
        data_collection_tag: "alpha_diversity",
        kind: "recipe",
        mode: null,
        location: dataRoot,
        matched: 1,
        missing_sources: [],
        optional: false,
        status: "ok",
        rule: null,
        samples: [],
        recipe: {
          name: "nf-core/ampliseq/alpha_diversity.py",
          summary: "Alpha diversity per sample.",
          sources: [
            {
              ref: "alpha_vectors",
              kind: "file",
              pattern: "qiime2/diversity/alpha_diversity/*/metadata.tsv",
              dc_ref: null,
              optional: false,
              matched: 1,
              samples: [`${dataRoot}/qiime2/diversity/alpha_diversity/shannon/metadata.tsv`],
              found: true,
            },
          ],
        },
      },
    ],
    dashboards: [],
    pruned_optional_dcs: [],
    truncated: false,
    run_id: null,
    dry_run: true,
    success: true,
  };
}

/** `folder_inspect` per `?location=`; any other folder holds nothing. */
function inspections(delays: Record<string, number> = {}): Record<string, StubAnswer> {
  const runRecords = {
    looks_like_run: true,
    markers: ["pipeline_info", "multiqc"],
    folders: { count: 2, names: ["multiqc", "pipeline_info"] },
    files: { count: 3, names: ["samplesheet.csv", "nextflow.log", "params.json"] },
  };
  const answers: Record<string, StubAnswer> = {
    [RUN42]: { json: inspection(RUN42, { ...runRecords, detected: detected(), run_info: RUN_INFO }) },
    [RUN77]: { json: inspection(RUN77, { ...runRecords, detected: RNASEQ }) },
    [S3_RUN]: { json: inspection(S3_RUN, { ...runRecords, detected: detected() }) },
  };
  for (const [location, delayMs] of Object.entries(delays)) {
    answers[location] = { ...(answers[location] ?? { json: inspection(location) }), delayMs };
  }
  return answers;
}

const FIND: Record<string, StubAnswer> = {
  // The searched folder is itself a run folder.
  [RUN42]: {
    json: {
      location: RUN42,
      runs: [
        {
          location: RUN42,
          name: "run42",
          relative: ".",
          markers: ["pipeline_info", "multiqc"],
          detected: detected(),
        },
      ],
      truncated: false,
      scanned: 3,
    },
  },
  [RESULTS]: {
    json: {
      location: RESULTS,
      runs: [
        {
          location: RUN42,
          name: "run42",
          relative: "run42",
          markers: ["pipeline_info", "multiqc"],
          detected: detected(),
        },
        {
          location: RUN77,
          name: "run77",
          relative: "batch/2026/run77",
          markers: ["pipeline_info"],
          detected: RNASEQ,
        },
      ],
      truncated: true,
      scanned: 120,
    },
  },
};

/** Stub every folder call; returns the paths listed, in order. */
async function stubFolders(
  page: Page,
  { inspectDelays = {} }: { inspectDelays?: Record<string, number> } = {},
): Promise<{ listed: string[] }> {
  const listed = await stubByParam(page, "**/api/v1/projects/local_dirs**", "path", LOCAL);
  await stubByParam(page, "**/api/v1/projects/s3_dirs**", "url", S3, () => ({
    status: 422,
    json: { detail: "This location is not one Depictio may browse.", code: "s3_refused" },
  }));
  await stubByParam(
    page,
    "**/api/v1/projects/folder_inspect**",
    "location",
    inspections(inspectDelays),
    (location) => ({ json: inspection(location) }),
  );
  await stubByParam(page, "**/api/v1/projects/find_runs**", "location", FIND, (location) => ({
    json: { location, runs: [], truncated: false, scanned: 1 },
  }));
  return { listed };
}

const treeNode = (page: Page, path: string) =>
  page.locator(`[data-testid='browse-tree-node'][data-path='${path}']`);

const chevron = (page: Page, path: string) =>
  treeNode(page, path).locator("[data-testid='browse-tree-chevron']");

async function openBrowser(page: Page): Promise<void> {
  await openRunTab(page);
  await page.locator("[data-testid='run-browse-local']").click();
  await expect(page.locator("[data-testid='browse-modal']")).toBeVisible();
}

/** Type a path in the path bar and press Enter. */
async function goTo(page: Page, path: string): Promise<void> {
  const input = page.locator("[data-testid='browse-path-input']");
  await input.fill(path);
  await input.press("Enter");
}

test.describe("Browse for a run folder", () => {
  // Same gate as create-from-run.spec.ts: creating a project as admin is not
  // the path under test in public mode.
  test.beforeEach(async ({ page }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Project creation is not exercised in public mode.");
    await mockTemplates(page);
  });

  test("expands folders lazily, with a chevron only where there are sub-folders, and walks by keyboard", async ({
    loginAsAdmin,
    page,
  }) => {
    await setRunFolderFlags(page, { local: true, remote: false });
    const { listed } = await stubFolders(page);

    await loginAsAdmin();
    await openBrowser(page);

    const modal = page.locator("[data-testid='browse-modal']");
    await expect(modal.locator("[data-testid='browse-group-local']")).toContainText(
      "This computer",
    );
    await expect(modal.locator("[data-testid='browse-group-s3']")).toHaveCount(0);

    // Only the allowed roots are listed on opening, the home folder as "~".
    await expect(treeNode(page, ROOT)).toBeVisible();
    await expect(treeNode(page, ROOT)).toContainText("~");
    expect(listed).not.toContain(ROOT);

    await chevron(page, ROOT).click();
    await expect(treeNode(page, RESULTS)).toBeVisible();
    expect(listed).toContain(ROOT);
    expect(listed).not.toContain(RESULTS);
    await expect(chevron(page, DOCUMENTS)).toHaveCount(0);
    await expect(chevron(page, RESULTS)).toHaveCount(1);

    // Clicking a folder selects it; the arrows expand and move; Enter selects.
    await treeNode(page, RESULTS).click();
    const detail = page.locator("[data-testid='browse-detail']");
    await expect(detail).toHaveAttribute("data-path", RESULTS);
    await page.keyboard.press("ArrowRight");
    await expect(treeNode(page, RUN42)).toBeVisible();
    await expect(treeNode(page, RUN42)).toHaveAttribute("data-run-folder", "true");
    await expect(treeNode(page, RUN42)).toContainText("Run folder");
    await expect(treeNode(page, RUN41)).not.toHaveAttribute("data-run-folder", "true");
    await expect(chevron(page, RUN41)).toHaveCount(0);

    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(detail).toHaveAttribute("data-path", BATCH);
    await expect(treeNode(page, BATCH)).toHaveAttribute("data-selected", "true");
    await expect(page.locator("[data-testid='browse-selected']")).toHaveAttribute(
      "data-full-path",
      BATCH,
    );
  });

  test("the detail pane reads the selected folder, ignores a slower earlier answer, and selecting fills the field", async ({
    loginAsAdmin,
    page,
  }) => {
    await setRunFolderFlags(page, { local: true, remote: false });
    await stubFolders(page, { inspectDelays: { [RESULTS]: 1_500 } });

    await loginAsAdmin();
    await openBrowser(page);

    await chevron(page, ROOT).click();
    await chevron(page, RESULTS).click();
    await expect(treeNode(page, RUN42)).toBeVisible();

    // `results` answers slowly; `run42` is selected before it does.
    await treeNode(page, RESULTS).click();
    await expect(page.locator("[data-testid='browse-detail-loading']")).toBeVisible();
    await treeNode(page, RUN42).click();

    const detail = page.locator("[data-testid='browse-detail']");
    await expect(detail).toHaveAttribute("data-path", RUN42);
    await expect(detail.locator("[data-testid='browse-detail-pipeline']")).toHaveText(
      "nf-core/ampliseq",
    );
    await expect(detail.locator("[data-testid='browse-detail-version']")).toHaveText("v2.16.0");
    await expect(detail.locator("[data-testid='browse-detail-template-version']")).toHaveText(
      "v2.16.0",
    );
    await expect(detail.locator("[data-testid='browse-detail-run-badge']")).toBeVisible();
    const markers = detail.locator("[data-testid='browse-detail-markers']");
    await expect(markers.locator("[data-marker='pipeline_info']")).toBeVisible();
    await expect(markers.locator("[data-marker='multiqc']")).toBeVisible();
    await expect(detail.locator("[data-testid='browse-detail-counts']")).toHaveText(
      "2 folders, 3 files",
    );
    await expect(detail.locator("[data-testid='browse-detail-files']")).toContainText(
      "samplesheet.csv",
    );

    // The answer for `results` lands after this and changes nothing.
    await page.waitForTimeout(2_000);
    await expect(detail).toHaveAttribute("data-path", RUN42);
    await expect(detail.locator("[data-testid='browse-detail-name']")).toHaveText("run42");
    await expect(detail.locator("[data-testid='browse-detail-pipeline']")).toHaveText(
      "nf-core/ampliseq",
    );

    // A folder without run records gets a gentle hint, not a refusal.
    const hint = page.locator("[data-testid='browse-not-run-hint']");
    await expect(hint).toHaveCount(0);
    await treeNode(page, RUN41).click();
    await expect(detail.locator("[data-testid='browse-detail-not-recognised']")).toBeVisible();
    await expect(hint).toBeVisible();
    await expect(page.locator("[data-testid='browse-select']")).toBeEnabled();
    await treeNode(page, RUN42).click();
    await expect(hint).toHaveCount(0);

    await page.locator("[data-testid='browse-select']").click();
    await expect(page.locator("[data-testid='browse-modal']")).toBeHidden();
    await expect(page.locator("[data-testid='run-data-root-input']")).toHaveValue(RUN42);

    // The picked folder is read at once, and fills in the template.
    const card = page.locator("[data-testid='run-detection-card']");
    await expect(card).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
    await expect(card.locator("[data-testid='run-detected-pipeline']")).toHaveText(
      "nf-core/ampliseq",
    );
    await expect(page.locator("[data-testid='run-pipeline-detected']")).toBeVisible();
  });

  test("the path bar suggests sub-folders and opens the tree on the folder typed", async ({
    loginAsAdmin,
    page,
  }) => {
    await setRunFolderFlags(page, { local: true, remote: false });
    await stubFolders(page);

    await loginAsAdmin();
    await openBrowser(page);

    const input = page.locator("[data-testid='browse-path-input']");
    await input.fill(`${RESULTS}/ru`);
    const suggestions = page.locator("[data-testid='browse-path-suggestion']");
    await expect(suggestions).toHaveCount(2);
    expect(
      await suggestions.evaluateAll((els) => els.map((el) => el.getAttribute("data-path"))),
    ).toEqual([RUN41, RUN42]);

    // Picking a suggestion opens the tree down to it and selects it.
    await page.locator(`[data-testid='browse-path-suggestion'][data-path='${RUN42}']`).click();
    await expect(treeNode(page, RUN42)).toHaveAttribute("data-selected", "true");
    await expect(page.locator("[data-testid='browse-detail']")).toHaveAttribute(
      "data-path",
      RUN42,
    );
    await expect(input).toHaveValue(RUN42);

    // Enter opens a folder several levels down, listing every level between.
    await goTo(page, YEAR);
    await expect(treeNode(page, YEAR)).toHaveAttribute("data-selected", "true");
    await expect(treeNode(page, BATCH)).toBeVisible();
    await expect(treeNode(page, RUN77)).toBeVisible();
    await expect(page.locator("[data-testid='browse-tree-truncated']")).toBeVisible();

    // A folder the server cannot open says why, under the path bar.
    await goTo(page, `${ROOT}/missing`);
    await expect(page.locator("[data-testid='browse-modal']")).toContainText(
      "This folder does not exist.",
    );
    await expect(input).toHaveAttribute("aria-invalid", "true");
    // The selection stays where it was.
    await expect(treeNode(page, YEAR)).toHaveAttribute("data-selected", "true");

    // A relative path is refused before any request.
    await goTo(page, "results/run42");
    await expect(page.locator("[data-testid='browse-modal']")).toContainText(
      "Type a full path (starting with / or ~/) or an s3:// location.",
    );
  });

  test("the detail pane compares the run with its template, previews pipeline_info, lists what the template finds, and opens a sub-folder", async ({
    loginAsAdmin,
    page,
  }) => {
    await setRunFolderFlags(page, { local: true, remote: false });
    await stubFolders(page);
    const dryRuns: Array<Record<string, unknown>> = [];
    await page.route("**/api/v1/projects/from_run", (route: Route) => {
      const body = (route.request().postDataJSON() ?? {}) as Record<string, unknown>;
      dryRuns.push(body);
      return route.fulfill({ json: findingsReport(String(body.data_root)) });
    });

    await loginAsAdmin();
    await openBrowser(page);
    await goTo(page, RUN42);
    const detail = page.locator("[data-testid='browse-detail']");

    // The run and the template side by side, every row agreeing.
    await expect(detail.locator("[data-testid='browse-detail-comparison']")).toContainText("This run");
    for (const row of ["pipeline", "version", "engine"]) {
      await expect(detail.locator(`[data-testid='browse-detail-${row}-agreement']`)).toHaveAttribute(
        "data-agreement",
        "same",
      );
    }

    // What the template finds is asked for only when unfolded, as a dry run.
    expect(dryRuns).toHaveLength(0);
    await detail.locator("[data-testid='browse-detail-findings-toggle']").click();
    await expect(detail.locator("[data-testid='browse-detail-findings-summary']")).toHaveText(
      "2 of 2 collections found",
    );
    expect(dryRuns).toHaveLength(1);
    expect(dryRuns[0]).toMatchObject({ data_root: RUN42, template_id: "nf-core/ampliseq/2.16.0", dry_run: true });
    // A file index shows its rule and the real path of what it matched.
    await detail.locator("[data-testid='run-preview-details-toggle-multiqc_data']").click();
    const samples = detail.locator("[data-testid='run-preview-samples-multiqc_data']");
    await expect(samples).toContainText("multiqc/multiqc_data/multiqc_data.json");
    await expect(samples.locator("[data-full-path]").first()).toHaveAttribute(
      "data-full-path",
      `${RUN42}/multiqc/multiqc_data/multiqc_data.json`,
    );
    await expect(samples).toContainText("and 6 more files");
    // A table shows the recipe applied and what each input found.
    await detail.locator("[data-testid='run-preview-details-toggle-alpha_diversity']").click();
    const recipe = detail.locator("[data-testid='run-preview-details-alpha_diversity']");
    await expect(recipe.locator("[data-testid='recipe-name']")).toHaveText(
      "nf-core/ampliseq/alpha_diversity.py",
    );
    await expect(recipe.locator("[data-testid='recipe-source-alpha_vectors']")).toHaveAttribute(
      "data-found",
      "true",
    );

    // pipeline_info opens onto what the engine wrote about the run.
    await detail.locator("[data-testid='browse-detail-pipeline-info-toggle']").click();
    const info = detail.locator("[data-testid='pipeline-info-preview']");
    await expect(info.locator("[data-testid='pipeline-info-engine']")).toContainText("Nextflow 25.04.6");
    await expect(info.locator("[data-testid='pipeline-info-run-name']")).toContainText("tender_curie");
    await info.getByRole("tab", { name: "Parameters (3)" }).click();
    // The parameters that place the run come first.
    await expect(info.locator("[data-testid='pipeline-info-params'] tr").first()).toContainText("input");
    await info.getByRole("tab", { name: "Tools (3)" }).click();
    await expect(info.locator("[data-testid='pipeline-info-tools']")).toContainText("dada2");
    await info.getByRole("tab", { name: "Files (1)" }).click();
    await expect(info.locator("[data-testid='pipeline-info-reports']")).toContainText("2.3 MB");

    // The contents are one list; a folder in it opens in the tree.
    await detail.locator("[data-testid='browse-detail-folder'][data-name='multiqc']").click();
    await expect(detail).toHaveAttribute("data-path", `${RUN42}/multiqc`);
    await expect(treeNode(page, `${RUN42}/multiqc`)).toHaveAttribute("data-selected", "true");
  });

  test("the dialog fills the window on demand and gives the path once", async ({ loginAsAdmin, page }) => {
    await setRunFolderFlags(page, { local: true, remote: false });
    await stubFolders(page);

    await loginAsAdmin();
    await openBrowser(page);
    await goTo(page, RUN42);

    // The selected folder's path is written once, at the top of the detail pane.
    await expect(page.locator("[data-testid='browse-selected']")).toHaveCount(1);
    await expect(page.locator("[data-testid='browse-detail'] [data-testid='browse-selected']")).toHaveAttribute(
      "data-full-path",
      RUN42,
    );

    const expand = page.locator("[data-testid='browse-expand']");
    const dialog = page.getByRole("dialog", { name: "Choose the run folder" });
    const before = (await dialog.boundingBox())?.width ?? 0;
    await expand.click();
    await expect(expand).toHaveAttribute("aria-pressed", "true");
    const viewport = page.viewportSize()?.width ?? 0;
    await expect.poll(async () => (await dialog.boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(viewport - 1);
    expect(before).toBeLessThan(viewport);
    await expand.click();
    await expect(expand).toHaveAttribute("aria-pressed", "false");
  });

  test("finds the run folders below a folder, and a hit opens the tree on it", async ({
    loginAsAdmin,
    page,
  }) => {
    await setRunFolderFlags(page, { local: true, remote: false });
    await stubFolders(page);

    await loginAsAdmin();
    await openBrowser(page);

    // A run folder searched from itself is listed as "This folder".
    await goTo(page, RUN42);
    await expect(treeNode(page, RUN42)).toHaveAttribute("data-selected", "true");
    const detail = page.locator("[data-testid='browse-detail']");
    const contentsToggle = detail.locator("[data-testid='browse-detail-contents-toggle']");
    await expect(detail.locator("[data-testid='browse-detail-counts']")).toHaveText(
      "2 folders, 3 files",
    );
    await expect(contentsToggle).toHaveCount(0);
    await page.locator("[data-testid='browse-find-runs']").click();
    const results = page.locator("[data-testid='browse-find-results']");
    await expect(results).toHaveAttribute("data-state", "ready");
    await expect(results.locator("[data-testid='browse-find-hit']")).toHaveCount(1);
    await expect(results.locator("[data-testid='browse-find-hit']")).toContainText("This folder");
    await expect(results.locator("[data-testid='browse-find-summary']")).toHaveText(
      "1 run folder under run42, 3 folders looked through.",
    );
    await expect(results.locator("[data-testid='browse-find-truncated']")).toHaveCount(0);

    // The hits come first; the folder's contents fold under a toggle that
    // keeps their count, and open on demand.
    expect(
      await detail
        .locator(
          "[data-testid='browse-find-results'], [data-testid='browse-detail-contents-toggle']",
        )
        .evaluateAll((els) => els.map((el) => el.getAttribute("data-testid"))),
    ).toEqual(["browse-find-results", "browse-detail-contents-toggle"]);
    await expect(contentsToggle).toHaveAttribute("aria-expanded", "false");
    await expect(contentsToggle).toContainText("Contents");
    await expect(contentsToggle).toContainText("(2 folders, 3 files)");
    // A folded panel has no height but stays in the page: its aria-hidden
    // says it is shut.
    const contents = detail.locator("[data-testid='browse-detail-contents']");
    await expect(contents).toHaveAttribute("aria-hidden", "true");
    await contentsToggle.click();
    await expect(contentsToggle).toHaveAttribute("aria-expanded", "true");
    await expect(contents).toHaveAttribute("aria-hidden", "false");
    await expect(contents.locator("[data-testid='browse-detail-files']")).toBeVisible();

    await results.getByRole("button", { name: "Clear the results" }).click();
    await expect(page.locator("[data-testid='browse-find-runs']")).toBeVisible();
    await expect(contentsToggle).toHaveCount(0);
    await expect(detail.locator("[data-testid='browse-detail-files']")).toBeVisible();

    // From the parent: two hits, one several levels down, and an honest
    // count of what was looked through.
    await treeNode(page, RESULTS).click();
    await page.locator("[data-testid='browse-find-runs']").click();
    await expect(results).toHaveAttribute("data-state", "ready");
    await expect(results.locator("[data-testid='browse-find-summary']")).toHaveText(
      "2 run folders under results, 120 folders looked through.",
    );
    await expect(results.locator("[data-testid='browse-find-truncated']")).toBeVisible();
    const hits = results.locator("[data-testid='browse-find-hit']");
    expect(await hits.evaluateAll((els) => els.map((el) => el.getAttribute("data-path")))).toEqual(
      [RUN42, RUN77],
    );
    // Each hit: its path relative to the folder searched, then who made the
    // run (the workflow's mark, pipeline and version) and its run records.
    const deepHit = results.locator(`[data-testid='browse-find-hit'][data-path='${RUN77}']`);
    await expect(deepHit).toContainText("batch/2026/run77");
    await expect(deepHit).toHaveAttribute("data-detected", "true");
    await expect(deepHit.locator("img[alt='nf-core']")).toBeVisible();
    await expect(deepHit.locator("[data-testid='browse-find-hit-pipeline']")).toHaveText(
      "nf-core/rnaseq",
    );
    await expect(deepHit.locator("[data-testid='browse-find-hit-version']")).toHaveText("v3.26.0");
    await expect(deepHit.locator("[data-marker='pipeline_info']")).toBeVisible();
    await expect(deepHit.locator("[data-marker='multiqc']")).toHaveCount(0);
    const nearHit = results.locator(`[data-testid='browse-find-hit'][data-path='${RUN42}']`);
    await expect(nearHit.locator("[data-testid='browse-find-hit-pipeline']")).toHaveText(
      "nf-core/ampliseq",
    );
    await expect(nearHit.locator("[data-marker='multiqc']")).toBeVisible();

    // The deep hit opens the tree on it; the hits stay listed meanwhile, and
    // still come first.
    await deepHit.click();
    await expect(treeNode(page, RUN77)).toHaveAttribute("data-selected", "true");
    await expect(treeNode(page, YEAR)).toBeVisible();
    await expect(detail).toHaveAttribute("data-path", RUN77);
    await expect(detail.locator("[data-testid='browse-detail-pipeline']")).toHaveText(
      "nf-core/rnaseq",
    );
    await expect(results).toBeVisible();
    await expect(deepHit).toHaveAttribute("data-active", "true");
    await expect(contentsToggle).toHaveAttribute("aria-expanded", "false");
  });

  test("reopens on the folder in the field and lists the recent ones", async ({
    loginAsAdmin,
    page,
  }) => {
    await setRunFolderFlags(page, { local: true, remote: false });
    await stubFolders(page);

    await loginAsAdmin();
    await openBrowser(page);
    // Nothing picked yet: no recent folders.
    await expect(page.locator("[data-testid='browse-recent']")).toHaveCount(0);

    await goTo(page, RUN42);
    await expect(treeNode(page, RUN42)).toHaveAttribute("data-selected", "true");
    await page.locator("[data-testid='browse-select']").click();
    await expect(page.locator("[data-testid='run-data-root-input']")).toHaveValue(RUN42);

    // Reopened, the browser starts on the field's folder.
    await page.locator("[data-testid='run-browse-local']").click();
    await expect(page.locator("[data-testid='browse-modal']")).toBeVisible();
    await expect(treeNode(page, RUN42)).toHaveAttribute("data-selected", "true");
    await expect(page.locator("[data-testid='browse-path-input']")).toHaveValue(RUN42);
    await expect(
      page.locator(`[data-testid='browse-recent-item'][data-path='${RUN42}']`),
    ).toBeVisible();
    await page.locator("[data-testid='browse-cancel']").click();
    await expect(page.locator("[data-testid='browse-modal']")).toBeHidden();
    await expect(page.locator("[data-testid='run-data-root-input']")).toHaveValue(RUN42);

    // With the field emptied, the recent folder is one click away.
    await page.locator("[data-testid='run-data-root-input']").fill("");
    await page.locator("[data-testid='run-browse-local']").click();
    await expect(page.locator("[data-testid='browse-detail-empty']")).toBeVisible();
    await page.locator(`[data-testid='browse-recent-item'][data-path='${RUN42}']`).click();
    await expect(treeNode(page, RUN42)).toHaveAttribute("data-selected", "true");
    await expect(page.locator("[data-testid='browse-detail']")).toHaveAttribute(
      "data-path",
      RUN42,
    );
  });

  test("S3 locations are listed beside local folders when the server allows browsing them", async ({
    loginAsAdmin,
    page,
  }) => {
    await setRunFolderFlags(page, { local: true, remote: true });
    await stubFolders(page);

    await loginAsAdmin();
    await openBrowser(page);

    const modal = page.locator("[data-testid='browse-modal']");
    await expect(modal.locator("[data-testid='browse-group-local']")).toBeVisible();
    await expect(modal.locator("[data-testid='browse-group-s3']")).toContainText("S3");

    await expect(treeNode(page, S3_BUCKET)).toBeVisible();
    await chevron(page, S3_BUCKET).click();
    await chevron(page, S3_PIPELINE).click();
    await treeNode(page, S3_RUN).click();

    const detail = page.locator("[data-testid='browse-detail']");
    await expect(detail).toHaveAttribute("data-path", S3_RUN);
    await expect(detail.locator("[data-testid='browse-detail-run-badge']")).toBeVisible();
    await expect(treeNode(page, S3_RUN)).toHaveAttribute("data-run-folder", "true");

    await page.locator("[data-testid='browse-select']").click();
    await expect(page.locator("[data-testid='run-data-root-input']")).toHaveValue(S3_RUN);
    await expect(page.locator("[data-testid='run-detection-card']")).toHaveAttribute(
      "data-state",
      "ready",
      { timeout: 20_000 },
    );
  });

  test("with only S3 allowed, the browser shows S3 alone and refuses a local path", async ({
    loginAsAdmin,
    page,
  }) => {
    await setRunFolderFlags(page, { local: false, remote: true });
    await stubFolders(page);

    await loginAsAdmin();
    await openBrowser(page);

    const modal = page.locator("[data-testid='browse-modal']");
    await expect(modal.locator("[data-testid='browse-group-s3']")).toBeVisible();
    await expect(modal.locator("[data-testid='browse-group-local']")).toHaveCount(0);
    const input = page.locator("[data-testid='browse-path-input']");
    await expect(input).toHaveAttribute("placeholder", "s3://bucket/results/run42/");

    await goTo(page, ROOT);
    await expect(modal).toContainText(
      "Browsing folders on this computer is not available on this server.",
    );

    // An S3 location outside the allowed ones is refused by the server, and
    // its reason shown.
    await goTo(page, "s3://another-bucket/run/");
    await expect(modal).toContainText("This location is not one Depictio may browse.");
  });

  test("a folder the server refuses to list says why and can be tried again", async ({
    loginAsAdmin,
    page,
  }) => {
    await setRunFolderFlags(page, { local: true, remote: false });
    await stubFolders(page);
    // Registered last, so asked first: refuse `batch` once, then let the
    // folder stubs answer.
    let refused = false;
    await page.route(
      (url) =>
        url.pathname.endsWith("/projects/local_dirs") && url.searchParams.get("path") === BATCH,
      (route: Route) => {
        if (refused) return route.fallback();
        refused = true;
        return route.fulfill({
          status: 422,
          json: { detail: "Depictio may not read this folder.", code: "local_path_refused" },
        });
      },
    );

    await loginAsAdmin();
    await openBrowser(page);

    await chevron(page, ROOT).click();
    await chevron(page, RESULTS).click();
    await chevron(page, BATCH).click();

    const error = page.locator("[data-testid='browse-tree-error']");
    await expect(error).toContainText("Depictio may not read this folder.");
    await error.getByRole("button", { name: "Try again" }).click();
    await expect(treeNode(page, YEAR)).toBeVisible();
    await expect(error).toHaveCount(0);
  });

  test("a private bucket is browsed with its connection details, even where S3 browsing is off", async ({
    loginAsAdmin,
    page,
  }) => {
    const BUCKET = "s3://private-runs/";
    const PIPELINE = `${BUCKET}ampliseq/`;
    const RUN = `${PIPELINE}run-7/`;
    const STORAGE = {
      endpoint_url: null,
      region: null,
      access_key_id: "AKIAE2EPRIVATEKEY",
      secret_access_key: "e2e-private-secret-value",
    };
    const DENIED = {
      status: 403,
      json: { detail: "Access to this bucket was denied.", code: "s3_access_denied" },
    };
    const LISTINGS: Record<string, StubAnswer> = {
      [BUCKET]: listing(BUCKET, BUCKET, [entry(PIPELINE)]),
      [PIPELINE]: listing(PIPELINE, BUCKET, [entry(RUN)]),
      [RUN]: listing(RUN, BUCKET, [entry(`${RUN}multiqc/`), entry(`${RUN}pipeline_info/`)], {
        looks_like_run: true,
      }),
    };
    const runRecords = {
      looks_like_run: true,
      markers: ["pipeline_info", "multiqc"],
      folders: { count: 2, names: ["multiqc", "pipeline_info"] },
      detected: detected(),
    };

    await setRunFolderFlags(page, { local: false, remote: false });
    // Every route reads the bucket only with the details.
    const dirs = await stubFolderRoute(page, "**/api/v1/projects/s3_dirs**", "url", (url, storage) =>
      storage ? (LISTINGS[url] ?? null) : DENIED,
    );
    const inspects = await stubFolderRoute(
      page,
      "**/api/v1/projects/folder_inspect**",
      "location",
      (location, storage) => {
        if (!storage) return DENIED;
        return { json: inspection(location, location === RUN ? runRecords : {}) };
      },
    );
    const finds = await stubFolderRoute(
      page,
      "**/api/v1/projects/find_runs**",
      "location",
      (location, storage) =>
        storage
          ? {
              json: {
                location,
                runs: [
                  {
                    location: RUN,
                    name: "run-7",
                    relative: "ampliseq/run-7",
                    markers: ["pipeline_info", "multiqc"],
                    detected: null,
                  },
                ],
                truncated: false,
                scanned: 12,
              },
            }
          : DENIED,
    );

    await loginAsAdmin();
    await openRunTab(page);
    const browse = page.locator("[data-testid='run-browse-local']");
    await expect(browse).toHaveCount(0);
    await page.locator("[data-testid='run-data-root-input']").fill(RUN);

    // Refused, so the section asks for the details; with them, Browse appears.
    const section = page.locator("[data-testid='run-private-bucket-section']");
    await expect(section).toBeVisible({ timeout: 20_000 });
    await section.locator("[data-testid='run-private-bucket-access-key']").fill(STORAGE.access_key_id);
    await section
      .locator("[data-testid='run-private-bucket-secret']")
      .fill(STORAGE.secret_access_key);
    await browse.click();
    const modal = page.locator("[data-testid='browse-modal']");
    await expect(modal).toBeVisible();

    // The bucket is the S3 root, and the browser opens on the field's folder.
    await expect(modal.locator("[data-testid='browse-group-s3']")).toBeVisible();
    await expect(treeNode(page, BUCKET)).toContainText("private-runs");
    await expect(treeNode(page, RUN)).toHaveAttribute("data-selected", "true");
    const detail = page.locator("[data-testid='browse-detail']");
    await expect(detail).toHaveAttribute("data-path", RUN);
    await expect(detail.locator("[data-testid='browse-detail-run-badge']")).toBeVisible();
    await expect(detail.locator("[data-testid='browse-detail-pipeline']")).toHaveText(
      "nf-core/ampliseq",
    );

    // Searching from the bucket finds the run, and the hit opens on it.
    await treeNode(page, BUCKET).click();
    await expect(detail).toHaveAttribute("data-path", BUCKET);
    await page.locator("[data-testid='browse-find-runs']").click();
    const results = page.locator("[data-testid='browse-find-results']");
    await expect(results).toHaveAttribute("data-state", "ready");
    // An S3 search does not identify its hits: selecting one does.
    const hit = results.locator(`[data-testid='browse-find-hit'][data-path='${RUN}']`);
    await expect(hit).toHaveAttribute("data-detected", "false");
    await expect(hit.locator("[data-status='run-folder']")).toBeVisible();
    await expect(hit.locator("[data-testid='browse-find-hit-unidentified']")).toHaveText(
      "Select it to identify the pipeline",
    );
    await expect(hit.locator("[data-testid='browse-find-hit-pipeline']")).toHaveCount(0);
    await expect(hit.locator("[data-marker='pipeline_info']")).toBeVisible();
    await expect(hit).toContainText("ampliseq/run-7");
    await hit.click();
    await expect(treeNode(page, RUN)).toHaveAttribute("data-selected", "true");

    await page.locator("[data-testid='browse-select']").click();
    await expect(page.locator("[data-testid='run-data-root-input']")).toHaveValue(RUN);
    await expect(page.locator("[data-testid='run-detection-card']")).toHaveAttribute(
      "data-state",
      "ready",
      { timeout: 20_000 },
    );

    // The tree, the detail pane and the search read through the POST twins,
    // the details in the body; the bucket lists of the server were never
    // asked for, S3 browsing being off.
    expect(dirs.length).toBeGreaterThan(0);
    expect(finds).toHaveLength(1);
    for (const call of [...dirs, ...finds]) {
      expect(call).toMatchObject({ method: "POST", storage: STORAGE });
      expect(call.url).not.toContain("?");
    }
    expect(dirs.map((call) => call.value)).toEqual(expect.arrayContaining([BUCKET, PIPELINE, RUN]));
    const inspected = inspects.filter((call) => call.method === "POST");
    expect(inspected.map((call) => call.value)).toEqual(expect.arrayContaining([RUN, BUCKET]));
    for (const call of inspected) expect(call.storage).toEqual(STORAGE);
    // Only the first read of the field, before any details, went without them.
    expect(inspects.filter((call) => call.method === "GET").map((call) => call.value)).toEqual([RUN]);
  });
});
