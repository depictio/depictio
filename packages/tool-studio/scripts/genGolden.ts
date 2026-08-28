/**
 * Generate the "golden" catalog entry from a committed fixture using the SAME
 * yamlGen the app ships. Writes module.yaml + <output>.yaml + fixture into the
 * target dir so CI can run `depictio dev catalog validate --path <dir>` on it —
 * the round-trip test that proves the app's output is loader/schema valid.
 *
 * Usage: tsx scripts/genGolden.ts <outDir>
 */
import { mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseFixture } from '../src/catalog/parseFixture';
import { generateEntry } from '../src/catalog/yamlGen';
import type { RenderSpec } from '../src/types';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, '..');
const outDir = process.argv[2] ?? resolve(pkgRoot, '.golden-out');
// `catalog validate` requires a tool's id to equal its folder name — the id is
// the address the viewer, the docs and the conformance project all build paths
// from. Derive it so the round-trip obeys the same rule a real entry does.
const toolId = basename(outDir);

const fixtureName = 'golden.csv';
const raw = readFileSync(join(pkgRoot, 'e2e', 'golden', fixtureName), 'utf8');
const fixture = parseFixture(fixtureName, raw);

// Keep this list adversarial, not representative: every entry exists because
// emitting it naively produced YAML the catalog model rejects.
const renders: RenderSpec[] = [
  // Numeric + boolean plotly params: they must reach the YAML *quoted*, since
  // `dict_kwargs` is Dict[str, str] and Pydantic v2 won't coerce int/bool → str.
  {
    uid: 'r1',
    component: 'figure',
    visu_type: 'histogram',
    dict_kwargs: { x: 'log2fc', color: 'sample', nbinsx: '30', log_y: 'true', title: 'Golden histogram' },
  },
  { uid: 'r2', component: 'card', column: 'coverage', aggregation: 'average' },
  // One card per layout family that requires a companion field, so a missing
  // mapping in fromBuilderStore/yamlGen fails the round-trip instead of a PR.
  {
    uid: 'r2b',
    component: 'card',
    column: 'coverage',
    aggregation: 'average',
    secondary_layout: 'threshold',
    threshold_value: 100,
    threshold_direction: 'min',
  },
  {
    uid: 'r2c',
    component: 'card',
    column: 'coverage',
    aggregation: 'average',
    secondary_layout: 'donut',
    breakdown_col: 'sample',
  },
  {
    uid: 'r2d',
    component: 'card',
    column: 'coverage',
    aggregation: 'average',
    secondary_layout: 'trend',
    trend_col: 'log2fc',
  },
  {
    uid: 'r2e',
    component: 'card',
    column: 'coverage',
    aggregation: 'average',
    secondary_layout: 'gauge',
    coverage_max: 200,
  },
  { uid: 'r3', component: 'table' },
  // A configured table and a filter control: both were inexpressible until the
  // Render model grew their fields, so both belong in the adversarial set.
  {
    uid: 'r3b',
    component: 'table',
    columns: ['gene', 'log2fc', 'pvalue'],
    page_size: 25,
    row_selection_enabled: true,
    row_selection_column: 'gene',
  },
  { uid: 'r4', component: 'interactive', interactive_type: 'MultiSelect', column_name: 'sample' },
  { uid: 'r4b', component: 'interactive', interactive_type: 'RangeSlider', column_name: 'coverage' },
  {
    uid: 'r5',
    component: 'advanced_viz',
    kind: 'volcano',
    roles: { feature_id: 'gene', effect_size: 'log2fc', significance: 'pvalue' },
  },
];

const entry = generateEntry({
  tool: { id: toolId, name: 'Golden Tool', source: 'nf-core' },
  output: { slug: 'results', path_glob: '**/golden/*.csv', description: 'Golden round-trip fixture.' },
  fixtureFileName: fixture.fileName,
  fixtureContent: fixture.raw,
  renders,
});

rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, 'module.yaml'), entry.moduleYaml);
writeFileSync(join(outDir, entry.outputYamlName), entry.outputYaml);
writeFileSync(join(outDir, entry.fixtureName), entry.fixtureContent);

console.log(`[genGolden] wrote entry to ${outDir}`);
console.log('--- module.yaml ---\n' + entry.moduleYaml);
console.log('--- ' + entry.outputYamlName + ' ---\n' + entry.outputYaml);
