#!/usr/bin/env node
/**
 * Shim-coverage gate for the serverless static bundle.
 *
 * Walks the module graph the static entry (`src/static-runtime/main.tsx`)
 * actually pulls in — following named imports to the file each name comes
 * from, barrels included, and applying the same module swaps as
 * `vite.static.config.ts` — and collects every `depictio-react-core` api.ts
 * export the graph imports. Each one that reaches the network (its body, or a
 * local function it calls, uses `fetch` / `authFetch` / a WebSocket /
 * EventSource) must be either
 *
 *   - DEFINED in `tabApiShim.ts` or `apiShim.ts` (an `export * from` the real
 *     api does not count — that is the real network call), or
 *   - listed in apiShim's `OFFLINE_UNSUPPORTED` with the reason it may stay
 *     unshimmed (a guarded opener, a write path a bundle never reaches).
 *
 * The audit found seven such calls the static App made with nothing behind
 * them (persistent sections, the funnel, ranked values, …), invisible to the
 * no-network Playwright guard because a `file://` page resolves
 * `/depictio/api/...` to another `file://` URL. This makes a new one a CI
 * failure instead.
 *
 *   node scripts/check-static-shim.mjs            # exit 1 on a gap
 *   node scripts/check-static-shim.mjs --list     # also print the used set
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const VIEWER = path.resolve(HERE, '..');
const ROOT = path.resolve(VIEWER, '../..');
const CORE = path.join(ROOT, 'packages/depictio-react-core/src');
const RUNTIME = path.join(VIEWER, 'src/static-runtime');
const API = path.join(CORE, 'api.ts');
const ENTRY = path.join(RUNTIME, 'main.tsx');
const SHIM_FILES = [path.join(RUNTIME, 'tabApiShim.ts'), path.join(RUNTIME, 'apiShim.ts')];

// The swaps of vite.static.config.ts (api.ts is handled by name, below).
const SWAPS = {
  [path.join(CORE, 'realtime.ts')]: path.join(RUNTIME, 'realtimeShim.ts'),
  [path.join(VIEWER, 'src/hooks/useCurrentUser.ts')]: path.join(RUNTIME, 'useCurrentUserShim.ts'),
  [path.join(VIEWER, 'src/hooks/useServerStatus.ts')]: path.join(RUNTIME, 'serverStatusShim.ts'),
  [path.join(VIEWER, 'src/chrome/variants/index.ts')]: path.join(RUNTIME, 'chromeVariantShim.ts'),
  [path.join(CORE, 'components/JBrowseRenderer.tsx')]: path.join(RUNTIME, 'jbrowseStub.tsx'),
};
// The project page's server-only parts, swapped for one empty stand-in.
const PROJECT_STUBS = path.join(RUNTIME, 'projectServerStubs.tsx');
for (const m of JSON.parse(fs.readFileSync(path.join(RUNTIME, 'projectServerParts.json'), 'utf8')).modules) {
  SWAPS[path.join(VIEWER, m)] = PROJECT_STUBS;
}
const SWAP_TARGETS = new Set(Object.values(SWAPS));
const ALIASES = [
  ['depictio-react-core', CORE],
  ['depictio-components', path.join(ROOT, 'packages/depictio-components/src/lib')],
  ['depictio-static-core', path.join(ROOT, 'packages/depictio-static-core/src')],
];

const viteConfig = fs.readFileSync(path.join(VIEWER, 'vite.static.config.ts'), 'utf8');
for (const shim of [...Object.values(SWAPS), SHIM_FILES[0]]) {
  if (!viteConfig.includes(path.basename(shim))) {
    console.error(`check-static-shim: ${path.basename(shim)} is no longer swapped in vite.static.config.ts — update SWAPS`);
    process.exit(2);
  }
}

const sourceCache = new Map();
function parse(file) {
  let sf = sourceCache.get(file);
  if (!sf) {
    sf = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
    sourceCache.set(file, sf);
  }
  return sf;
}

function tryFile(base) {
  for (const cand of [base, `${base}.ts`, `${base}.tsx`, `${base}/index.ts`, `${base}/index.tsx`]) {
    if (fs.existsSync(cand) && fs.statSync(cand).isFile()) return cand;
  }
  return null;
}

function resolve(spec, importer) {
  let base = null;
  if (spec.startsWith('.')) base = path.resolve(path.dirname(importer), spec);
  else {
    for (const [name, dir] of ALIASES) {
      if (spec === name) base = dir;
      else if (spec.startsWith(`${name}/`)) base = path.join(dir, spec.slice(name.length + 1));
    }
  }
  if (base === null) return null; // a package: not ours to walk
  const file = tryFile(base.replace(/\.(js|mjs)$/, ''));
  if (!file || !/\.(ts|tsx)$/.test(file)) return null;
  // A shim reaches its real module (module-shim treats every swap target as a
  // shim: jbrowseStub mounts the real JBrowseRenderer, whose graph is walked).
  if (SHIM_FILES.includes(importer) || SWAP_TARGETS.has(importer)) return file;
  return SWAPS[file] ?? file;
}

// ---- api.ts: which exports reach the network --------------------------------

const NETWORK_RE = /\b(authFetch|fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\s*\(|new\s+(WebSocket|EventSource|XMLHttpRequest)\b/;

function apiNetworkedExports() {
  const sf = parse(API);
  const bodies = new Map();
  const exported = new Set();
  const isExported = (n) => n.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword);
  for (const stmt of sf.statements) {
    if (ts.isFunctionDeclaration(stmt) && stmt.name) {
      bodies.set(stmt.name.text, stmt.getText(sf));
      if (isExported(stmt)) exported.add(stmt.name.text);
    } else if (ts.isVariableStatement(stmt)) {
      for (const d of stmt.declarationList.declarations) {
        if (ts.isIdentifier(d.name) && d.initializer) {
          bodies.set(d.name.text, d.initializer.getText(sf));
          if (isExported(stmt)) exported.add(d.name.text);
        }
      }
    }
  }
  const networked = new Set([...bodies].filter(([, b]) => NETWORK_RE.test(b)).map(([n]) => n));
  let grew = true;
  while (grew) {
    grew = false;
    for (const [name, body] of bodies) {
      if (networked.has(name)) continue;
      for (const callee of networked) {
        if (callee !== name && new RegExp(`\\b${callee}\\s*\\(`).test(body)) {
          networked.add(name);
          grew = true;
          break;
        }
      }
    }
  }
  return new Set([...exported].filter((n) => networked.has(n)));
}

// ---- export resolution through barrels --------------------------------------

/** The file a name exported by `file` is defined in (or API for api names). */
function originOf(file, name, seen = new Set()) {
  if (file === API) return API;
  const key = `${file}#${name}`;
  if (seen.has(key)) return null;
  seen.add(key);
  const sf = parse(file);
  const starTargets = [];
  for (const stmt of sf.statements) {
    if (ts.isExportDeclaration(stmt)) {
      const target = stmt.moduleSpecifier ? resolveApi(stmt.moduleSpecifier.text, file) : null;
      if (stmt.exportClause && ts.isNamedExports(stmt.exportClause)) {
        for (const el of stmt.exportClause.elements) {
          if (el.name.text !== name) continue;
          const local = (el.propertyName ?? el.name).text;
          if (target) return originOf(target, local, seen);
          return localImportOrigin(sf, file, local, seen) ?? file;
        }
      } else if (!stmt.exportClause && target) {
        starTargets.push(target);
      }
    }
  }
  if (declaresLocally(sf, name)) return file;
  for (const target of starTargets) {
    if (target === API) {
      if (apiExports.has(name)) return API;
      continue;
    }
    const o = originOf(target, name, seen);
    if (o && (o === API || declaresLocally(parse(o), name) || o !== target)) return o;
  }
  return null;
}

