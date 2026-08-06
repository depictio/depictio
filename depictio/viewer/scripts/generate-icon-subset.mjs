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
// Source is not the only place icon names are authored. Dashboards carry their
// own ids in data — `tab_icon` on a tab, `icon` on a dashboard, `icon_name` on a
// card — written in the project YAML and baked into the `.db_seeds/*.json` that
// fresh deployments load. Those never appear in a .ts file, so a source-only
// scan shipped them blank: every viralrecon tab icon, most of the advanced-viz
// showcase. The corpus under depictio/projects/ is therefore scanned too.
//
// Every `pnpm dev` / `pnpm build` / `pnpm build:static` runs this first (see
// package.json scripts), so adding an <Icon icon="..."/> or a `tab_icon:` to a
// dashboard and rebuilding is enough — no manual step. Names that cannot be
// resolved are reported loudly rather than silently shipping a blank icon.

import { readFile, writeFile, mkdir, readdir, stat } from 'node:fs/promises';
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

// Dashboard corpus: project YAML plus the `.db_seeds/*.json` generated from it
// (fresh deployments load the JSON, not the YAML — see CLAUDE.md), and any
// template/reference dashboard shipped alongside. Scanned for authored icon ids
// in data fields; see CORPUS_ICON_FIELD.
const CORPUS_DIRS = [join(REPO, 'depictio/projects')];

const CORPUS_EXTENSIONS = new Set(['.yaml', '.yml', '.json']);

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

