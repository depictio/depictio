/**
 * One validation pass over the draft, returning machine-readable diagnostics.
 *
 * The authoritative check is `depictio dev catalog validate`; this mirrors as
 * much of it as can run in a browser, so a contributor (or an agent driving the
 * app) learns about a rejection before opening the PR rather than from CI:
 *
 *   - the generated YAML against the same JSON Schemas the files declare
 *     (module.schema.json / output.schema.json, snapshotted from the model);
 *   - identity rules from `_check_identity_urls` and `check_identity`;
 *   - nf-core / EDAM existence against the vendored indices (`check_existence`);
 *   - fixture sanity from `_check_fixture_sanity` (data rows, cross-tool copy);
 *   - render grounding (grounding.ts, which mirrors the Render validators);
 *   - id uniqueness from `CatalogEntry` (render ids vs each other / the output).
 *
 * Every diagnostic carries a stable `code` and a `path` into the draft, and the
 * wizard `step` that fixes it, so the UI can link to the field and a script can
 * act on it without parsing prose.
 */
import Ajv2020 from 'ajv/dist/2020';
import yaml from 'js-yaml';
import moduleSchema from '../../public/module.schema.json';
import outputSchema from '../../public/output.schema.json';
import type { KindsMap, OutputMeta, ParsedFixture, RenderSpec, ToolMeta } from '../types';
import type { CatalogManifest } from './catalog';
import { validateAll } from './grounding';
import { genModuleYaml, genOutputYaml, outputId } from './yamlGen';

export type Severity = 'error' | 'warning';

export interface Diagnostic {
  /** Stable identifier, e.g. `identity.homepage_missing`, `render.role_dtype`. */
  code: string;
  severity: Severity;
  /** Where in the draft: `tool.homepage`, `output.find`, `fixture`, `renders[2]`. */
  path: string;
  message: string;
  /** Wizard step that fixes it: 0 Tool, 1 Fixture, 2 Visualizations. */
  step: 0 | 1 | 2;
  /** Set for render diagnostics. */
  renderUid?: string;
  /** Which output (allOutputs order) it belongs to, when the tool has several. */
  outputIndex?: number;
}

export interface ExistenceIndices {
  nfCoreModules?: Set<string>;
  edamTerms?: Set<string>;
}

export interface DraftToValidate {
  tool: ToolMeta;
  output: OutputMeta;
  fixture: ParsedFixture | null;
  renders: RenderSpec[];
  kinds: KindsMap;
  /** Committed catalog, for the cross-tool fixture copy check. */
  catalog?: CatalogManifest;
  indices?: ExistenceIndices;
  /** Appending to a committed output: identity and find are not authored here. */
  appendMode?: boolean;
  /** sha256 hex of the fixture bytes (async to compute; pass when known). */
  fixtureSha256?: string;
  /** Another output of the same tool: identity and module.yaml are checked once. */
  skipIdentity?: boolean;
}

const ajv = new Ajv2020({ allErrors: true, strict: false });
const validateModule = ajv.compile(moduleSchema);
const validateOutput = ajv.compile(outputSchema);

function schemaDiagnostics(
  which: 'module' | 'output',
  text: string,
  validate: typeof validateModule,
): Diagnostic[] {
  let doc: unknown;
  try {
    doc = yaml.load(text);
  } catch (e) {
    return [
      {
        code: `schema.${which}_yaml`,
        severity: 'error',
        path: which === 'module' ? 'tool' : 'output',
        message: `The generated ${which} YAML does not parse: ${(e as Error).message}`,
        step: 0,
      },
    ];
  }
  if (validate(doc)) return [];
  return (validate.errors ?? []).map((err) => {
    const field = err.instancePath.split('/').filter(Boolean);
    const isRender = which === 'output' && field[0] === 'renders_as';
    const extra =
      err.keyword === 'additionalProperties'
        ? ` (${String((err.params as { additionalProperty?: string }).additionalProperty)})`
        : '';
    return {
      code: `schema.${which}`,
      severity: 'error' as const,
      path: isRender
        ? `renders[${field[1]}]${field.length > 2 ? '.' + field.slice(2).join('.') : ''}`
        : `${which === 'module' ? 'tool' : 'output'}${field.length ? '.' + field.join('.') : ''}`,
      message: `${which === 'module' ? 'module.yaml' : 'output YAML'}${err.instancePath || ''} ${err.message}${extra}`,
      step: isRender ? 2 : 0,
    };
  });
}