function localImportOrigin(sf, file, local, seen) {
  for (const stmt of sf.statements) {
    if (!ts.isImportDeclaration(stmt) || !stmt.importClause?.namedBindings) continue;
    const nb = stmt.importClause.namedBindings;
    if (!ts.isNamedImports(nb)) continue;
    for (const el of nb.elements) {
      if (el.name.text === local) {
        const target = resolveApi(stmt.moduleSpecifier.text, file);
        return target ? originOf(target, (el.propertyName ?? el.name).text, seen) : null;
      }
    }
  }
  return null;
}

function declaresLocally(sf, name) {
  for (const stmt of sf.statements) {
    if (name === 'default') {
      if (ts.isExportAssignment(stmt)) return true;
      if (stmt.modifiers?.some((m) => m.kind === ts.SyntaxKind.DefaultKeyword)) return true;
      continue;
    }
    if (
      (ts.isFunctionDeclaration(stmt) || ts.isClassDeclaration(stmt) || ts.isEnumDeclaration(stmt)) &&
      stmt.name?.text === name
    )
      return true;
    if (ts.isVariableStatement(stmt)) {
      for (const d of stmt.declarationList.declarations) {
        if (ts.isIdentifier(d.name) && d.name.text === name) return true;
      }
    }
  }
  return false;
}

/** `resolve`, but api.ts stays api.ts (its swap is checked by name). */
function resolveApi(spec, importer) {
  return resolve(spec, importer);
}

const apiExports = (() => {
  const out = new Set();
  const sf = parse(API);
  for (const stmt of sf.statements) {
    const exp = stmt.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword);
    if (!exp) continue;
    if ((ts.isFunctionDeclaration(stmt) || ts.isClassDeclaration(stmt)) && stmt.name) out.add(stmt.name.text);
    if (ts.isVariableStatement(stmt)) {
      for (const d of stmt.declarationList.declarations) if (ts.isIdentifier(d.name)) out.add(d.name.text);
    }
  }
  return out;
})();

