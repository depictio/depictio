// Generate the bundled Iconify icon subset.
//
// `@iconify/react` resolves unknown icon names by fetching them from the public
// Iconify API at runtime. The app ships a strict CSP (`connect-src 'self'`, see
// depictio/api/main.py and docker-images/nginx.conf.template), so those fetches
// are blocked and every icon renders empty. Only the Vite dev server escapes it,
// because it sends no CSP at all.
//
// So the icons have to be in the bundle. This scans the source for icon names,
// pulls just those out of the installed @iconify-json collections, and writes
// them to src/generated/iconSubset.ts, which src/icons.ts registers at boot.
//
// Runs from `predev` / `prebuild`, so adding an <Icon icon="..."/> and rebuilding
// is enough — no manual step. Names that cannot be resolved are reported loudly
// rather than silently shipping a blank icon.

import { readFile, writeFile, mkdir, readdir } from 'node:fs/promises';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { getIcons } from '@iconify/utils';

const HERE = dirname(fileURLToPath(import.meta.url));
const VIEWER = join(HERE, '..');
const REPO = join(VIEWER, '../..');

// Scanned trees. The workspace packages are aliased to their src/ by
// vite.config.ts and share the deduped @iconify/react instance, so icons they
// reference are resolved by the same registration.
const SCAN_DIRS = [
  join(VIEWER, 'src'),
  join(REPO, 'packages/depictio-components/src'),
  join(REPO, 'packages/depictio-react-core/src'),
];

const SCAN_EXTENSIONS = new Set(['.ts', '.tsx', '.js', '.jsx']);
const OUT_FILE = join(VIEWER, 'src/generated/iconSubset.ts');

// Collections installed as devDependencies. A prefix outside this list is
// reported rather than bundled — add the matching @iconify-json package.
const COLLECTIONS = [
  'mdi',
  'tabler',
  'material-symbols',
  'ph',
  'bx',
  'bi',
  'simple-icons',
  'octicon',
  'mingcute',
  'ic',
  'carbon',
  'formkit',
];

// `prefix:name`, both lowercase kebab. Matches icon literals wherever they are
// written: a JSX prop, a lookup table, a ternary. Deliberately broad — anything
// that does not resolve against a real collection is discarded below, which is
// what keeps unrelated literals like `group:foo` out of the output.
const ICON_LITERAL = /['"`]([a-z][a-z0-9]*(?:-[a-z0-9]+)*:[a-z][a-z0-9]*(?:-[a-z0-9]+)*)['"`]/g;

async function* walk(dir) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return; // tree absent (e.g. a package not checked out) — nothing to scan
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === 'generated') continue;
      yield* walk(full);
    } else if (SCAN_EXTENSIONS.has(entry.name.slice(entry.name.lastIndexOf('.')))) {
      yield full;
    }
  }
}

// True when the literal sits directly behind an `icon` prop or property, as in
// `icon="mdi:x"`, `icon={'mdi:x'}` or `icon: 'mdi:x'`. Used only to decide
// whether an unrecognised prefix is worth warning about: `depictio:recents-changed`
// is a DOM event name, `formkit:number` is a real icon, and both otherwise look
// alike to the literal regex.
const ICON_CONTEXT = /icon\s*[:=]\s*\{?\s*$/i;

async function collectUsedNames() {
  // name -> { files: Set<string>, iconContext: boolean } for actionable output
  const found = new Map();
  for (const dir of SCAN_DIRS) {
    for await (const file of walk(dir)) {
      const source = await readFile(file, 'utf8');
      for (const match of source.matchAll(ICON_LITERAL)) {
        const name = match[1];
        if (!found.has(name)) found.set(name, { files: new Set(), iconContext: false });
        const entry = found.get(name);
        entry.files.add(relative(REPO, file));
        if (ICON_CONTEXT.test(source.slice(Math.max(0, match.index - 16), match.index))) {
          entry.iconContext = true;
        }
      }
    }
  }
  return found;
}

async function loadCollection(prefix) {
  const path = new URL(`../node_modules/@iconify-json/${prefix}/icons.json`, import.meta.url);
  return JSON.parse(await readFile(path, 'utf8'));
}

const used = await collectUsedNames();

const byPrefix = new Map();
for (const full of used.keys()) {
  const prefix = full.slice(0, full.indexOf(':'));
  if (!byPrefix.has(prefix)) byPrefix.set(prefix, []);
  byPrefix.get(prefix).push(full.slice(full.indexOf(':') + 1));
}

const subsets = [];
const unresolved = [];
let iconCount = 0;

for (const prefix of COLLECTIONS) {
  const names = byPrefix.get(prefix);
  if (!names?.length) continue;

  const collection = await loadCollection(prefix);
  const subset = getIcons(collection, names);

  // getIcons drops names it cannot find. Diff to surface typos, icons that moved
  // between collections, and aliases needing a newer @iconify-json release.
  const resolved = new Set([...Object.keys(subset?.icons ?? {}), ...Object.keys(subset?.aliases ?? {})]);
  for (const name of names) {
    if (!resolved.has(name)) unresolved.push(`${prefix}:${name}`);
  }

  if (subset) {
    subsets.push(subset);
    iconCount += resolved.size;
  }
}

// Prefixes used in source with no installed collection. Distinguished from
// typos because the fix is different: install @iconify-json/<prefix>. Only
// literals in an `icon` position count, so DOM event names sharing the
// `prefix:name` shape are not reported.
const missingCollections = [...byPrefix.keys()]
  .filter((prefix) => !COLLECTIONS.includes(prefix))
  .filter((prefix) =>
    byPrefix.get(prefix).some((name) => used.get(`${prefix}:${name}`)?.iconContext),
  );

const banner = `// GENERATED by scripts/generate-icon-subset.mjs — do not edit.
// Regenerate with \`pnpm build\` (or \`pnpm dev\`), which runs the generator first.
//
// Icon data bundled so <Icon/> never reaches the public Iconify API, which the
// app's \`connect-src 'self'\` CSP blocks. See the generator for the full story.
`;

await mkdir(dirname(OUT_FILE), { recursive: true });
await writeFile(
  OUT_FILE,
  `${banner}
import type { addCollection } from '@iconify/react';

type IconCollection = Parameters<typeof addCollection>[0];

export const iconCollections: IconCollection[] = ${JSON.stringify(subsets, null, 2)};
`,
  'utf8',
);

const summary = subsets.map((s) => `${s.prefix}(${Object.keys(s.icons ?? {}).length})`).join(' ');
console.log(`[icons] bundled ${iconCount} icons from ${subsets.length} collections: ${summary}`);

if (unresolved.length) {
  console.warn(
    `[icons] WARNING: ${unresolved.length} icon name(s) not found in their collection ` +
      `— these render blank at runtime:\n` +
      unresolved.map((n) => `  ${n}  (${[...used.get(n).files].join(', ')})`).join('\n'),
  );
}
if (missingCollections.length) {
  console.warn(
    `[icons] WARNING: no collection installed for prefix(es): ${missingCollections.join(', ')}\n` +
      `  Install with: pnpm add -D ${missingCollections.map((p) => `@iconify-json/${p}`).join(' ')}\n` +
      `  then add the prefix to COLLECTIONS in scripts/generate-icon-subset.mjs`,
  );
}
