/**
 * The catalog picker's *usability* contract: every render the catalog offers
 * can be added to a dashboard through the real picker, and the component it
 * produces renders on its home surface — in the editor and in the viewer.
 *
 * "Home surface" is load-bearing. Not every component takes a grid tile:
 * interactive ones never do, and live in the left filter panel instead. See
 * HOME below.
 *
 * Data-driven off the compose endpoint, like its companion registration spec,
 * so a newly-authored module is covered the moment it matches a collection.
 *
 * Components are added in batches onto throwaway dashboards rather than all
 * onto one: a dashboard is re-rendered after every add, so a single 60-tile
 * dashboard would spend most of the run re-drawing tiles already asserted, and
 * a failure in it would be far harder to read than a failure on a six-tile one.
 *
 * Env knobs:
 *   CATALOG_E2E_RENDERS=first  only the first render of each output (fast smoke)
 *   CATALOG_E2E_BATCH=N        components per throwaway dashboard (default 6)
 *   CATALOG_E2E_LIMIT=N        stop after N renders per project (smoke run)
 *   CATALOG_E2E_SHARD=K
 *   CATALOG_E2E_SHARDS=N       walk only shard K of N (see SHARD below)
 *   CATALOG_E2E_LANES=N        split this shard across N parallel tests
 */
import { APIRequestContext, Page, expect as pwExpect } from "@playwright/test";
import { test, expect, apiLogin } from "../../fixtures/auth";
import { credentials } from "../../fixtures/credentials";
import {
  addCatalogRender,
  createDashboard,
  deleteDashboard,
  findCatalogProjects,
  flattenOffers,
  MULTIQC_WARM_TIMEOUT_MS,
  storedComponentIds,
  waitForMultiqcOptions,
  CatalogProject,
  RenderOffer,
} from "../../fixtures/catalog";

const BATCH = Number(process.env.CATALOG_E2E_BATCH ?? 6);
const FIRST_RENDER_ONLY = process.env.CATALOG_E2E_RENDERS === "first";
// Smoke-run cap: exercise the first N renders of each project instead of all.
const LIMIT = Number(process.env.CATALOG_E2E_LIMIT ?? 0);

/**
 * Which slice of the catalog this job owns.
 *
 * The walk is auth-mode independent — nothing on the catalog -> builder ->
 * viewer path branches on public / demo / single-user mode — so the CI matrix's
 * three legs were each re-walking the identical several hundred renders. They
 * now take a shard each: the union is still the whole catalog, once per run, at
 * a third of the wall clock, because the legs already run in parallel on
 * separate stacks.
 *
 * Defaults to 1 of 1, i.e. the whole catalog, so a local run and any leg that
 * does not set these keep full coverage.
 */
const SHARD = Number(process.env.CATALOG_E2E_SHARD ?? 1);
const SHARDS = Number(process.env.CATALOG_E2E_SHARDS ?? 1);
if (
  !Number.isInteger(SHARD) ||
  !Number.isInteger(SHARDS) ||
  SHARDS < 1 ||
  SHARD < 1 ||
  SHARD > SHARDS
) {
  // Loud on purpose: a shard silently out of range is a third of the catalog
  // quietly going unwalked while CI stays green.
  throw new Error(`bad CATALOG_E2E_SHARD=${SHARD} of CATALOG_E2E_SHARDS=${SHARDS}`);
}

/**
 * How many parallel tests this shard is split into.
 *
 * The walk used to be a single test, so it held one worker for an hour while
 * the other finished the rest of the suite in ten minutes and then sat idle.
 * State is already isolated per batch — a throwaway dashboard created and
 * deleted around every six renders, random component ids, a stored-component
 * check scoped to one dashboard — so nothing but the stack is shared between
 * lanes. Expect roughly 1.5x from a second lane rather than 2x: the backend
 * runs a single uvicorn worker and shares the runner with mongo, redis, minio
 * and celery.
 */