// ---- the walk ----------------------------------------------------------------

const used = new Map(); // api name -> first importer
const visited = new Set();
const queue = [ENTRY];

function visit(file) {
  if (visited.has(file) || file === API || SHIM_FILES.includes(file)) return;
  visited.add(file);
  const sf = parse(file);
  const follow = (spec, names) => {
    const target = resolveApi(spec, file);
    if (!target) return;
    if (names === null) {
      if (target !== API) queue.push(target);
      return;
    }
    for (const name of names) {
      const origin = target === API ? API : originOf(target, name);
      if (origin === API) {
        if (!used.has(name)) used.set(name, path.relative(ROOT, file));
      } else queue.push(origin ?? target);
      // (A re-export is not a use: visiting a barrel walks its imports, never
      // its `export … from` lines, so only the names someone imports count.)
    }
  };
  const walk = (node) => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const clause = node.importClause;
      if (!clause) follow(node.moduleSpecifier.text, null);
      else if (!clause.isTypeOnly) {
        const names = [];
        if (clause.name) names.push('default');
        const nb = clause.namedBindings;
        if (nb && ts.isNamedImports(nb)) {
          for (const el of nb.elements) if (!el.isTypeOnly) names.push((el.propertyName ?? el.name).text);
        } else if (nb && ts.isNamespaceImport(nb)) {
          const target = resolveApi(node.moduleSpecifier.text, file);
          if (target === API) {
            // `import * as api` — every property read off it counts.
            const ns = nb.name.text;
            const re = new RegExp(`\\b${ns}\\.([A-Za-z_$][\\w$]*)`, 'g');
            for (const m of sf.getText().matchAll(re)) names.push(m[1]);
          } else if (target) queue.push(target);
        }
        follow(node.moduleSpecifier.text, names);
      }
    } else if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments[0] &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      follow(node.arguments[0].text, null);
    }
    ts.forEachChild(node, walk);
  };
  walk(sf);
}

while (queue.length) visit(queue.shift());

// ---- the shims -----------------------------------------------------------------

function definedExports(file) {
  const out = new Set();
  const sf = parse(file);
  for (const stmt of sf.statements) {
    const exp = stmt.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword);
    if (exp && ts.isFunctionDeclaration(stmt) && stmt.name) out.add(stmt.name.text);
    if (exp && ts.isVariableStatement(stmt)) {
      for (const d of stmt.declarationList.declarations) if (ts.isIdentifier(d.name)) out.add(d.name.text);
    }
    if (ts.isExportDeclaration(stmt) && stmt.exportClause && ts.isNamedExports(stmt.exportClause)) {
      for (const el of stmt.exportClause.elements) out.add(el.name.text);
    }
  }
  return out;
}

function declaredUnsupported() {
  const sf = parse(SHIM_FILES[1]);
  const out = new Map();
  for (const stmt of sf.statements) {
    if (!ts.isVariableStatement(stmt)) continue;
    for (const d of stmt.declarationList.declarations) {
      if (!ts.isIdentifier(d.name) || d.name.text !== 'OFFLINE_UNSUPPORTED' || !d.initializer) continue;
      let init = d.initializer;
      while (ts.isAsExpression(init) || ts.isSatisfiesExpression?.(init)) init = init.expression;
      if (!ts.isObjectLiteralExpression(init)) continue;
      for (const p of init.properties) {
        if (ts.isPropertyAssignment(p)) {
          const key = ts.isIdentifier(p.name) || ts.isStringLiteral(p.name) ? p.name.text : null;
          if (key) out.set(key, p.initializer.getText(sf));
        }
      }
    }
  }
  return out;
}

const networked = apiNetworkedExports();
const shimmed = new Set(SHIM_FILES.flatMap((f) => [...definedExports(f)]));
const unsupported = declaredUnsupported();

const gaps = [...used].filter(([name]) => networked.has(name) && !shimmed.has(name) && !unsupported.has(name));
const stale = [...unsupported.keys()].filter((name) => shimmed.has(name) || !networked.has(name));

if (process.argv.includes('--list')) {
  const rows = [...used].filter(([n]) => networked.has(n)).sort();
  for (const [name, from] of rows) {
    const how = shimmed.has(name) ? 'shimmed' : unsupported.has(name) ? 'declared unsupported' : 'GAP';
    console.log(`${how.padEnd(22)} ${name}  (${from})`);
  }
}
console.log(
  `check-static-shim: ${visited.size} modules, ${[...used.keys()].filter((n) => networked.has(n)).length} networked api calls reachable, ${gaps.length} gap(s)`,
);
for (const name of stale) {
  console.error(`  stale OFFLINE_UNSUPPORTED entry: ${name} (${shimmed.has(name) ? 'now shimmed' : 'not a networked api export'})`);
}
for (const [name, from] of gaps) {
  console.error(`  unshimmed network call: ${name} (imported by ${from})`);
}
process.exit(gaps.length || stale.length ? 1 : 0);
