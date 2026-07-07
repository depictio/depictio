/**
 * Generate the "golden" catalog entry from a committed fixture using the SAME
 * yamlGen the app ships. Writes module.yaml + <output>.yaml + fixture into the
 * target dir so CI can run `depictio dev catalog validate --path <dir>` on it —
 * the round-trip test that proves the app's output is loader/schema valid.
 *
 * Usage: tsx scripts/genGolden.ts <outDir>
 */
import { mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseFixture } from '../src/catalog/parseFixture';
import { generateEntry } from '../src/catalog/yamlGen';
import type { RenderSpec } from '../src/types';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, '..');
const outDir = process.argv[2] ?? resolve(pkgRoot, '.golden-out');

const fixtureName = 'golden.csv';
const raw = readFileSync(join(pkgRoot, 'e2e', 'golden', fixtureName), 'utf8');
const fixture = parseFixture(fixtureName, raw);

const renders: RenderSpec[] = [
  { uid: 'r1', component: 'figure', visu_type: 'histogram', dict_kwargs: { x: 'log2fc', color: 'sample' } },
  { uid: 'r2', component: 'card', column: 'coverage', aggregation: 'average' },
  { uid: 'r3', component: 'table' },
  {
    uid: 'r4',
    component: 'advanced_viz',
    kind: 'volcano',
    roles: { feature_id: 'gene', effect_size: 'log2fc', significance: 'pvalue' },
  },
];

const entry = generateEntry({
  tool: { id: 'golden_tool', name: 'Golden Tool' },
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
