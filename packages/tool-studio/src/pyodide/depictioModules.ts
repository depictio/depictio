/**
 * Build-time (Node) collector of the depictio Python a recipe imports, shipped
 * into Tool Studio's Pyodide engine — the same approach as the serverless
 * bundle (depictio/serverless/pyodide/modules.py): the server's own files,
 * copied, not a second implementation.
 *
 *   depictio/recipes/__init__.py      verbatim: load_recipe, validate_sources,
 *                                     validate_schema, call_transform and the
 *                                     readers the engine calls as they are
 *   depictio/recipes/lib/*.py         verbatim (pure python + polars/numpy)
 *   depictio/models/models/transforms.py
 *                                     RecipeSource only, extracted from the real
 *                                     file (the rest of it reaches
 *                                     deltatables, which drags in the world)
 *   depictio/models/models/data_collections_types/indexed_file.py
 *                                     verbatim (pydantic only; a lib imports it)
 *
 * plus an empty `__init__.py` for every package on the way. Used by
 * scripts/genKinds.ts (→ public/pyodide/depictio_modules.json) and by the
 * Node-side engine test, which builds the tree straight from the repo.
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

/** Whole files shipped as they are, relative to the repo root. */
const VERBATIM = [
  'depictio/recipes/__init__.py',
  'depictio/models/models/data_collections_types/indexed_file.py',
  // `recipes._read_source_file` imports it lazily to read a YAML/JSON
  // samplesheet standing in for a CSV/TSV source (stdlib + polars + yaml only).
  'depictio/cli/cli/utils/record_sheets.py',
];
const LIB_DIR = 'depictio/recipes/lib';
const TRANSFORMS = 'depictio/models/models/transforms.py';

/** `RecipeSource` out of transforms.py: the module's non-depictio imports, then
 *  the class body up to the next top-level statement. */
export function extractRecipeSource(source: string): string {
  const lines = source.split('\n');
  const imports = lines.filter((l) => /^(from|import) /.test(l) && !/^from depictio[. ]/.test(l));
  const start = lines.findIndex((l) => l.startsWith('class RecipeSource('));
  if (start < 0) throw new Error(`${TRANSFORMS} defines no RecipeSource`);
  let end = start + 1;
  while (end < lines.length && !/^\S/.test(lines[end])) end++;
  const body = lines.slice(start, end).join('\n').trimEnd();
  if (/\bRunScope\b|\bdepictio\b/.test(body)) {
    throw new Error(`RecipeSource in ${TRANSFORMS} now reaches a depictio name; extend the extraction`);
  }
  return [
    `"""RecipeSource, extracted from ${TRANSFORMS} for Tool Studio's Pyodide engine."""`,
    '',
    ...imports,
    '',
    '',
    body,
    '',
  ].join('\n');
}

/** `{path in the Pyodide FS: source}`, or null when the depictio tree is absent. */
export function collectDepictioModules(repoRoot: string): Record<string, string> | null {
  const at = (rel: string) => resolve(repoRoot, rel);
  if (!existsSync(at(TRANSFORMS)) || !existsSync(at(LIB_DIR))) return null;
  const files: Record<string, string> = {};
  for (const rel of VERBATIM) files[rel] = readFileSync(at(rel), 'utf8');
  for (const name of readdirSync(at(LIB_DIR)).sort()) {
    if (name.endsWith('.py')) files[`${LIB_DIR}/${name}`] = readFileSync(at(`${LIB_DIR}/${name}`), 'utf8');
  }
  files[TRANSFORMS] = extractRecipeSource(readFileSync(at(TRANSFORMS), 'utf8'));
  for (const path of Object.keys(files)) {
    const parts = path.split('/').slice(0, -1);
    for (let i = 1; i <= parts.length; i++) {
      const init = `${parts.slice(0, i).join('/')}/__init__.py`;
      if (!(init in files)) files[init] = '';
    }
  }
  return Object.fromEntries(Object.entries(files).sort(([a], [b]) => a.localeCompare(b)));
}
