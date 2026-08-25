/**
 * Catalog-picker helpers: talk to the compose endpoint, then drive the picker.
 *
 * The catalog specs are *data-driven*: nothing here hard-codes a tool, an
 * output or a project id. Whatever the running stack has ingested is what gets
 * exercised, so a new module lands in the suite the moment it matches a data
 * collection — which is exactly the guarantee the specs are meant to give.
 */
import { APIRequestContext, Page, expect } from "@playwright/test";
import { API_URL, API_PREFIX, TokenBundle } from "./auth";

export interface CatalogRender {
  id?: string;
  component: string;
  kind?: string;
  visu_type?: string;
  column?: string;
  aggregation?: string;
  aggregations?: string[];
  secondary_layout?: string;
  section?: string;
}

export interface CatalogMatch {
  output_id: string;
  name?: string;
  origin_tool?: string | null;
  description?: string;
  mode?: string | null;
  dc_id: string;
  dc_tag: string;
  dc_type?: string | null;
  wf_id: string;
  recipe?: string | null;
  fixture?: string | null;
  find?: { filename?: string; path_glob?: string } | null;
  source_url?: string | null;
  nf_core_url?: string | null;
  biotools_url?: string | null;
  renders_as: CatalogRender[];
}

export interface CatalogModule {
  tool_id: string;
  tool_name: string;
  matches: CatalogMatch[];
}

export interface CatalogProject {
  id: string;
  name: string;
  modules: CatalogModule[];
}

const auth = (t: TokenBundle) => ({ Authorization: `Bearer ${t.access_token}` });

/** Every (module, match, render) triple a project offers, flattened. */
export interface RenderOffer {
  toolId: string;
  toolName: string;
  match: CatalogMatch;
  render: CatalogRender;
  /** Position of `render` inside `match.renders_as` — the picker's tab index. */
  renderIndex: number;
  /** Stable, human-readable label used for test steps and failure messages. */
  label: string;
}

export function flattenOffers(modules: CatalogModule[]): RenderOffer[] {
  const offers: RenderOffer[] = [];
  for (const mod of modules) {
    for (const match of mod.matches) {
      match.renders_as.forEach((render, renderIndex) => {
        offers.push({
          toolId: mod.tool_id,
          toolName: mod.tool_name,
          match,
          render,
          renderIndex,
          label:
            `${mod.tool_id}/${match.output_id}[${renderIndex}] ` +
            `${render.component}${render.kind ? `:${render.kind}` : ""} ` +
            `on ${match.dc_tag}`,
        });
      });
    }
  }
  return offers;
}

export async function fetchCompose(
  request: APIRequestContext,
  tokens: TokenBundle,
  projectId: string,
): Promise<CatalogModule[]> {
  const res = await request.get(
    `${API_URL}${API_PREFIX}/catalog/project/${projectId}/compose`,
    { headers: auth(tokens) },
  );
  if (!res.ok()) return [];
  const body = (await res.json()) as { modules?: CatalogModule[] };
  return body.modules ?? [];
}

/**
 * Every project the user can see that the catalog recognises something in.
 * Returns [] on a stack with no ingested tool outputs — specs skip rather than
 * fail, so the suite stays green on an iris/penguins-only deployment.
 */
export async function findCatalogProjects(
  request: APIRequestContext,
  tokens: TokenBundle,
): Promise<CatalogProject[]> {
  const res = await request.get(`${API_URL}${API_PREFIX}/projects/get/all`, {
    headers: auth(tokens),
  });
  expect(res.ok(), `projects/get/all failed: ${res.status()}`).toBeTruthy();
  const projects = (await res.json()) as Array<Record<string, unknown>>;

  const found: CatalogProject[] = [];
  for (const p of projects) {
    const id = String(p.id ?? p._id ?? "");
    if (!id) continue;
    const modules = await fetchCompose(request, tokens, id);
    if (modules.length) found.push({ id, name: String(p.name ?? id), modules });
  }
  return found;
}

export async function createDashboard(
  request: APIRequestContext,
  tokens: TokenBundle,
  projectId: string,
  title: string,
): Promise<string> {
  const me = await request.get(`${API_URL}${API_PREFIX}/auth/me`, {
    headers: auth(tokens),
  });
  expect(me.ok(), `auth/me failed: ${me.status()}`).toBeTruthy();
  const user = (await me.json()) as { id?: string; _id?: string; email?: string; is_admin?: boolean };
  const userId = String(user.id ?? user._id);
  const dashboardId = objectId();

  const res = await request.post(
    `${API_URL}${API_PREFIX}/dashboards/save/${dashboardId}`,
    {
      headers: { ...auth(tokens), "Content-Type": "application/json" },
      data: {
        dashboard_id: dashboardId,
        version: 1,
        title,
        subtitle: "",
        icon: "mdi:view-dashboard",
        icon_color: "orange",
        icon_variant: "filled",
        workflow_system: "none",
        notes_content: "",
        permissions: {
          owners: [{ _id: userId, email: user.email, is_admin: !!user.is_admin }],
          editors: [],
          viewers: [],
        },
        is_public: false,
        last_saved_ts: "",
        project_id: projectId,
        is_main_tab: true,
        tab_order: 0,
      },
    },
  );
  expect(res.ok(), `dashboard create failed: ${res.status()} ${await res.text()}`).toBeTruthy();
  return dashboardId;
}

