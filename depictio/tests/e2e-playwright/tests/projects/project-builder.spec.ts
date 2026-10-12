/**
 * The Project Builder (/projects/build): turning a folder into a project by
 * grouping its files into data collections.
 *
 * Every test drives the real UI against stubbed builder routes
 * (`/projects/builder/{tree,suggest,match,template}`), a stubbed file preview
 * and a stubbed `/projects/from_run`, like the run-folder spec: the value is
 * what the page shows and sends, and none of it needs a folder on the
 * runner's disk. The payloads are what the real backend answers for the same
 * folder (a `quant/S1..S3.tsv` scan, a `samples.csv` and a `tree.nwk`),
 * produced by `depictio/project_builder` itself.
 *
 * The standalone mode (`depictio project-builder <dir>`) is the same bundle
 * with a `depictio-mode` meta tag in its page: the last test injects it into
 * the served document and checks the page never reaches for a session.
 */

import { Page, Route } from "@playwright/test";
import { test, expect, getAuthMode } from "@fixtures/auth";
import {
  inspection,
  mockTemplates,
  openRunTab,
  setRunFolderFlags,
  stubByParam,
} from "@fixtures/runFolder";

const DATA_ROOT = "/data/e2e-survey";
const S3_ROOT = "s3://depictio-e2e/survey/run-1";
const PROJECT_NAME = "E2E builder survey";
const TEMPLATE_ID = "custom/e2e-builder-survey";
const PROJECT_ID = "665f0f3c1e4a2d7f8e5b8cb1";
const RUN_ID = "run-builder-1";
const HANDOFF_KEY = "depictio:project-builder:handoff";

/** What `/suggest` derives for `quant/S1.tsv` alone, with `quant/S2.tsv`
 *  ticked, and for a Newick file (`compose.glob_regex` of the glob). */
const S1_REGEX = String.raw`^(?:[^/]+/)*S1\.tsv$`;
const QUANT_REGEX = String.raw`^quant/S[^/]*\.tsv$`;
const SAMPLES_REGEX = String.raw`^(?:[^/]+/)*samples\.csv$`;
const TREE_REGEX = String.raw`^(?:[^/]+/)*tree\.nwk$`;
/** Valid in the browser, refused by Python's `re`: a variable-width look-behind. */
const LOOKBEHIND_REGEX = String.raw`^quant/(?<=q\w+/)S\d+\.tsv$`;

type Json = Record<string, unknown>;
type StubAnswer = { status?: number; json: unknown };

// ── Payloads ────────────────────────────────────────────────────────────────

function entry(path: string, isDir: boolean, size: number | null) {
  return { name: path.split("/").pop() as string, path, is_dir: isDir, size };
}

/** `/tree` listings by folder, for `root`. */
function listings(root: string): Record<string, Json> {
  const listing = (path: string, entries: ReturnType<typeof entry>[]) => ({
    path,
    entries,
    truncated: false,
    is_remote: root.startsWith("s3://"),
    root_label: root,
  });
  return {
    "": listing("", [
      entry("quant", true, null),
      entry("samples.csv", false, 57),
      entry("tree.nwk", false, 31),
    ]),
    quant: listing("quant", [
      entry("quant/S1.tsv", false, 35),
      entry("quant/S2.tsv", false, 26),
      entry("quant/S3.tsv", false, 26),
    ]),
  };
}

function suggestion(overrides: Json): Json {
  return { catalog: [], multiqc: false, format: null, separator: null, ...overrides };
}

/** `/suggest` answers by `path|examples`. The server's tag for `quant/S1.tsv`
 *  is `quant_s1` (the top folder joins the stem); the page alone would say
 *  `s1`, so seeing it proves the editor took the suggestion. */
