/**
 * Parity harness for the client-side validation: each case below is a draft the
 * Studio must flag (with the given code) AND that `depictio dev catalog
 * validate` must reject. Writes one tool folder per case under <outDir> and a
 * `cases.json` index; CI runs the CLI on every folder and expects a failure.
 *
 * A case the Studio flags but the CLI accepts means the client is stricter
 * than CI for no reason; a case the CLI rejects but the Studio misses is the
 * gap this file exists to close. Either way the run fails.
 *
 * Usage: tsx scripts/genNegatives.ts <outDir>
 */
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseFixture } from '../src/catalog/parseFixture';
import { generateEntry } from '../src/catalog/yamlGen';
import { validateDraft, type DraftToValidate } from '../src/catalog/diagnostics';
import { kindsMapFrom } from '../src/catalog/kinds';
import type { OutputMeta, RenderSpec, ToolMeta } from '../src/types';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, '..');
const outDir = resolve(process.argv[2] ?? join(pkgRoot, '.negatives-out'));
const kinds = kindsMapFrom(JSON.parse(readFileSync(join(pkgRoot, 'public', 'kinds.json'), 'utf8')).kinds);

const CSV = 'gene,log2fc,pvalue,sample,day\nA,2.1,0.01,S1,2024-01-02\nB,-1.2,0.2,S2,2024-01-03\n';
const volcano: RenderSpec = {
  uid: 'v',
  component: 'advanced_viz',
  kind: 'volcano',
  roles: { feature_id: 'gene', effect_size: 'log2fc', significance: 'pvalue' },
};

interface Case {
  name: string;
  expect: string;
  tool?: Partial<ToolMeta>;
  output?: Partial<OutputMeta>;
  csv?: string;
  renders?: RenderSpec[];
}

const CASES: Case[] = [
  { name: 'nohomepage', expect: 'identity.homepage_missing', tool: { homepage: undefined } },
  { name: 'nodescription', expect: 'identity.description_missing', tool: { description: undefined } },
  { name: 'badbiotools', expect: 'identity.biotools_url', tool: { biotools_url: 'https://example.org/t' } },
  { name: 'badnfcore', expect: 'identity.nf_core_url', tool: { nf_core_url: 'https://github.com/someone/modules' } },
  { name: 'badversion', expect: 'identity.version', tool: { version: 'v2' } },
  { name: 'headeronly', expect: 'fixture.no_data', csv: 'gene,log2fc,pvalue,sample,day\n' },
  {
    name: 'roledtype',
    expect: 'render.role_dtype',
    renders: [{ ...volcano, roles: { ...volcano.roles, effect_size: 'sample' } as Record<string, string> }],
  },
  {
    // An ISO date is a String to polars; the Studio used to call it Datetime.
    name: 'datesarestrings',
    expect: 'render.grounding',
    renders: [{ uid: 'c', component: 'card', column: 'day', aggregation: 'average' }],
  },
  {
    name: 'unboundcolumn',
    expect: 'render.grounding',
    renders: [{ uid: 'c', component: 'card', column: 'nope', aggregation: 'average' }],
  },
  {
    // The fixture must be a sample of the recipe's output (CLI loads the recipe).
    name: 'recipemismatch',
    expect: 'recipe.fixture_mismatch',
    output: {
      recipe: {
        code:
          'import polars as pl\nfrom depictio.models.models.transforms import RecipeSource\n' +
          'SOURCES = [RecipeSource(ref="raw", dc_ref="negrecipemismatch_results_raw")]\n' +
          'OUTPUT_SCHEMA = {\n    "depth": pl.Float64,\n}\ndef transform(sources):\n    return sources["raw"]\n',
      },
    },
  },
  {
    name: 'recipenosources',
    expect: 'recipe.empty_sources',
    output: {
      recipe: {
        code: 'import polars as pl\nSOURCES = []\nOUTPUT_SCHEMA = {\n    "gene": pl.Utf8,\n}\ndef transform(sources):\n    return sources["raw"]\n',
      },
    },
  },
  {
    name: 'idcollision',
    expect: 'render.id_collides_output',
    renders: [{ ...volcano, id: '__OUTPUT_ID__' }],
  },
];

rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });
const index: Array<{ dir: string; expect: string; studioCodes: string[] }> = [];
let missed = 0;
for (const c of CASES) {
  const toolId = `neg${c.name}`; // the folder name must equal the id
  const tool: ToolMeta = {
    id: toolId,
    name: `Negative ${c.name}`,
    source: 'nf-core',
    description: 'Negative parity case.',
    homepage: 'https://example.org/neg',
    ...c.tool,
  };
  const output: OutputMeta = { slug: 'results', path_glob: '**/neg/*.csv', ...c.output };
  const fixture = parseFixture('results.csv', c.csv ?? CSV);
  const renders = (c.renders ?? [volcano]).map((r) =>
    r.id === '__OUTPUT_ID__' ? { ...r, id: `${toolId}_${output.slug}` } : r,
  );
  const draft: DraftToValidate = { tool, output, fixture, renders, kinds };
  const studioCodes = validateDraft(draft)
    .filter((d) => d.severity === 'error')
    .map((d) => d.code);
  if (!studioCodes.includes(c.expect)) {
    console.error(`[genNegatives] Studio MISSED ${c.name}: expected ${c.expect}, got ${studioCodes.join(', ') || 'none'}`);
    missed++;
  }
  const entry = generateEntry({ tool, output, fixtureFileName: fixture.fileName, fixtureContent: fixture.raw, renders });
  const dir = join(outDir, toolId);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'module.yaml'), entry.moduleYaml);
  writeFileSync(join(dir, entry.outputYamlName), entry.outputYaml);
  writeFileSync(join(dir, entry.fixtureName), entry.fixtureContent);
  if (entry.recipeFile) writeFileSync(join(dir, entry.recipeFile.name), entry.recipeFile.content);
  index.push({ dir, expect: c.expect, studioCodes });
}
writeFileSync(join(outDir, 'cases.json'), JSON.stringify(index, null, 2) + '\n');
console.log(`[genNegatives] wrote ${CASES.length} cases to ${outDir}`);
if (missed) process.exit(1);