const LANES = Number(process.env.CATALOG_E2E_LANES ?? 1);
if (!Number.isInteger(LANES) || LANES < 1) {
  throw new Error(`bad CATALOG_E2E_LANES=${LANES}`);
}

/**
 * Where a component of each type is *supposed* to render.
 *
 * `interactive` never takes a grid tile, by design: both apps filter it out of
 * the grid and route it to the left filter panel — placement 'left', the model
 * default — or to the top band, which is allow-listed to Timeline. Looking for
 * one on the grid was asserting the opposite of the product contract, which is
 * why the MultiSelect renders the catalog offers could only ever fail on the
 * viewer. Reach for this table, not for the walk, when a new component type
 * turns up somewhere other than the grid.
 *
 * placement 'top' is unreachable from the catalog — the catalog's Render model
 * declares no placement field and forbids extras — so "filter panel" covers
 * every interactive render this walk can produce.
 */
type Home = "grid" | "filter panel";
const HOME: Record<string, Home> = { interactive: "filter panel" };
const homeOf = (offer: RenderOffer): Home => HOME[offer.render.component] ?? "grid";
const HOME_ROOT: Record<Home, string> = {
  grid: "[data-testid='dashboard-content']",
  "filter panel": "[data-tour-id='filter-panel']",
};

/** The frame a renderer owns, whatever it managed to draw inside it. */
const CHROME_SELECTOR = ".depictio-component-chrome";

/** What "it rendered" means, per component type.
 *
 * image, jbrowse, map and text have no entry because the catalog offers none
 * of them today. They are all grid-homed, so only the content assertion is
 * missing for them, and the stuck-skeleton check below stands in for it.
 */
const CONTENT_SELECTOR: Record<string, string> = {
  card: ".depictio-card",
  table: ".ag-root-wrapper",
  figure: ".js-plotly-plot",
  advanced_viz: ".js-plotly-plot",
  multiqc: ".js-plotly-plot",
  // The panel emits the cell wrapper whether or not the renderer produced
  // anything, so the chrome is the first DOM the component itself owns.
  interactive: CHROME_SELECTOR,
};

/** How long to wait for CONTENT_SELECTOR, per component type.
 *
 * A MultiQC tile does not own its figure: the backend builds every figure of a
 * report on first request and 202s until they are ready, and MultiQCFigure
 * polls for that for up to 5 minutes (PREPARE_POLL_MAX_MS), documenting a
 * 30-75s shimmer on a cold collection. The default budget below sits inside
 * that window, so the first few MultiQC tiles of a run were failing on a build
 * that was still legitimately in progress, then passing on retry once the
 * report was warm. Every other component type computes its own frame and is
 * held to the shorter budget.
 */
const CONTENT_TIMEOUT_MS: Record<string, number> = { multiqc: 150_000 };
const DEFAULT_CONTENT_TIMEOUT_MS = 60_000;

interface Checked {
  problem: string | null;
  /** Does the tile span its whole grid row? Compared across surfaces. */
  fullWidth?: boolean;
}

/**
 * Assert one added component is present and healthy on the page currently
 * loaded. Returns a problem string instead of throwing so one broken module
 * doesn't hide the twenty after it.
 */