const SUGGESTIONS: Record<string, Json> = {
  "quant/S1.tsv|": suggestion({
    path: "quant/S1.tsv",
    tag: "quant_s1",
    type: "table",
    mode: "single",
    glob: "**/S1.tsv",
    regex: S1_REGEX,
    format: "tsv",
    separator: "\t",
  }),
  "quant/S1.tsv|quant/S2.tsv": suggestion({
    path: "quant/S1.tsv",
    tag: "quant_s1",
    type: "table",
    mode: "recursive",
    glob: "quant/S*.tsv",
    regex: QUANT_REGEX,
    format: "tsv",
    separator: "\t",
  }),
  "samples.csv|": suggestion({
    path: "samples.csv",
    tag: "samples",
    type: "table",
    mode: "single",
    glob: "**/samples.csv",
    regex: SAMPLES_REGEX,
    format: "csv",
    separator: ",",
  }),
  "tree.nwk|": suggestion({
    path: "tree.nwk",
    tag: "tree",
    type: "phylogeny",
    mode: "single",
    glob: "**/tree.nwk",
    regex: TREE_REGEX,
  }),
};

function matched(overrides: Json): Json {
  return {
    regex: null,
    files: [],
    count: 0,
    runs: [],
    truncated: false,
    schema: null,
    consistent: null,
    mismatches: [],
    missing_indexes: [],
    warnings: [],
    ...overrides,
  };
}

const COUNTS_SCHEMA = { sample: "String", gene: "String", count: "Int64" };
const SAMPLES_SCHEMA = { sample: "String", site: "String", depth: "Float64" };

/** `/match`: a single file by its path, a scan by its regex. */
function matchFor(collection: Json): Json {
  if (collection.mode === "single") {
    const path = String(collection.path ?? "");
    if (path === "samples.csv") {
      return matched({ files: [path], count: 1, schema: SAMPLES_SCHEMA, consistent: true });
    }
    if (path.startsWith("quant/")) {
      return matched({ files: [path], count: 1, schema: COUNTS_SCHEMA, consistent: true });
    }
    if (path === "tree.nwk") return matched({ files: [path], count: 1 });
    return matched({});
  }
  const regex = collection.regex as string;
  if (regex === QUANT_REGEX) {
    return matched({
      regex,
      files: ["quant/S1.tsv", "quant/S2.tsv", "quant/S3.tsv"],
      count: 3,
      schema: COUNTS_SCHEMA,
      consistent: true,
    });
  }
  if (regex === TREE_REGEX) return matched({ regex, files: ["tree.nwk"], count: 1 });
  if (regex === LOOKBEHIND_REGEX) {
    // What the browser's own regex engine would match: the server is what refuses it.
    return matched({
      regex,
      files: ["quant/S1.tsv", "quant/S2.tsv", "quant/S3.tsv"],
      count: 3,
      schema: COUNTS_SCHEMA,
      consistent: true,
    });
  }
  return matched({ regex });
}

/** `/projects/run_file_preview` answers by location, with the dtypes the
 *  builder asks for. */
function previews(root: string): Record<string, Json> {
  const table = (rel: string, size: number, columns: string[], rows: string[][], dtypes: Json) => ({
    location: `${root}/${rel}`,
    name: rel.split("/").pop(),
    size,
    format: "table",
    columns,
    rows,
    columns_total: columns.length,
    rows_total: rows.length,
    text: null,
    truncated: false,
    reason: null,
    dtypes,
  });
  return {
    [`${root}/quant/S1.tsv`]: table(
      "quant/S1.tsv",
      35,
      ["sample", "gene", "count"],
      [
        ["S1", "g1", "10"],
        ["S1", "g2", "4"],
      ],
      COUNTS_SCHEMA,
    ),
    [`${root}/samples.csv`]: table(
      "samples.csv",
      57,
      ["sample", "site", "depth"],
      [
        ["S1", "north", "12.5"],
        ["S2", "south", "8.0"],
        ["S3", "east", "3.2"],
      ],
      SAMPLES_SCHEMA,
    ),
    [`${root}/tree.nwk`]: {
      location: `${root}/tree.nwk`,
      name: "tree.nwk",
      size: 31,
      format: "text",
      columns: [],
      rows: [],
      columns_total: 0,
      rows_total: null,
      text: "((S1:0.1,S2:0.2):0.05,S3:0.3);\n",
      truncated: false,
      reason: null,
      dtypes: null,
    },
  };
}

