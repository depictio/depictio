/**
 * The catalog picker's *usability* contract: every render the catalog offers
 * can be added to a dashboard through the real picker, and the component it
 * produces renders — in the editor and in the viewer.
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
 */
import { Page, expect as pwExpect } from "@playwright/test";
import { test, expect, apiLogin } from "../../fixtures/auth";
import { credentials } from "../../fixtures/credentials";
import {
  addCatalogRender,
  createDashboard,
  deleteDashboard,
  findCatalogProjects,
  flattenOffers,
  storedComponentIds,
  waitForMultiqcOptions,
  CatalogProject,
  RenderOffer,
} from "../../fixtures/catalog";

const BATCH = Number(process.env.CATALOG_E2E_BATCH ?? 6);
const FIRST_RENDER_ONLY = process.env.CATALOG_E2E_RENDERS === "first";
// Smoke-run cap: exercise the first N renders of each project instead of all.
const LIMIT = Number(process.env.CATALOG_E2E_LIMIT ?? 0);

/** What "it rendered" means, per component type. */
const CONTENT_SELECTOR: Record<string, string> = {
  card: ".depictio-card",
  table: ".ag-root-wrapper",
  figure: ".js-plotly-plot",
  advanced_viz: ".js-plotly-plot",
  multiqc: ".js-plotly-plot",
};

/** How long a component gets to draw, when the default is not enough.
 *
 * A MultiQC figure is prepared server-side on first request: the component
 * polls for up to PREPARE_POLL_MAX_MS (300s, MultiQCFigure.tsx) and shows
 * "Preparing MultiQC figures…" meanwhile, with the comment there putting a cold
 * data collection at 30-75s. Asserting on a 60s budget inside that window is
 * what made this spec flaky. 120s sits clear of the documented range while
 * still failing well before the component gives up, so a genuinely broken tile
 * does not cost five minutes. */
const CONTENT_TIMEOUT: Record<string, number> = { multiqc: 120_000 };
const DEFAULT_CONTENT_TIMEOUT = 60_000;

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
  const cell = page.locator(`[data-component-id='${componentId}']`);
  try {
    await pwExpect(cell).toBeVisible({ timeout: 30_000 });
  } catch {
    return { problem: `${offer.label}: not on the ${surface} grid at all` };
  }

  // Advanced-viz, MultiQC and JBrowse cells are behind a viewport gate
  // (LazyMount): below the fold they render a skeleton and never fetch. A tile
  // the user has not scrolled to is not a broken tile, so scroll to it before
  // asking whether it drew.
  await cell.scrollIntoViewIfNeeded().catch(() => undefined);

  // How wide the tile is relative to its grid — the editor and the viewer must
  // agree. They size their grids from different containers, so compare the
  // spans-the-row verdict rather than the pixels.
  const fullWidth = await cell.evaluate((node) => {
    const item = (node as HTMLElement).closest(".react-grid-item") ?? (node as HTMLElement);
    const grid = item.closest(".react-grid-layout");
    if (!grid) return false;
    return item.getBoundingClientRect().width >= grid.getBoundingClientRect().width - 24;
  });

  const selector = CONTENT_SELECTOR[offer.render.component];
  if (selector) {
    const budget = CONTENT_TIMEOUT[offer.render.component] ?? DEFAULT_CONTENT_TIMEOUT;
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

  const errorCount = await cell.locator(".dashboard-error").count();
  if (errorCount > 0) {
    const text = (await cell.locator(".dashboard-error").first().innerText()).trim();
    return { problem: `${offer.label}: error state on the ${surface} — ${text}`, fullWidth };
  }
  return { problem: null, fullWidth };
}

test.describe("catalog modules are usable on a dashboard", () => {
  test.describe.configure({ mode: "serial" });

  let tokens: Awaited<ReturnType<typeof apiLogin>>;
  let projects: CatalogProject[] = [];

  test.beforeAll(async ({ request }) => {
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

  test("every catalog render adds and renders", async ({ page, request }) => {
    test.skip(
      projects.length === 0,
      "no ingested tool output on this stack — nothing for the catalog to match",
    );
    // Generous: the walk is one browser doing a full add cycle per render.
    test.setTimeout(60 * 60_000);

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

    for (const project of projects) {
      let offers = flattenOffers(project.modules);
      if (FIRST_RENDER_ONLY) offers = offers.filter((o) => o.renderIndex === 0);
      if (LIMIT > 0) offers = offers.slice(0, LIMIT);

      for (let start = 0; start < offers.length; start += BATCH) {
        const batch = offers.slice(start, start + BATCH);
        const title = `e2e catalog ${project.id.slice(-6)} ${start / BATCH + 1}`;
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
    console.log(`added ${added} catalog renders across ${projects.length} project(s)`);
    expect(added, "no catalog render was added at all").toBeGreaterThan(0);
    expect(problems, `\n${problems.join("\n")}\n`).toEqual([]);
  });
});
