/**
 * The catalog picker's *registration* contract, checked against whatever the
 * running stack has ingested.
 *
 * This is the half that answers "is every module correctly registered": the
 * compose endpoint recognises the collection, the match carries everything the
 * picker needs to draw a row and a detail popover, and the output's preview
 * payload actually builds. The companion spec
 * (`catalog-modules-on-dashboard.spec.ts`) answers the other half — "is it
 * usable on a dashboard".
 */
import { test, expect } from "../../fixtures/auth";
import { apiLogin, API_URL, API_PREFIX } from "../../fixtures/auth";
import { credentials } from "../../fixtures/credentials";
import {
  findCatalogProjects,
  flattenOffers,
  CatalogProject,
} from "../../fixtures/catalog";

const COMPONENT_TYPES = new Set([
  "advanced_viz",
  "card",
  "figure",
  "image",
  "interactive",
  "jbrowse",
  "map",
  "multiqc",
  "table",
  "text",
]);

test.describe("catalog registration", () => {
  test.describe.configure({ mode: "serial" });

  let tokens: Awaited<ReturnType<typeof apiLogin>>;
  let projects: CatalogProject[] = [];

  test.beforeAll(async ({ request }) => {
    tokens = await apiLogin(request, credentials.adminUser.email, credentials.adminUser.password);
    projects = await findCatalogProjects(request, tokens);
  });

  test("at least one project has catalog matches", async () => {
    test.skip(
      projects.length === 0,
      "no ingested tool output on this stack — nothing for the catalog to match",
    );
    for (const p of projects) {
      // eslint-disable-next-line no-console
      console.log(
        `${p.name} (${p.id}): ${p.modules.length} tools, ` +
          `${flattenOffers(p.modules).length} renders`,
      );
    }
    expect(projects.length).toBeGreaterThan(0);
  });

  test("every match carries what the picker draws it from", async () => {
    test.skip(projects.length === 0, "no catalog matches on this stack");
    const problems: string[] = [];

    for (const project of projects) {
      for (const mod of project.modules) {
        expect(mod.tool_id, `${project.name}: module without tool_id`).toBeTruthy();
        expect(mod.tool_name, `${project.name}/${mod.tool_id}: no tool_name`).toBeTruthy();
        expect(mod.matches.length, `${project.name}/${mod.tool_id}: no matches`).toBeGreaterThan(0);

        for (const m of mod.matches) {
          const where = `${project.name}/${mod.tool_id}/${m.output_id}`;
          if (!m.name) problems.push(`${where}: no display name`);
          if (!m.dc_id) problems.push(`${where}: no dc_id — cannot bind a component`);
          if (!m.wf_id) problems.push(`${where}: no wf_id — cannot bind a component`);
          if (!m.dc_tag) problems.push(`${where}: no dc_tag — the source chip would be blank`);
          if (!m.renders_as?.length) problems.push(`${where}: no renders_as — nothing to add`);
          for (const r of m.renders_as ?? []) {
            if (!COMPONENT_TYPES.has(r.component)) {
              problems.push(`${where}: unknown component type '${r.component}'`);
            }
            if (r.component === "advanced_viz" && !r.kind) {
              problems.push(`${where}: advanced_viz render without a kind`);
            }
            if (r.component === "card" && !(r.column && r.aggregation)) {
              problems.push(`${where}: card render without column+aggregation`);
            }
          }
        }
      }
    }
    expect(problems, problems.join("\n")).toEqual([]);
  });

  test("every matched output builds a preview payload", async ({ request }) => {
    test.skip(projects.length === 0, "no catalog matches on this stack");
    test.setTimeout(180_000);

    // One output can match several collections (a raw scan and a recipe-derived
    // reshape); its payload is fixture-based and identical, so build it once.
    const outputs = new Set<string>();
    for (const p of projects) {
      for (const mod of p.modules) for (const m of mod.matches) outputs.add(m.output_id);
    }

    const problems: string[] = [];
    for (const outputId of [...outputs].sort()) {
      const res = await request.get(
        `${API_URL}${API_PREFIX}/catalog/output/${outputId}/preview-payload`,
        { headers: { Authorization: `Bearer ${tokens.access_token}` } },
      );
      if (!res.ok()) {
        problems.push(`${outputId}: preview-payload ${res.status()} ${await res.text()}`);
        continue;
      }
      const payload = (await res.json()) as { renders?: Array<Record<string, unknown>> };
      if (!payload.renders?.length) problems.push(`${outputId}: payload has no renders`);
      for (const r of payload.renders ?? []) {
        if (r._error) problems.push(`${outputId}[${r.index}]: ${String(r._error)}`);
      }
    }
    expect(problems, problems.join("\n")).toEqual([]);
  });
});
