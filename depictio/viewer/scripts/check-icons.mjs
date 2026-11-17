// Fail when a shipped dashboard names an icon the viewer bundle cannot render.
//
// generate-icon-subset.mjs bundles the icons named in depictio/projects/**
// (YAML and .db_seeds JSON: `icon`, `tab_icon`, `icon_name`) and only *warns*
// about the ones it cannot find, so a typo ships as an empty box in every built
// bundle (the strict CSP blocks the Iconify API fallback). This runs the same
// scan and resolution and exits 1, listing file:line and value.
//
//   pnpm run check:icons

import { readFile } from 'node:fs/promises';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  COLLECTIONS,
  DATA_ICON_LITERAL,
  SCAN_DATA_EXTENSIONS,
  unresolvedNames,
  walk,
} from './icon-scan.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '../../..');
const DATA_DIRS = [join(REPO, 'depictio/projects')];

// value -> [{ file, line }]
const used = new Map();
for (const dir of DATA_DIRS) {
  for await (const file of walk(dir, SCAN_DATA_EXTENSIONS)) {
    const source = await readFile(file, 'utf8');
    for (const match of source.matchAll(DATA_ICON_LITERAL)) {
      const value = match[1];
      const line = source.slice(0, match.index).split('\n').length;
      if (!used.has(value)) used.set(value, []);
      used.get(value).push({ file: relative(REPO, file), line });
    }
  }
}

const byPrefix = new Map();
for (const value of used.keys()) {
  const prefix = value.slice(0, value.indexOf(':'));
  if (!byPrefix.has(prefix)) byPrefix.set(prefix, []);
  byPrefix.get(prefix).push(value.slice(value.indexOf(':') + 1));
}

const problems = []; // { value, reason }
for (const [prefix, names] of byPrefix) {
  if (!COLLECTIONS.includes(prefix)) {
    for (const name of names) problems.push({ value: `${prefix}:${name}`, reason: 'no collection installed' });
    continue;
  }
  for (const name of await unresolvedNames(prefix, names)) {
    problems.push({ value: `${prefix}:${name}`, reason: 'not in collection' });
  }
}

const total = [...used.values()].reduce((n, sites) => n + sites.length, 0);
if (problems.length) {
  console.error(`[check:icons] ${problems.length} unresolved icon(s) in depictio/projects (render blank in a built bundle):`);
  for (const { value, reason } of problems.sort((a, b) => a.value.localeCompare(b.value))) {
    console.error(`  ${value}  (${reason})`);
    for (const { file, line } of used.get(value)) console.error(`    ${file}:${line}`);
  }
  console.error(
    '  Fix the name, or install the @iconify-json collection and add its prefix to COLLECTIONS in scripts/icon-scan.mjs.',
  );
  process.exit(1);
}
console.log(`[check:icons] ok: ${used.size} distinct icons (${total} uses) all resolve`);