async function checkComponent(
  page: Page,
  componentId: string,
  offer: RenderOffer,
  surface: string,
): Promise<Checked> {
  const home = homeOf(offer);
  // .first(): data-tour-id="filter-panel" sits on both the collapsed rail and
  // the expanded panel, and a narrow viewport mounts a second copy in a Drawer.
  // Only one of them is ever in the DOM at this viewport; .first() makes which
  // one not matter.
  const root = page.locator(HOME_ROOT[home]).first();
  const cell = root.locator(`[data-component-id='${componentId}']`);
  try {
    await pwExpect(cell).toBeVisible({ timeout: 30_000 });
  } catch {
    // "Absent" and "ambiguous" need different answers. A duplicated id fails
    // strict mode, and reporting that as "not there at all" is how a real bug
    // hides behind a message about a missing one.
    const found = await cell.count().catch(() => 0);
    return {
      problem:
        found === 0
          ? `${offer.label}: not in the ${surface} ${home} at all`
          : `${offer.label}: ${found} nodes carry this component id in the ${surface} ${home}`,
    };
  }

  // The other half of the placement contract. If the interactive filter in the
  // two apps' grid lists were ever dropped, a filter control would start
  // claiming a tile — and, carrying no layout entry, would be auto-placed on
  // top of another one — while still passing the check above.
  if (home !== "grid") {
    const strays = await page
      .locator(`${HOME_ROOT.grid} [data-component-id='${componentId}']`)
      .count();
    if (strays > 0) {
      return { problem: `${offer.label}: also took a tile on the ${surface} grid` };
    }
  }

  // Advanced-viz, MultiQC and JBrowse cells are behind a viewport gate
  // (LazyMount): below the fold they render a skeleton and never fetch. A tile
  // the user has not scrolled to is not a broken tile, so scroll to it before
  // asking whether it drew.
  await cell.scrollIntoViewIfNeeded().catch(() => undefined);

  // How wide the tile is relative to its grid — the editor and the viewer must
  // agree. They size their grids from different containers, so compare the
  // spans-the-row verdict rather than the pixels.
  //
  // Grid-homed components only: "spans the row" is a grid property. The filter
  // panel is one column wide and every control spans it, and in the viewer the
  // panel has no react-grid ancestor at all (its grid is edit-mode only), so
  // measuring there would read true in the editor and false in the viewer and
  // flag every filter as a cross-surface disagreement.
  const fullWidth =
    home === "grid"
      ? await cell.evaluate((node) => {
          const item =
            (node as HTMLElement).closest(".react-grid-item") ?? (node as HTMLElement);
          const grid = item.closest(".react-grid-layout");
          if (!grid) return false;
          return (
            item.getBoundingClientRect().width >= grid.getBoundingClientRect().width - 24
          );
        })
      : undefined;

  const selector = CONTENT_SELECTOR[offer.render.component];
  if (selector) {
    const budget =
      CONTENT_TIMEOUT_MS[offer.render.component] ?? DEFAULT_CONTENT_TIMEOUT_MS;
    try {
      await pwExpect(cell.locator(selector).first()).toBeVisible({ timeout: budget });
    } catch {
      const text = (await cell.innerText().catch(() => "")).trim().slice(0, 200);
      // Distinguish "still working" from "broken": the two need different
      // answers, and the message is the only evidence a CI log keeps.
      const stillPreparing = text.includes("Preparing MultiQC figures");
      const why = stillPreparing
        ? `still preparing after ${budget / 1000}s`
        : `nothing matching '${selector}' rendered`;
      return {
        problem: `${offer.label}: ${why} on the ${surface} — cell reads: ${text || "(empty)"}`,
        fullWidth,
      };
    }
  }

  // A chrome proves a frame exists, not that the first load finished: a
  // renderer puts its loading skeleton *inside* that frame. A real content
  // selector (a plotly div, an ag-grid root) already implies the load landed;
  // the chrome and no-selector-at-all do not, so those are checked explicitly.
  // Every skeleton, and only a skeleton, carries aria-busy.
  if (!selector || selector === CHROME_SELECTOR) {
    try {
      await pwExpect(cell.locator("[aria-busy]")).toHaveCount(0, { timeout: 30_000 });
    } catch {
      return {
        problem: `${offer.label}: still showing a loading skeleton on the ${surface}`,
        fullWidth,
      };
    }
  }

  const errorCount = await cell.locator(".dashboard-error").count();
  if (errorCount > 0) {
    const text = (await cell.locator(".dashboard-error").first().innerText()).trim();
    return { problem: `${offer.label}: error state on the ${surface} — ${text}`, fullWidth };
  }
  return { problem: null, fullWidth };
}

