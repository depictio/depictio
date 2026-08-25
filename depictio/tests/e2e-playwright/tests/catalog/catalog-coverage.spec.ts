/**
 * The catalog's *coverage* contract: every output the catalog declares is
 * reachable from a project.
 *
 * Its two companion specs are data-driven off whatever the running stack has
 * ingested, which makes them green on a stack that ingests nothing and blind to
 * a module no reference project happens to produce. This one closes that gap by
 * checking one purpose-built project — `depictio/projects/init/catalog_conformance/`,
 * generated from the catalog itself — offers all of it.
 *
 * The manifest is the contract. It is written by the generator from
 * `load_catalog_entries()`, and `depictio/tests/catalog/test_conformance_project.py`
 * fails when it drifts from the catalog, so this spec can trust it as "what
 * should be offered" without re-parsing the catalog in TypeScript.
 *
 * The project is opt-in (`DEPICTIO_SEED_EXTRA_PROJECTS=catalog_conformance` on
 * the backend), so a stack without it skips. Set CATALOG_CONFORMANCE_REQUIRED=1
 * — as CI does — to turn that skip into a failure.
 */
import { readFileSync } from "fs";
import { join } from "path";
import { test, expect, apiLogin } from "../../fixtures/auth";
import { API_URL, API_PREFIX } from "../../fixtures/auth";
import { credentials } from "../../fixtures/credentials";
import { fetchCompose, flattenOffers, CatalogModule } from "../../fixtures/catalog";

interface Manifest {
  project_id: string;
  outputs: string[];
  lanes: Record<string, "recipe" | "raw">;
  coverage_exemptions: string[];
}

const MANIFEST_PATH = join(
  __dirname,
  "../../../../projects/init/catalog_conformance/manifest.json",
);
const REQUIRED = process.env.CATALOG_CONFORMANCE_REQUIRED === "1";

function readManifest(): Manifest | null {
  try {
    return JSON.parse(readFileSync(MANIFEST_PATH, "utf-8")) as Manifest;
  } catch {
    return null;
  }
}

test.describe("catalog coverage", () => {
  test.describe.configure({ mode: "serial" });

  let tokens: Awaited<ReturnType<typeof apiLogin>>;
  let manifest: Manifest | null = null;
  let modules: CatalogModule[] = [];
  let seeded = false;

  test.beforeAll(async ({ request }) => {
    manifest = readManifest();
    if (!manifest) return;
    tokens = await apiLogin(request, credentials.adminUser.email, credentials.adminUser.password);

    // The project id is derived from its name, so the manifest knows it without
    // anyone having to look it up on the stack.
    const res = await request.get(`${API_URL}${API_PREFIX}/projects/get/all`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });
    if (!res.ok()) return;
    const projects = (await res.json()) as Array<Record<string, unknown>>;
    seeded = projects.some((p) => String(p.id ?? p._id ?? "") === manifest!.project_id);
    if (seeded) modules = await fetchCompose(request, tokens, manifest.project_id);
  });

  test("the conformance project is seeded", async () => {
    expect(manifest, `no manifest at ${MANIFEST_PATH} — run the generator`).not.toBeNull();
    test.skip(
      !seeded && !REQUIRED,
      "catalog_conformance is not seeded on this stack (DEPICTIO_SEED_EXTRA_PROJECTS)",
    );
    expect(
      seeded,
      "CATALOG_CONFORMANCE_REQUIRED=1 but the project is absent — the backend " +
        "needs DEPICTIO_SEED_EXTRA_PROJECTS=catalog_conformance",
    ).toBeTruthy();
  });

  test("every catalog output is offered", async () => {
    test.skip(!seeded, "conformance project not seeded");
    const offered = new Set<string>();
    for (const mod of modules) for (const m of mod.matches) offered.add(m.output_id);

    const exempt = new Set(manifest!.coverage_exemptions);
    const missing = manifest!.outputs.filter((id) => !offered.has(id) && !exempt.has(id));

    expect(
      missing,
      `outputs the conformance project does not offer:\n  ${missing
        .map((id) => `${id} (${manifest!.lanes[id]} lane)`)
        .join("\n  ")}\n` +
        "A recipe-lane miss usually means the seed file was dropped at init " +
        "(check the API log for 'skipping recipe DC'); a raw-lane miss means " +
        "the scan found nothing at the staged path.",
    ).toEqual([]);
  });

  test("both matching lanes are exercised", async () => {
    test.skip(!seeded, "conformance project not seeded");
    // Compose recognises a collection three ways and the reference projects lean
    // almost entirely on the recipe branch. Losing the raw lane here would mean
    // `find.filename` / `find.path_glob` quietly stop being tested end to end.
    const byLane = { recipe: 0, raw: 0 };
    for (const mod of modules) {
      for (const m of mod.matches) {
        const lane = manifest!.lanes[m.output_id];
        if (lane) byLane[lane] += 1;
      }
    }
    expect(byLane.recipe, "no recipe-matched offer").toBeGreaterThan(0);
    expect(byLane.raw, "no path-matched offer — the find patterns are untested").toBeGreaterThan(0);
  });

  test("every offer can be bound to a component", async () => {
    test.skip(!seeded, "conformance project not seeded");
    const problems: string[] = [];
    for (const offer of flattenOffers(modules)) {
      const where = `${offer.toolId}/${offer.match.output_id}`;
      if (!offer.match.dc_id) problems.push(`${where}: no dc_id`);
      if (!offer.match.wf_id) problems.push(`${where}: no wf_id`);
      if (!offer.render.component) problems.push(`${where}: render without a component`);
    }
    expect(problems, problems.join("\n")).toEqual([]);
  });
});