// Icon *fields* in the dashboard corpus, matched textually so the same pattern
// covers YAML (`tab_icon: mdi:virus`) and JSON (`"tab_icon": "mdi:virus"`).
// The corpus is not parsed: template YAML carries `{PLACEHOLDER}` substitutions
// that a strict loader chokes on, and a superset of candidate ids is all this
// needs — anything that isn't a real icon is dropped when it fails to resolve.
//
// The key must be `icon`, `icon_name`, or end in `_icon` / `_icon_name`
// (`tab_icon`, `tab_icon_name`). Anchoring on `_` is what keeps `amplicon:`
// out — it ends in "icon" but is a data-collection mode, not an icon field.
// `icon_color` / `icon_variant` are excluded by the same anchoring.
//
// Values that are image paths (`/assets/images/workflows/nf-core.png`) do not
// match the `prefix:name` shape and are skipped; the viewer renders those as
// <img> rather than through Iconify.
const CORPUS_ICON_FIELD =
  /["']?(?<![a-z0-9])((?:[a-z0-9]+_)*icon(?:_name)?)["']?\s*:\s*["']?([a-z][a-z0-9]*(?:-[a-z0-9]+)*:[a-z][a-z0-9]*(?:-[a-z0-9]+)*)["']?/g;

async function* walk(dir, extensions = SCAN_EXTENSIONS) {
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

// True when the literal sits directly behind an `icon` prop or property, as in
// `icon="mdi:x"`, `icon={'mdi:x'}` or `icon: 'mdi:x'`. Used only to decide
// whether an unrecognised prefix is worth warning about: `depictio:recents-changed`
// is a DOM event name, `formkit:number` is a real icon, and both otherwise look
// alike to the literal regex.
const ICON_CONTEXT = /icon\s*[:=]\s*\{?\s*$/i;

// name -> { files: Set<string>, iconContext: boolean, fromSource: boolean }
// for actionable output. `fromSource` separates "a component asks for this" from
// "only a dashboard document asks for this", which is the reporting the corpus
// scan exists to provide.
function record(found, name, file, { iconContext, fromSource }) {
  if (!found.has(name)) {
    found.set(name, { files: new Set(), iconContext: false, fromSource: false });
  }
  const entry = found.get(name);
  entry.files.add(relative(REPO, file));
  if (iconContext) entry.iconContext = true;
  if (fromSource) entry.fromSource = true;
  return entry;
}

const absentCorpusDirs = [];

async function collectUsedNames() {
  const found = new Map();
  for (const dir of SCAN_DIRS) {
    for await (const file of walk(dir)) {
      const source = await readFile(file, 'utf8');
      for (const match of source.matchAll(ICON_LITERAL)) {
        const before = source.slice(Math.max(0, match.index - 16), match.index);
        record(found, match[1], file, {
          iconContext: ICON_CONTEXT.test(before),
          fromSource: true,
        });
      }
    }
  }
  // Corpus ids always sit in a declared icon field, so they count as icon
  // context: an unknown prefix here is a real "install the collection" signal,
  // not a false positive from a string that merely looks like `prefix:name`.
  for (const dir of CORPUS_DIRS) {
    // A build context that omits the corpus (the viewer Docker image copies
    // only depictio/viewer + packages) would otherwise scan nothing and ship
    // the dashboards' icons blank again — the exact failure this scan exists
    // to prevent, and invisible because walk() treats an absent tree as empty.
    if (!(await stat(dir).catch(() => null))?.isDirectory()) {
      absentCorpusDirs.push(relative(REPO, dir));
      continue;
    }
    for await (const file of walk(dir, CORPUS_EXTENSIONS)) {
      const source = await readFile(file, 'utf8');
      for (const match of source.matchAll(CORPUS_ICON_FIELD)) {
        record(found, match[2], file, { iconContext: true, fromSource: false });
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
let corpusOnlyCount = 0;

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
    else if (!used.get(`${prefix}:${name}`).fromSource) corpusOnlyCount += 1;
  }

  if (subset) {
    subsets.push(subset);
    iconCount += resolved.size;
  }
}

// Prefixes used in source or the dashboard corpus with no installed collection.
// Distinguished from typos because the fix is different: install
// @iconify-json/<prefix>. Only literals in an `icon` position count, so DOM
// event names sharing the `prefix:name` shape are not reported.
const missingCollections = [...byPrefix.keys()]
  .filter((prefix) => !COLLECTIONS.includes(prefix))
  .filter((prefix) =>
    byPrefix.get(prefix).some((name) => used.get(`${prefix}:${name}`)?.iconContext),
  );

const banner = `// GENERATED by scripts/generate-icon-subset.mjs — do not edit.
// Regenerate with \`pnpm build\` (or \`pnpm dev\`), which runs the generator first.
//
// Icon data bundled so <Icon/> never reaches the public Iconify API, which the
// app's \`connect-src 'self'\` CSP blocks — and which a static bundle opened
// from file:// cannot reach at all. Covers ids written in source *and* ids
// authored in the dashboard corpus (\`tab_icon\`, \`icon\`, \`icon_name\` in
// depictio/projects/**). See the generator for the full story.
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
console.log(
  `[icons] bundled ${iconCount} icons from ${subsets.length} collections: ${summary}` +
    ` (${corpusOnlyCount} authored only in depictio/projects/**, not referenced from source)`,
);

if (unresolved.length) {
  console.warn(
    `[icons] WARNING: ${unresolved.length} icon name(s) not found in their collection ` +
      `— these render blank at runtime:\n` +
      unresolved.map((n) => `  ${n}  (${[...used.get(n).files].join(', ')})`).join('\n'),
  );
}
if (absentCorpusDirs.length) {
  console.warn(
    `[icons] WARNING: dashboard corpus not in this build context: ${absentCorpusDirs.join(', ')}\n` +
      `  Icons authored only in dashboard YAML / .db_seeds JSON (tab_icon, icon,\n` +
      `  icon_name) are NOT bundled and will render blank under the app's CSP.\n` +
      `  Fix: make the corpus reachable from the build (for the viewer image,\n` +
      `  add "COPY depictio/projects ./depictio/projects/" to docker-images/Dockerfile.viewer).`,
  );
}
if (missingCollections.length) {
  console.warn(
    `[icons] WARNING: no collection installed for prefix(es): ${missingCollections.join(', ')}\n` +
      `  Install with: pnpm add -D ${missingCollections.map((p) => `@iconify-json/${p}`).join(' ')}\n` +
      `  then add the prefix to COLLECTIONS in scripts/generate-icon-subset.mjs`,
  );
}