/** `.../modules/nf-core/<path>[/meta.yml|/main.nf]` → `<path>` (`_nf_core_module`). */
export function nfCoreModuleOf(url: string | undefined): string | null {
  if (!url || !url.includes('/modules/nf-core/')) return null;
  let module = url.split('/modules/nf-core/')[1].replace(/\/+$/, '');
  for (const suffix of ['/meta.yml', '/main.nf']) {
    if (module.endsWith(suffix)) module = module.slice(0, -suffix.length);
  }
  return module;
}

function identityDiagnostics(tool: ToolMeta, indices?: ExistenceIndices): Diagnostic[] {
  const out: Diagnostic[] = [];
  const push = (code: string, path: string, message: string, severity: Severity = 'error') =>
    out.push({ code, severity, path, message, step: 0 });

  if (!tool.description?.trim())
    push('identity.description_missing', 'tool.description', 'A tool needs a description (shown on its catalog card).');
  if (!tool.homepage?.trim())
    push('identity.homepage_missing', 'tool.homepage', 'A tool needs a homepage (linked from its catalog card).');
  if (tool.biotools_url && !tool.biotools_url.startsWith('https://bio.tools/'))
    push('identity.biotools_url', 'tool.biotools_url', `biotools_url must be a https://bio.tools/ URL, got "${tool.biotools_url}".`);
  if (tool.nf_core_url && !tool.nf_core_url.includes('github.com/nf-core/modules'))
    push('identity.nf_core_url', 'tool.nf_core_url', `nf_core_url must point at github.com/nf-core/modules/..., got "${tool.nf_core_url}".`);
  if (tool.source_url && !/^https?:\/\//.test(tool.source_url))
    push('identity.source_url', 'tool.source_url', `source_url must be an http(s):// URL, got "${tool.source_url}".`);
  if (tool.homepage && !/^https?:\/\//.test(tool.homepage))
    push('identity.homepage_url', 'tool.homepage', 'The homepage should be an http(s):// URL.', 'warning');

  for (const [i, topic] of (tool.edam_topics ?? []).entries()) {
    // yamlGen canonicalises topic_NNNN; anything still not a URL is rejected by the model.
    const url = /(^|[/:])topic_\d{4}$/.test(topic.trim())
      ? `http://edamontology.org/${topic.trim().match(/topic_\d{4}$/)![0]}`
      : topic.trim();
    if (!url.startsWith('http://edamontology.org/topic_')) {
      push('identity.edam_prefix', `tool.edam_topics[${i}]`, `EDAM topics must be topic_NNNN ids or http://edamontology.org/topic_NNNN URLs, got "${topic}".`);
      continue;
    }
    const term = url.split('/').pop()!;
    if (indices?.edamTerms?.size && !indices.edamTerms.has(term))
      push('index.edam_unknown', `tool.edam_topics[${i}]`, `EDAM term "${term}" is not in the vendored index.`);
  }
  const module = nfCoreModuleOf(tool.nf_core_url);
  if (module && indices?.nfCoreModules?.size && !indices.nfCoreModules.has(module))
    push('index.nf_core_unknown', 'tool.nf_core_url', `nf-core module "${module}" is not in the vendored index.`);
  if (tool.version && !/^\d+\.\d+\.\d+$/.test(tool.version))
    push('identity.version', 'tool.version', `version must be MAJOR.MINOR.PATCH, got "${tool.version}".`);
  return out;
}

function findDiagnostics(output: OutputMeta): Diagnostic[] {
  const out: Diagnostic[] = [];
  if (!output.path_glob?.trim() && !output.filename?.trim())
    out.push({ code: 'find.missing', severity: 'error', path: 'output.find', message: 'An output needs a path glob or an exact file name to be recognised in a run.', step: 0 });
  if (output.path_glob_alt?.length && !output.path_glob?.trim())
    out.push({ code: 'find.alt_without_glob', severity: 'error', path: 'output.find.path_glob_alt', message: 'Alternative globs need a main path glob.', step: 0 });
  return out;
}

function fixtureDiagnostics(d: DraftToValidate): Diagnostic[] {
  const { fixture } = d;
  if (!fixture) return d.appendMode ? [] : [{ code: 'fixture.missing', severity: 'error', path: 'fixture', message: 'Add a fixture: a sample of the output file.', step: 1 }];
  const out: Diagnostic[] = [];
  if (fixture.raw) {
    const lines = fixture.raw.split(/\r?\n/).filter((l) => l.trim());
    if (lines.length < 2)
      out.push({ code: 'fixture.no_data', severity: 'error', path: 'fixture', message: 'The fixture has no data rows; it would ground every binding while showing nothing.', step: 1 });
  }
  for (const w of fixture.parseWarnings ?? []) {
    if (/no data rows/.test(w)) continue; // reported above
    out.push({ code: 'fixture.parse', severity: 'warning', path: 'fixture', message: w, step: 1 });
  }
  if (d.fixtureSha256 && d.catalog) {
    for (const t of d.catalog.tools) {
      if (t.id === d.tool.id) continue; // same tool sharing a fixture is fine
      const twin = t.outputs.find((o) => o.fixtureSha256 === d.fixtureSha256);
      if (twin) {
        out.push({ code: 'fixture.duplicate', severity: 'error', path: 'fixture', message: `This fixture is byte-identical to ${twin.id}'s. A fixture must be a sample of THIS output.`, step: 1 });
        break;
      }
    }
  }
  return out;
}

/** Keys of a recipe's `OUTPUT_SCHEMA = {...}` literal, read statically (the
 *  shape every catalog recipe uses). null when the literal cannot be found.
 *
 *  The literal is delimited by a brace-depth scan from its opening `{`, which
 *  skips string literals (single, double, triple-quoted) and `#` comments: a
 *  regex up to the next column-0 `}` swallowed `OPTIONAL_OUTPUT_SCHEMA` after a
 *  one-line `OUTPUT_SCHEMA = {...}`. Only top-level keys (depth 1) count. */
export function recipeOutputColumns(code: string): string[] | null {
  const head = /^OUTPUT_SCHEMA\b[^=\n]*=\s*\{/m.exec(code);
  if (!head) return null;
  const keys: string[] = [];
  let depth = 1;
  let i = head.index + head[0].length;
  // The last string literal closed at depth 1, waiting for a `:` to make it a key.
  let pending: string | null = null;
  while (i < code.length && depth > 0) {
    const c = code[i];
    if (c === '#') {
      while (i < code.length && code[i] !== '\n') i++;
      continue;
    }
    if (c === '"' || c === "'") {
      const triple = code.startsWith(c.repeat(3), i);
      const quote = triple ? c.repeat(3) : c;
      let j = i + quote.length;
      let text = '';
      while (j < code.length && !code.startsWith(quote, j)) {
        if (code[j] === '\\') {
          text += code[j + 1] ?? '';
          j += 2;
          continue;
        }
        if (!triple && code[j] === '\n') break; // unterminated: stop at the line end
        text += code[j];
        j++;
      }
      i = j + quote.length;
      if (depth === 1) pending = text;
      continue;
    }
    if (c === '{' || c === '[' || c === '(') depth++;
    else if (c === '}' || c === ']' || c === ')') depth--;
    if (c === ':' && depth === 1 && pending !== null) keys.push(pending);
    if (!/\s/.test(c)) pending = null;
    i++;
  }
  return depth === 0 ? keys : null;
}

/** `load_recipe` (depictio/recipes/__init__.py) refuses a module without these. */
const RECIPE_SYMBOLS: Array<[RegExp, string]> = [
  [/^SOURCES\b/m, 'SOURCES'],
  [/^OUTPUT_SCHEMA\b/m, 'OUTPUT_SCHEMA'],
  [/^def transform\s*\(/m, 'transform()'],
];

function recipeDiagnostics(d: DraftToValidate): Diagnostic[] {
  const recipe = d.output.recipe;
  if (!recipe) return [];
  const out: Diagnostic[] = [];
  const push = (code: string, message: string, severity: Severity = 'error', step: 0 | 1 = 1) =>
    out.push({ code, severity, path: 'output.recipe', message, step });
  if (!recipe.code.trim()) {
    // An imported reference whose file is not here (a pipeline-keyed
    // `nf-core/<pipeline>/<name>.py`, or a module file left out of the
    // import): kept verbatim, and only CI can check it.
    if (recipe.ref?.trim()) {
      push('recipe.external', `The recipe ${recipe.ref} is not loaded here; it is exported as a reference and checked by CI only.`, 'warning');
      return out;
    }
    push('recipe.empty', 'The recipe is empty.');
    return out;
  }
  for (const [re, name] of RECIPE_SYMBOLS)
    if (!re.test(recipe.code)) push('recipe.missing_symbol', `The recipe defines no ${name} (load_recipe requires it).`);
  // load_recipe: "SOURCES must be a non-empty list".
  if (/^SOURCES[^=\n]*=\s*\[\s*\]/m.test(recipe.code))
    push('recipe.empty_sources', 'SOURCES is empty: declare at least one RecipeSource (load_recipe rejects an empty list).');
  const declared = recipeOutputColumns(recipe.code);
  if (declared && !declared.length)
    push('recipe.empty_schema', 'OUTPUT_SCHEMA is empty: declare the columns transform() returns.', 'warning');
  if (declared && d.fixture) {
    const have = new Set(d.fixture.columns.map((c) => c.name));
    const absent = declared.filter((c) => !have.has(c));
    if (absent.length)
      push(
        'recipe.fixture_mismatch',
        `The fixture lacks ${absent.join(', ')} from OUTPUT_SCHEMA; it must be a sample of the recipe's output (run the recipe to produce it).`,
      );
  }
  return out;
}

/** Declared `columns` (an imported recipe-free output) against the fixture:
 *  the bindings are grounded against both in CI, so a gap is worth a word. */
function columnsDiagnostics(d: DraftToValidate): Diagnostic[] {
  const cols = Object.keys(d.output.columns ?? {});
  if (!cols.length || d.output.recipe || !d.fixture?.columns.length) return [];
  const have = new Set(d.fixture.columns.map((c) => c.name));
  const absent = cols.filter((c) => !have.has(c));
  return absent.length
    ? [{ code: 'output.columns_mismatch', severity: 'warning', path: 'output.columns', step: 1, message: `The output declares ${absent.join(', ')} in columns, which the fixture lacks.` }]
    : [];
}

function idDiagnostics(d: DraftToValidate): Diagnostic[] {
  const out: Diagnostic[] = [];
  const oid = outputId(d.tool.id, d.output.slug);
  const seen = new Map<string, string>();
  d.renders.forEach((r, i) => {
    if (!r.id) return;
    if (r.id === oid)
      out.push({ code: 'render.id_collides_output', severity: 'error', path: `renders[${i}].id`, renderUid: r.uid, message: `Render id "${r.id}" is the output's own id.`, step: 2 });
    if (seen.has(r.id))
      out.push({ code: 'render.id_duplicate', severity: 'error', path: `renders[${i}].id`, renderUid: r.uid, message: `Render id "${r.id}" is used twice.`, step: 2 });
    seen.set(r.id, r.uid);
  });
  return out;
}

/** Every diagnostic for the draft, errors first. Pure and synchronous. */
export function validateDraft(d: DraftToValidate): Diagnostic[] {
  const all: Diagnostic[] = [];
  if (!d.appendMode) {
    if (!d.skipIdentity) all.push(...identityDiagnostics(d.tool, d.indices));
    all.push(...findDiagnostics(d.output));
    if (d.tool.id && d.tool.name && !d.skipIdentity)
      all.push(...schemaDiagnostics('module', genModuleYaml(d.tool), validateModule));
    if (d.tool.id && d.output.slug)
      all.push(
        ...schemaDiagnostics(
          'output',
          genOutputYaml(d.tool, d.output, d.fixture?.fileName ?? 'fixture.csv', d.renders),
          validateOutput,
        ),
      );
  }
  all.push(...fixtureDiagnostics(d));
  all.push(...recipeDiagnostics(d));
  all.push(...columnsDiagnostics(d));
  if (!d.renders.length && !d.appendMode)
    all.push({ code: 'renders.empty', severity: 'error', path: 'renders', message: 'Add at least one visualization.', step: 2 });
  if (d.fixture) {
    const index = new Map(d.renders.map((r, i) => [r.uid, i]));
    for (const g of validateAll(d.renders, d.fixture.columns, d.kinds)) {
      all.push({
        code: g.code ?? 'render.grounding',
        severity: g.severity,
        path: `renders[${index.get(g.renderUid) ?? '?'}]`,
        renderUid: g.renderUid,
        message: g.message,
        step: 2,
      });
    }
  }
  all.push(...idDiagnostics(d));
  return all.sort((a, b) => (a.severity === b.severity ? a.step - b.step : a.severity === 'error' ? -1 : 1));
}

export interface OutputToValidate {
  output: OutputMeta;
  fixture: ParsedFixture | null;
  renders: RenderSpec[];
  fixtureSha256?: string;
}

/** Diagnostics for a whole tool: identity once, then every output, plus the
 *  checks that only exist across outputs (slugs, render ids and fixture file
 *  names must be unique within the tool folder). Paths of every output but a
 *  lone one are prefixed `outputs[i].`. */
export function validateTool(
  base: Omit<DraftToValidate, 'output' | 'fixture' | 'renders' | 'fixtureSha256' | 'skipIdentity'>,
  outputs: OutputToValidate[],
): Diagnostic[] {
  const many = outputs.length > 1;
  const all: Diagnostic[] = [];
  outputs.forEach((o, i) => {
    for (const d of validateDraft({ ...base, ...o, skipIdentity: i > 0 })) {
      const own = !d.path.startsWith('tool');
      all.push({ ...d, ...(many ? { outputIndex: i } : {}), path: many && own ? `outputs[${i}].${d.path}` : d.path });
    }
  });
  if (many) {
    const seen = (key: (o: OutputToValidate) => string | undefined, code: string, what: string) => {
      const firstAt = new Map<string, number>();
      outputs.forEach((o, i) => {
        const k = key(o);
        if (!k) return;
        if (firstAt.has(k))
          all.push({ code, severity: 'error', path: `outputs[${i}]`, outputIndex: i, step: code === 'fixture.name_clash' ? 1 : 0, message: `${what} "${k}" is already used by output ${firstAt.get(k)! + 1}.` });
        else firstAt.set(k, i);
      });
    };
    seen((o) => o.output.slug || undefined, 'output.slug_duplicate', 'Output slug');
    seen((o) => o.fixture?.fileName, 'fixture.name_clash', 'Fixture file name');
    const ids = new Map<string, number>();
    outputs.forEach((o, i) =>
      o.renders.forEach((r, j) => {
        if (!r.id) return;
        const prev = ids.get(r.id);
        if (prev !== undefined && prev !== i)
          all.push({ code: 'render.id_duplicate', severity: 'error', path: `outputs[${i}].renders[${j}].id`, outputIndex: i, renderUid: r.uid, step: 2, message: `Render id "${r.id}" is also used in output ${prev + 1}; ids are unique within a tool.` });
        else ids.set(r.id, i);
      }),
    );
  }
  return all.sort((a, b) => (a.severity === b.severity ? a.step - b.step : a.severity === 'error' ? -1 : 1));
}

/** sha256 hex of a string's UTF-8 bytes (what `validate` hashes on disk). */
export async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** Parse a vendored index file (`#` comments and blank lines ignored). */
export function parseIndex(text: string): Set<string> {
  return new Set(
    text
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#')),
  );
}