/** The template `/template` builds from the two collections below. */
const TEMPLATE = {
  template: {
    template_id: TEMPLATE_ID,
    description: `${PROJECT_NAME}, defined with the Project Builder`,
    version: "1",
    variables: [
      {
        name: "DATA_ROOT",
        description: "The folder or s3:// prefix the collections are read from",
        required: true,
      },
    ],
  },
  name: PROJECT_NAME,
  project_type: "advanced",
  is_public: false,
  workflows: [
    {
      name: "main",
      engine: { name: "python" },
      data_location: { structure: "flat", locations: ["{DATA_ROOT}"] },
      data_collections: [
        {
          data_collection_tag: "quant",
          config: {
            type: "Table",
            metatype: "Aggregate",
            scan: { mode: "recursive", scan_parameters: { regex_config: { pattern: QUANT_REGEX } } },
            dc_specific_properties: { format: "tsv", polars_kwargs: { separator: "\t" } },
          },
        },
        {
          data_collection_tag: "samples",
          config: {
            type: "Table",
            metatype: "Metadata",
            scan: { mode: "single", scan_parameters: { filename: "{DATA_ROOT}/samples.csv" } },
            dc_specific_properties: { format: "csv", polars_kwargs: { separator: "," } },
          },
        },
      ],
    },
  ],
};

const TEMPLATE_YAML = [
  "# Defined with the Depictio Project Builder.",
  "# Run it against the folder (or s3:// prefix) it was built from, or any other",
  "# with the same layout:",
  "#   depictio ingest <folder or s3://prefix> --template <this file>",
  "template:",
  `  template_id: ${TEMPLATE_ID}`,
  `  description: ${PROJECT_NAME}, defined with the Project Builder`,
  "  version: '1'",
  "  variables:",
  "  - name: DATA_ROOT",
  "    description: The folder or s3:// prefix the collections are read from",
  "    required: true",
  `name: ${PROJECT_NAME}`,
  "project_type: advanced",
  "is_public: false",
  "workflows:",
  "- name: main",
  "  engine:",
  "    name: python",
  "  data_location:",
  "    structure: flat",
  "    locations:",
  "    - '{DATA_ROOT}'",
  "  data_collections:",
  "  - data_collection_tag: quant",
  "    config:",
  "      type: Table",
  "      metatype: Aggregate",
  "      scan:",
  "        mode: recursive",
  "        scan_parameters:",
  "          regex_config:",
  `            pattern: ${QUANT_REGEX}`,
  "      dc_specific_properties:",
  "        format: tsv",
  "        polars_kwargs:",
  String.raw`          separator: "\t"`,
  "  - data_collection_tag: samples",
  "    config:",
  "      type: Table",
  "      metatype: Metadata",
  "      scan:",
  "        mode: single",
  "        scan_parameters:",
  "          filename: '{DATA_ROOT}/samples.csv'",
  "      dc_specific_properties:",
  "        format: csv",
  "        polars_kwargs:",
  "          separator: ','",
  "",
].join("\n");

const TEMPLATE_RESULT = { template: TEMPLATE, yaml: TEMPLATE_YAML, template_id: TEMPLATE_ID, warnings: [] };

/** The draft the page sends for those two collections. */
const EXPECTED_DRAFT = {
  name: PROJECT_NAME,
  workflows: [
    {
      name: "main",
      engine: "python",
      structure: "flat",
      data_collections: [
        {
          tag: "quant",
          type: "table",
          mode: "recursive",
          glob: "quant/S*.tsv",
          regex: QUANT_REGEX,
          props: { kind: "table", format: "tsv", separator: "\t" },
        },
        {
          tag: "samples",
          type: "table",
          mode: "single",
          path: "samples.csv",
          props: { kind: "table", format: "csv", separator: "," },
        },
      ],
    },
  ],
};

