// Shared by generate-icon-subset.mjs (bundles icons) and check-icons.mjs
// (fails on icons that would not bundle). One definition of which collections
// are installed, how a data file names an icon and how a name resolves, so the
// guard can never disagree with the generator.

import { readFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { getIcons } from '@iconify/utils';

// Collections installed as devDependencies. A prefix outside this list is
// reported rather than bundled — add the matching @iconify-json package.
export const COLLECTIONS = [
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

// Shipped dashboard data. Seeded dashboards name their icons in YAML and in the
// exported `.db_seeds` JSON, so no TS source mentions them and they used to
// resolve against the Iconify API — i.e. render as an empty box in every built
// bundle, and only there, since `vite dev` sends no CSP. Scanning the data
// itself is what makes "add a tile, pick an icon, ship it" work without also
// remembering to mirror the id into a TS list.
export const SCAN_DATA_EXTENSIONS = new Set(['.yaml', '.yml', '.json']);

// `<slot>: <icon>` in YAML or JSON, quoted or not. A separate matcher from the
// source-code literal because YAML writes `icon: mdi:table` bare, and matching
// every bare `a:b` in arbitrary data would sweep up tags, paths and timestamps.
export const DATA_ICON_LITERAL =
  /["']?(?:icon|tab_icon|icon_name)["']?\s*:\s*["']?([a-z][a-z0-9]*(?:-[a-z0-9]+)*:[a-z][a-z0-9]*(?:-[a-z0-9]+)*)["']?/g;

export async function* walk(dir, extensions) {
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
      yield* walk(full, extensions);
    } else if (extensions.has(entry.name.slice(entry.name.lastIndexOf('.')))) {
      yield full;
    }
  }
}

export async function loadCollection(prefix) {
  const path = new URL(`../node_modules/@iconify-json/${prefix}/icons.json`, import.meta.url);
  return JSON.parse(await readFile(path, 'utf8'));
}

// Names (without prefix) of `names` that `prefix`'s collection cannot resolve.
// Same test as the generator: getIcons drops what it cannot find, aliases included.
export async function unresolvedNames(prefix, names) {
  const collection = await loadCollection(prefix);
  const subset = getIcons(collection, names);
  const resolved = new Set([
    ...Object.keys(subset?.icons ?? {}),
    ...Object.keys(subset?.aliases ?? {}),
  ]);
  return names.filter((name) => !resolved.has(name));
}