export async function deleteDashboard(
  request: APIRequestContext,
  tokens: TokenBundle,
  dashboardId: string,
): Promise<void> {
  // Never throws: it runs in a `finally`, and losing the real failure to a
  // cleanup error would be the worst possible trade. A failed cleanup is worth
  // one line on stderr — the throwaway dashboard is named `e2e catalog …`.
  try {
    const res = await request.delete(
      `${API_URL}${API_PREFIX}/dashboards/delete/${dashboardId}`,
      { headers: auth(tokens) },
    );
    if (!res.ok()) {
      // eslint-disable-next-line no-console
      console.warn(`cleanup: DELETE ${dashboardId} -> ${res.status()} ${await res.text()}`);
    }
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn(`cleanup: DELETE ${dashboardId} threw ${e}`);
  }
}

/** 24-hex Mongo ObjectId, same shape as the viewer's `generateObjectId`. */
export function objectId(): string {
  const ts = Math.floor(Date.now() / 1000)
    .toString(16)
    .padStart(8, "0");
  let rest = "";
  for (let i = 0; i < 16; i++) rest += Math.floor(Math.random() * 16).toString(16);
  return ts + rest;
}

/**
 * Add one catalog render to `dashboardId` through the real picker UI and return
 * the component id it was saved under.
 *
 * Deliberately the *whole* user path — choice screen → search → row → render
 * tab → Add — because the parts that silently drop config (the render→config
 * translation, the store, the save payload) all sit on it, and none of them are
 * exercised by hitting the compose endpoint.
 */
export async function addCatalogRender(
  page: Page,
  dashboardId: string,
  offer: RenderOffer,
): Promise<string> {
  const componentId = crypto.randomUUID();
  await page.goto(`/dashboard-edit/${dashboardId}/component/add/${componentId}`);

  await page.locator("[data-testid='component-source-catalog']").click();

  // Narrow to one row: output ids are unique per (output, collection) pair and
  // the search matches on them.
  const search = page.locator("[data-testid='catalog-search']");
  await expect(search).toBeVisible({ timeout: 20_000 });
  await search.fill(offer.match.output_id);

  const row = page
    .locator(
      `[data-testid='catalog-match'][data-output-id='${offer.match.output_id}']` +
        `[data-dc-tag='${offer.match.dc_tag}']`,
    )
    .first();
  await expect(row).toBeVisible({ timeout: 15_000 });

  // Click-then-verify, retried: the row list re-renders as the search filter
  // settles, and a click that lands on a node being replaced is swallowed —
  // the panel then quietly stays on whatever was selected before, which is the
  // first match in the first tool rather than an error anyone would notice.
  const panel = page.locator("[data-testid='catalog-preview-panel']");
  await expect(async () => {
    await row.click({ timeout: 5_000 });
    await expect(panel).toHaveAttribute("data-output-id", offer.match.output_id, {
      timeout: 3_000,
    });
  }).toPass({ timeout: 30_000 });

  // The switcher only exists when the output offers more than one render. Same
  // treatment: the tab strip wraps and reflows as the preview loads, so a click
  // can hit a node that is being re-laid-out.
  if (offer.match.renders_as.length > 1) {
    const tab = page.locator(
      `[data-testid='catalog-render-tab'][data-render-index='${offer.renderIndex}']`,
    );
    await expect(async () => {
      await tab.click({ timeout: 5_000 });
      await expect(panel).toHaveAttribute("data-selected-index", String(offer.renderIndex), {
        timeout: 3_000,
      });
    }).toPass({ timeout: 30_000 });
  }

  const add = page.locator("[data-testid='catalog-add']");
  await expect(add).toHaveAttribute("data-component", offer.render.component, {
    timeout: 10_000,
  });

  // Watch the save itself rather than only the navigation that follows it: a
  // rejected payload would otherwise surface as an opaque navigation timeout.
  const saved = page.waitForResponse(
    (r) => r.url().includes("/dashboards/save/") && r.request().method() === "POST",
    { timeout: 30_000 },
  );
  await add.click();
  const res = await saved;
  if (!res.ok()) {
    throw new Error(`save returned ${res.status()}: ${(await res.text()).slice(0, 300)}`);
  }

  // handleDirectAdd navigates only after the component is persisted; staying on
  // the builder means it fell back to the Design step.
  await page.waitForURL(`**/dashboard-edit/${dashboardId}`, { timeout: 30_000 });
  return componentId;
}

/** Component ids currently stored on a dashboard, straight from the API. */
export async function storedComponentIds(
  request: APIRequestContext,
  tokens: TokenBundle,
  dashboardId: string,
): Promise<Set<string>> {
  const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/get/${dashboardId}`, {
    headers: auth(tokens),
  });
  if (!res.ok()) return new Set();
  const dash = (await res.json()) as { stored_metadata?: Array<{ index?: string }> };
  return new Set((dash.stored_metadata ?? []).map((m) => String(m.index)));
}