/** The dry run (`from_run` or the standalone `/plan`) of that template. */
function plan(root: string): Json {
  return {
    project_id: null,
    project_name: PROJECT_NAME,
    template_id: TEMPLATE_ID,
    detected_template: null,
    data_root: root,
    detected_runs: [],
    resolved_variables: {},
    data_collections: [
      {
        data_collection_tag: "quant",
        kind: "scan",
        mode: "recursive",
        location: root,
        matched: 3,
        missing_sources: [],
        optional: false,
        status: "ok",
        rule: QUANT_REGEX,
        samples: ["S1", "S2", "S3"].map((s) => `${root}/quant/${s}.tsv`),
        found_in: "quant",
        recipe: null,
      },
      {
        data_collection_tag: "samples",
        kind: "scan",
        mode: "single",
        location: `${root}/samples.csv`,
        matched: 1,
        missing_sources: [],
        optional: false,
        status: "ok",
        rule: `${root}/samples.csv`,
        samples: [`${root}/samples.csv`],
        found_in: null,
        recipe: null,
      },
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
  };
}

/** `/template`'s refusal of a regex Python cannot compile, word for word. */
const REGEX_REFUSAL = {
  detail: "'quant': invalid regex (look-behind requires fixed-width pattern).",
  code: "inline_template_invalid",
};

// ── Stubs ───────────────────────────────────────────────────────────────────

/** Fulfil, unless the page cancelled the request meanwhile (the builder
 *  aborts a suggestion or a match a newer edit supersedes). */
async function answer(route: Route, reply: StubAnswer): Promise<void> {
  try {
    await route.fulfill({ status: reply.status ?? 200, json: reply.json });
  } catch {
    // Cancelled by the page.
  }
}

interface BuilderCalls {
  tree: Json[];
  suggest: Json[];
  match: Json[];
  template: Json[];
  preview: Json[];
}

/** Stub the builder routes and the file preview for `root`; `template`
 *  answers `/template`. Returns every request body, by route, in order. */
async function stubBuilder(
  page: Page,
  root: string,
  template: (body: Json) => StubAnswer = () => ({ json: TEMPLATE_RESULT }),
): Promise<BuilderCalls> {
  const calls: BuilderCalls = { tree: [], suggest: [], match: [], template: [], preview: [] };
  const folders = listings(root);
  const files = previews(root);
  const body = (route: Route) => (route.request().postDataJSON() ?? {}) as Json;

  await page.route("**/api/v1/projects/builder/tree", async (route) => {
    const b = body(route);
    calls.tree.push(b);
    const path = String(b.path ?? "");
    const listing = folders[path];
    await answer(
      route,
      listing
        ? { json: listing }
        : { status: 404, json: { detail: `'${path}' is not a folder of the data root.`, code: "folder_missing" } },
    );
  });
  await page.route("**/api/v1/projects/builder/suggest", async (route) => {
    const b = body(route);
    calls.suggest.push(b);
    const examples = ((b.examples as string[] | undefined) ?? []).slice().sort().join(",");
    const known = SUGGESTIONS[`${b.path}|${examples}`];
    await answer(
      route,
      known
        ? { json: known }
        : { status: 404, json: { detail: `'${b.path}' is not a file of the data root.`, code: "file_missing" } },
    );
  });
  await page.route("**/api/v1/projects/builder/match", async (route) => {
    const b = body(route);
    calls.match.push(b);
    await answer(route, { json: matchFor(b.collection as Json) });
  });
  await page.route("**/api/v1/projects/builder/template", async (route) => {
    const b = body(route);
    calls.template.push(b);
    await answer(route, template(b));
  });
  await page.route("**/api/v1/projects/run_file_preview", async (route) => {
    const b = body(route);
    calls.preview.push(b);
    const known = files[String(b.location)];
    await answer(
      route,
      known
        ? { json: known }
        : { status: 404, json: { detail: "This file does not exist.", code: "run_file_missing" } },
    );
  });
  return calls;
}

/** Stub `/projects/from_run`; returns the request bodies, in order. */
async function stubFromRun(page: Page, reply: (body: Json) => StubAnswer): Promise<Json[]> {
  const bodies: Json[] = [];
  await page.route("**/api/v1/projects/from_run", async (route) => {
    const b = (route.request().postDataJSON() ?? {}) as Json;
    bodies.push(b);
    await answer(route, reply(b));
  });
  return bodies;
}

/** The ingestion run a created project starts: dispatched, then ingested. */
async function stubIngestionRun(page: Page): Promise<void> {
  let polls = 0;
  await page.route(`**/api/v1/projects/refresh_manifest/${RUN_ID}`, (route) => {
    polls += 1;
    const done = polls > 1;
    return route.fulfill({
      json: {
        project_id: PROJECT_ID,
        refreshed: ["quant", "samples"].map((tag) => ({
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
}

// ── Page helpers ────────────────────────────────────────────────────────────

const treeItem = (page: Page, path: string) =>
  page.locator(`[data-testid='builder-tree-item'][data-path='${path}']`);

const byTestId = (page: Page, id: string) => page.locator(`[data-testid='${id}']`);

/** Server mode: type the root and wait until it was read. */
async function chooseRoot(page: Page, root: string): Promise<void> {
  await byTestId(page, "builder-root-input").fill(root);
  await expect(byTestId(page, "builder-root-status")).toHaveAttribute("data-state", "ready");
}

/** Pick `path` in the tree (opening its folder first, if any). */
async function pickFile(page: Page, path: string): Promise<void> {
  const folder = path.includes("/") ? path.split("/")[0] : null;
  if (folder && (await treeItem(page, path).count()) === 0) await treeItem(page, folder).click();
  await treeItem(page, path).locator("[data-testid='builder-tree-file']").click();
}

/** The live matches settled on `count` files. */
async function expectMatches(page: Page, count: number): Promise<void> {
  await expect(byTestId(page, "builder-matches-count")).toHaveAttribute("data-count", String(count));
  await expect(byTestId(page, "builder-matches")).toHaveAttribute("data-state", "ready");
}

/** The two collections of the template: a scan generalised from two ticked
 *  example files, then a single file. Checks what the editor takes from
 *  `/suggest` on the way. */
async function addTwoCollections(page: Page, calls: BuilderCalls): Promise<void> {
  const tag = byTestId(page, "builder-dc-tag");

  await pickFile(page, "quant/S1.tsv");
  await expect(tag).toHaveValue("quant_s1");
  await expect(byTestId(page, "builder-dc-type")).toHaveValue("Table");
  await expectMatches(page, 1);
  // The picked file previews with each column's dtype.
  await expect(
    page.locator("[data-testid='file-preview-dtype'][data-column='count']"),
  ).toHaveText("Int64");
  expect(calls.preview.at(-1)).toMatchObject({
    data_root: DATA_ROOT,
    location: `${DATA_ROOT}/quant/S1.tsv`,
    infer_types: true,
  });

  await tag.fill("quant");
  // A second example turns the suggestion into a scan over the glob both share.
  await treeItem(page, "quant/S2.tsv").getByRole("checkbox").check();
  await expect(byTestId(page, "builder-dc-glob")).toHaveValue("quant/S*.tsv");
  await expect(byTestId(page, "builder-dc-regex")).toHaveValue(QUANT_REGEX);
  await expectMatches(page, 3);
  expect(calls.suggest.at(-1)).toMatchObject({ path: "quant/S1.tsv", examples: ["quant/S2.tsv"] });
  expect(calls.match.at(-1)?.collection).toMatchObject({ tag: "quant", mode: "recursive", regex: QUANT_REGEX });
  // Every file the scan matches is tinted in the tree, the unticked one too.
  await expect(treeItem(page, "quant/S3.tsv")).toHaveAttribute("data-matched", "true");

  await byTestId(page, "builder-add-dc").click();
  await expect(page.locator("[data-testid='builder-dc-card'][data-tag='quant']")).toBeVisible();
  for (const file of ["quant/S1.tsv", "quant/S2.tsv", "quant/S3.tsv"]) {
    await expect(treeItem(page, file)).toHaveAttribute("data-claimed-tag", "quant");
  }

  await pickFile(page, "samples.csv");
  await expect(tag).toHaveValue("samples");
  await expectMatches(page, 1);
  await byTestId(page, "builder-add-dc").click();
  await expect(page.locator("[data-testid='builder-dc-card'][data-tag='samples']")).toBeVisible();
  await expect(treeItem(page, "samples.csv")).toHaveAttribute("data-claimed-tag", "samples");
}

/** On the review step: the template the draft makes is on screen. */
async function expectTemplateShown(page: Page): Promise<void> {
  const yaml = byTestId(page, "builder-review-yaml");
  await expect(yaml).toContainText(`template_id: ${TEMPLATE_ID}`);
  await expect(yaml).toContainText(`pattern: ${QUANT_REGEX}`);
}

// ── Server mode ─────────────────────────────────────────────────────────────

test.describe("Project Builder", () => {
  // As create-from-run.spec.ts: for admins in standard and single-user mode;
  // public mode does not exercise project creation.
  test.beforeEach(async ({ page }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Project creation is not exercised in public mode.");
    await mockTemplates(page);
    await setRunFolderFlags(page, { local: true, remote: false });
  });

  test("the create dialog's advanced project card opens the builder", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/projects");
    await page.locator("[data-tour-id='projects-create']").click();

    const card = byTestId(page, "create-project-builder-card");
    await expect(card).toContainText("Project Builder");
    await expect(card).not.toHaveAttribute("aria-disabled", "true");
    await card.click();

    await expect(page).toHaveURL(/\/projects\/build$/);
    await expect(byTestId(page, "builder-title")).toHaveText("Project Builder");
    await expect(byTestId(page, "builder-root-input")).toBeVisible();
  });

  test("an unrecognised pipeline hands its folder to the builder, once", async ({
    loginAsAdmin,
    page,
  }) => {
    await stubByParam(page, "**/api/v1/projects/folder_inspect**", "location", {
      [S3_ROOT]: {
        status: 502,
        json: { detail: "The storage did not answer in time.", code: "s3_unreachable" },
      },
    });
    await stubFromRun(page, () => ({
      status: 422,
      json: {
        detail: "No installed template matches the pipeline that produced this folder.",
        code: "template_not_detected",
      },
    }));
    const calls = await stubBuilder(page, S3_ROOT);

    await loginAsAdmin();
    await openRunTab(page);
    await byTestId(page, "run-data-root-input").fill(S3_ROOT);
    await expect(byTestId(page, "run-detection-card")).toHaveAttribute("data-state", "error", {
      timeout: 20_000,
    });
    await byTestId(page, "create-from-run-submit").click();

    const notDetected = byTestId(page, "run-template-not-detected");
    await expect(notDetected).toBeVisible({ timeout: 20_000 });
    await notDetected.locator("[data-testid='run-define-collections-preview']").click();

    // The builder opens on that folder and reads it; the hand-off is gone.
    await expect(page).toHaveURL(/\/projects\/build$/);
    await expect(byTestId(page, "builder-root-input")).toHaveValue(S3_ROOT);
    await expect(byTestId(page, "builder-root-status")).toHaveAttribute("data-state", "ready");
    expect(calls.tree[0]?.root, "no private bucket details were handed over").toEqual({
      data_root: S3_ROOT,
    });
    await expect
      .poll(() => page.evaluate((key) => window.sessionStorage.getItem(key), HANDOFF_KEY))
      .toBeNull();
  });

  test("a folder no template matches offers the builder from the source step", async ({
    loginAsAdmin,
    page,
  }) => {
    await stubByParam(page, "**/api/v1/projects/folder_inspect**", "location", {
      [S3_ROOT]: {
        json: inspection(S3_ROOT, {
          folders: { count: 1, names: ["quant"] },
          files: { count: 2, names: ["samples.csv", "tree.nwk"] },
          detected: null,
        }),
      },
    });
    await stubBuilder(page, S3_ROOT);

    await loginAsAdmin();
    await openRunTab(page);
    await byTestId(page, "run-data-root-input").fill(S3_ROOT);
    await expect(byTestId(page, "run-detection-card")).toHaveAttribute("data-state", "ready", {
      timeout: 20_000,
    });
    await byTestId(page, "run-define-collections").click();

    await expect(page).toHaveURL(/\/projects\/build$/);
    await expect(byTestId(page, "builder-root-input")).toHaveValue(S3_ROOT);
    await expect
      .poll(() => page.evaluate((key) => window.sessionStorage.getItem(key), HANDOFF_KEY))
      .toBeNull();
  });

  test("groups files into collections, previews the plan, then creates the project", async ({
    loginAsAdmin,
    page,
  }) => {
    const calls = await stubBuilder(page, DATA_ROOT);
    const fromRun = await stubFromRun(page, (b) =>
      b.dry_run
        ? { json: plan(DATA_ROOT) }
        : {
            json: {
              ...plan(DATA_ROOT),
              project_id: PROJECT_ID,
              run_id: RUN_ID,
              dry_run: false,
              success: true,
            },
          },
    );
    await stubIngestionRun(page);

    await loginAsAdmin();
    await page.goto("/projects/build");

    // Source & project.
    await chooseRoot(page, DATA_ROOT);
    expect(calls.tree[0]).toEqual({ root: { data_root: DATA_ROOT }, path: "" });
    await byTestId(page, "builder-project-name").fill(PROJECT_NAME);
    await byTestId(page, "builder-next").click();

    await addTwoCollections(page, calls);

    // Review: the template the draft makes.
    await byTestId(page, "builder-next").click();
    await expectTemplateShown(page);
    expect(calls.template.at(-1)).toEqual({ draft: EXPECTED_DRAFT, remote: false });

    // The dry run carries the inline template, never a template id.
    await expect(byTestId(page, "builder-plan")).toBeEnabled();
    await byTestId(page, "builder-plan").click();
    await expect(
      page.locator("[data-testid='builder-plan-report'] [data-testid='run-preview-report']"),
    ).toBeVisible();
    await expect(byTestId(page, "run-match-summary")).toHaveText("2 of 2 collections ready");
    const dryRun = fromRun[0];
    expect(dryRun).toMatchObject({
      data_root: DATA_ROOT,
      project_name: PROJECT_NAME,
      dry_run: true,
    });
    expect(dryRun.template).toEqual(TEMPLATE);
    expect(dryRun).not.toHaveProperty("template_id");
    expect(dryRun).not.toHaveProperty("storage");

    // Create for real, and watch the ingestion it started.
    const create = byTestId(page, "builder-create");
    await expect(create).toBeEnabled();
    await create.click();
    const modal = byTestId(page, "run-created-modal");
    await expect(modal).toBeVisible({ timeout: 20_000 });
    const created = fromRun.find((b) => b.dry_run === false);
    expect(created, "the real (non dry-run) create was sent").toBeTruthy();
    expect(created?.template).toEqual(TEMPLATE);
    expect(created).not.toHaveProperty("template_id");
    await expect(modal.locator("[data-testid='run-created-status']")).toHaveAttribute(
      "data-state",
      "success",
      { timeout: 30_000 },
    );

    // The project exists: the draft kept for this folder is dropped.
    await expect
      .poll(() =>
        page.evaluate(
          (key) => window.localStorage.getItem(key),
          `depictio:project-builder:draft:v1:${DATA_ROOT}`,
        ),
      )
      .toBeNull();
  });

  test("a draft the server refuses shows its reason, word for word", async ({
    loginAsAdmin,
    page,
  }) => {
    const calls = await stubBuilder(page, DATA_ROOT, () => ({ status: 422, json: REGEX_REFUSAL }));

    await loginAsAdmin();
    await page.goto("/projects/build");
    await chooseRoot(page, DATA_ROOT);
    await byTestId(page, "builder-project-name").fill(PROJECT_NAME);
    await byTestId(page, "builder-next").click();

    // A tree is one file: the page does not offer to scan for it.
    await pickFile(page, "tree.nwk");
    await expect(byTestId(page, "builder-dc-type")).toHaveValue("Phylogeny");
    await expect(byTestId(page, "file-preview-text")).toContainText("((S1:0.1,S2:0.2)");
    await expect(byTestId(page, "builder-dc-mode").locator("input[value='recursive']")).toBeDisabled();

    // A regex the browser compiles and the server's Python does not.
    await pickFile(page, "quant/S1.tsv");
    await byTestId(page, "builder-dc-tag").fill("quant");
    await byTestId(page, "builder-dc-mode").getByText("Scan (pattern)").click();
    await byTestId(page, "builder-dc-regex").fill(LOOKBEHIND_REGEX);
    await expectMatches(page, 3);
    await byTestId(page, "builder-add-dc").click();
    await expect(page.locator("[data-testid='builder-dc-card'][data-tag='quant']")).toBeVisible();

    await byTestId(page, "builder-next").click();
    const error = byTestId(page, "builder-template-error");
    await expect(error).toContainText(REGEX_REFUSAL.detail);
    await expect(error).toContainText("The server refused the draft");
    expect(calls.template.at(-1)?.draft).toMatchObject({
      workflows: [
        { data_collections: [{ tag: "quant", mode: "recursive", regex: LOOKBEHIND_REGEX }] },
      ],
    });

    // Nothing to preview or create from.
    await expect(byTestId(page, "builder-review-yaml")).toHaveCount(0);
    await expect(byTestId(page, "builder-plan")).toBeDisabled();
    await expect(byTestId(page, "builder-create-reason")).toContainText(
      "The template could not be built.",
    );
  });
});

// ── Standalone mode ─────────────────────────────────────────────────────────

/** Serve `/projects/build` as `depictio project-builder` does: the SPA's own
 *  page with the `depictio-mode` meta tag in its head. */
async function serveStandalone(page: Page): Promise<void> {
  await page.route(/\/projects\/build\/?$/, async (route) => {
    if (route.request().resourceType() !== "document") return route.fallback();
    const response = await route.fetch();
    const html = (await response.text()).replace(
      "<head>",
      '<head><meta name="depictio-mode" content="project-builder">',
    );
    const headers: Record<string, string> = {
      ...response.headers(),
      "content-type": "text/html; charset=utf-8",
    };
    delete headers["content-length"];
    delete headers["content-encoding"];
    await route.fulfill({ status: response.status(), headers, body: html });
  });
}

test.describe("Project Builder, standalone", () => {
  test("boots without a session on the served folder and writes the template next to it", async ({
    page,
  }) => {
    const OUT_DIR = `${DATA_ROOT}/.depictio/template`;
    const BUNDLE = `${OUT_DIR}/template.yaml`;
    const INGEST = `depictio ingest ${DATA_ROOT} --template ${BUNDLE}`;

    await serveStandalone(page);
    await page.route("**/api/v1/projects/builder/context", (route) =>
      route.fulfill({
        json: { mode: "standalone", data_root: DATA_ROOT, out_dir: OUT_DIR, writable: true },
      }),
    );
    const calls = await stubBuilder(page, DATA_ROOT);
    const plans: Json[] = [];
    await page.route("**/api/v1/projects/builder/plan", async (route) => {
      plans.push((route.request().postDataJSON() ?? {}) as Json);
      await answer(route, { json: plan(DATA_ROOT) });
    });
    const writes: Json[] = [];
    await page.route("**/api/v1/projects/builder/write", async (route) => {
      const b = (route.request().postDataJSON() ?? {}) as Json;
      writes.push(b);
      await answer(
        route,
        b.overwrite
          ? { json: { path: BUNDLE, yaml: TEMPLATE_YAML, ingest_command: INGEST } }
          : {
              status: 409,
              json: {
                detail: `${BUNDLE} already exists. Overwrite it to replace it.`,
                code: "bundle_exists",
              },
            },
      );
    });

    // No session exists, and none is asked for.
    const authCalls: string[] = [];
    page.on("request", (request) => {
      if (/\/api\/v1\/auth\//.test(request.url())) authCalls.push(request.url());
    });
    const visited: string[] = [];
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) visited.push(new URL(frame.url()).pathname);
    });

    await page.goto("/projects/build");
    await expect(byTestId(page, "builder-root-fixed")).toHaveText(DATA_ROOT);
    await expect(byTestId(page, "builder-root-input")).toHaveCount(0);
    await byTestId(page, "builder-project-name").fill(PROJECT_NAME);
    await byTestId(page, "builder-next").click();

    await addTwoCollections(page, calls);
    await byTestId(page, "builder-next").click();
    await expectTemplateShown(page);

    await expect(byTestId(page, "builder-plan")).toBeEnabled();
    await byTestId(page, "builder-plan").click();
    await expect(
      page.locator("[data-testid='builder-plan-report'] [data-testid='run-preview-report']"),
    ).toBeVisible();
    expect(plans[0]?.template).toEqual(TEMPLATE);

    // A bundle is there already: replacing it is confirmed first.
    const write = byTestId(page, "builder-write");
    await expect(write).toBeEnabled();
    await write.click();
    await expect(byTestId(page, "builder-overwrite-confirm")).toBeVisible();
    await byTestId(page, "builder-overwrite-confirm-button").click();

    await expect(byTestId(page, "builder-written-path")).toHaveText(BUNDLE);
    await expect(byTestId(page, "builder-ingest-command")).toHaveText(INGEST);
    expect(writes.map((b) => b.overwrite)).toEqual([false, true]);
    expect(writes[1]?.template).toEqual(TEMPLATE);

    await expect(page).toHaveURL(/\/projects\/build$/);
    expect(visited.filter((path) => path.startsWith("/auth")), "never sent to the login page").toEqual(
      [],
    );
    expect(authCalls, "no session bootstrap").toEqual([]);
  });
});