test.describe("catalog modules are usable on a dashboard", () => {
  // Parallel, not serial: the lanes below are independent, and a serial retry
  // re-runs the whole group — which is precisely how one failed attempt cost a
  // full hour on top of the two the walk already needed.
  test.describe.configure({ mode: "parallel" });

  let tokens: Awaited<ReturnType<typeof apiLogin>>;
  let projects: CatalogProject[] = [];

  test.beforeAll(async ({ request }) => {
    // Hooks take their budget from the project timeout (60s), not from the
    // test's own setTimeout, and describe.configure({ timeout }) does not reach
    // them either — so this has to be set here. The dominant term is the
    // MultiQC warm-up at the bottom of this hook, so the budget is derived from
    // it: a hook that expires first reports a bare hook timeout and fails every
    // lane at 0ms, hiding the collection that actually never warmed up. The
    // slack on top covers the login (up to ~52s of limiter backoff) and one
    // compose call per catalog project on the stack.
    test.setTimeout(MULTIQC_WARM_TIMEOUT_MS + 120_000);
    tokens = await apiLogin(request, credentials.adminUser.email, credentials.adminUser.password);
    projects = await findCatalogProjects(request, tokens);

    // Warm every data collection a MultiQC render would be added from, before
    // the first add rather than during it. See waitForMultiqcOptions: the
    // picker persists what the builder options say at click time, so a cold
    // collection is saved as a component with no plot and only fails later.
    const multiqcDcIds = [
      ...new Set(
        projects
          .flatMap((p) => flattenOffers(p.modules))
          .filter((o) => o.render.component === "multiqc")
          .map((o) => o.match.dc_id),
      ),
    ];
    const cold = await waitForMultiqcOptions(request, tokens, multiqcDcIds);
    if (cold.length) {
      console.log(`multiqc options never came up for: ${cold.join(", ")}`);
    }
  });

  const walkLane = async (lane: number, page: Page, request: APIRequestContext) => {
    test.skip(
      projects.length === 0,
      "no ingested tool output on this stack — nothing for the catalog to match",
    );
    // Still generous — the walk is one browser doing a full add cycle per
    // render — but a shard split across lanes is a fraction of the old whole,
    // and an hour of budget is an hour of budget actually spent when the walk
    // hangs rather than fails.
    test.setTimeout(30 * 60_000);

    // Programmatic login only seeds storage — the SPA reads it on first load.
    await page.addInitScript(
      (t) => {
        window.localStorage.setItem(
          "local-store",
          JSON.stringify({
            access_token: t.access_token,
            refresh_token: t.refresh_token,
            logged_in: true,
            user_id: t.user_id,
            email: t.email ?? "",
          }),
        );
      },
      { ...tokens, email: credentials.adminUser.email },
    );

    const problems: string[] = [];
    let added = 0;

    // Both counters run across projects, not per project, so each project is
    // split evenly rather than by where its boundary happens to fall.
    let seq = 0;
    let laneSeq = 0;

    const work = projects.map((project) => {
      let offers = flattenOffers(project.modules)
        // A stable order is what makes the union of the shards provably the
        // whole catalog. Compose ordering is derived from the project document
        // and is deterministic today; sorting removes the dependency on that.
        .sort((a, b) => a.label.localeCompare(b.label));
      if (FIRST_RENDER_ONLY) offers = offers.filter((o) => o.renderIndex === 0);
      if (LIMIT > 0) offers = offers.slice(0, LIMIT);
      // Round-robin rather than a contiguous slice: renders come grouped by
      // tool and by type, so a contiguous third would hand one leg all the
      // cheap cards and another all the MultiQC cold builds. A no-op at 1 of 1.
      offers = offers.filter(() => seq++ % SHARDS === SHARD - 1);
      // And again to split this shard between the lanes. A no-op at 1 lane.
      offers = offers.filter(() => laneSeq++ % LANES === lane);
      return { project, offers };
    });
    test.skip(
      work.every((w) => w.offers.length === 0),
      "nothing in this shard and lane to walk on this stack",
    );

    for (const { project, offers } of work) {
      for (let start = 0; start < offers.length; start += BATCH) {
        const batch = offers.slice(start, start + BATCH);
        const title = `e2e catalog ${project.id.slice(-6)} s${SHARD} ${start / BATCH + 1}`;
        // A full walk outlives an access token, and an expired one turns the
        // cleanup at the end of each batch into a silent 401 that leaves the
        // throwaway dashboards behind. One login per batch is cheap.
        tokens = await apiLogin(
          request,
          credentials.adminUser.email,
          credentials.adminUser.password,
        );
        const dashboardId = await createDashboard(request, tokens, project.id, title);

        try {
          const placed: Array<{
            componentId: string;
            offer: RenderOffer;
            fullWidthInEditor?: boolean;
          }> = [];
          for (const offer of batch) {
            await test
              .step(`add ${offer.label}`, async () => {
                const componentId = await addCatalogRender(page, dashboardId, offer);
                const entry: (typeof placed)[number] = { componentId, offer };
                placed.push(entry);
                added += 1;
                // Assert on the editor we just landed on, before moving to the
                // next add. Two reasons: the failure points at one render
                // instead of a batch, and waiting for the tile to draw lets the
                // editor's debounced layout save settle — navigating away
                // mid-debounce is how a component went missing from the
                // dashboard it had just been saved to.
                const checked = await checkComponent(page, componentId, offer, "editor");
                entry.fullWidthInEditor = checked.fullWidth;
                if (checked.problem) problems.push(checked.problem);
              })
              .catch((e: unknown) => problems.push(`${offer.label}: add failed — ${e}`));
          }
          if (placed.length === 0) continue;

          // Nothing may have dropped out of the document along the way.
          const stored = await storedComponentIds(request, tokens, dashboardId);
          for (const { componentId, offer } of placed) {
            if (!stored.has(componentId)) {
              problems.push(`${offer.label}: saved, then vanished from the dashboard`);
            }
          }

          // The viewer is a different surface with a different container width
          // and no edit chrome — a component can render in one and not the other.
          await page.goto(`/dashboard/${dashboardId}`);
          for (const { componentId, offer, fullWidthInEditor } of placed) {
            const checked = await checkComponent(page, componentId, offer, "viewer");
            if (checked.problem) problems.push(checked.problem);
            if (
              checked.fullWidth !== undefined &&
              fullWidthInEditor !== undefined &&
              checked.fullWidth !== fullWidthInEditor
            ) {
              problems.push(
                `${offer.label}: spans the row in the ` +
                  `${checked.fullWidth ? "viewer" : "editor"} but not in the ` +
                  `${checked.fullWidth ? "editor" : "viewer"}`,
              );
            }
          }
        } finally {
          await deleteDashboard(request, tokens, dashboardId);
        }
      }
    }

    // eslint-disable-next-line no-console
    const scope = SHARDS > 1 ? ` (shard ${SHARD} of ${SHARDS})` : "";
    const laneScope = LANES > 1 ? ` lane ${lane + 1} of ${LANES}` : "";
    console.log(
      `added ${added} catalog renders across ${projects.length} project(s)${scope}${laneScope}`,
    );
    expect(added, "no catalog render was added at all").toBeGreaterThan(0);
    expect(problems, `\n${problems.join("\n")}\n`).toEqual([]);
  };

  for (let lane = 0; lane < LANES; lane++) {
    const suffix = LANES > 1 ? ` (lane ${lane + 1} of ${LANES})` : "";
    test(`every catalog render adds and renders${suffix}`, async ({ page, request }) => {
      await walkLane(lane, page, request);
    });
  }
});
