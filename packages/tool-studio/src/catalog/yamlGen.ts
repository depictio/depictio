/**
 * Generate the on-disk catalog files for a tool entry, matching the format the
 * loader (`_load_tool_dir`) + Pydantic models expect and the aesthetic of the
 * committed examples (flow-style `renders_as` items, `# yaml-language-server`
 * header). `columns` is deliberately OMITTED — the exported fixture grounds the
 * bindings in CI (schema-ownership rule: fixture present ⇒ grounding deferred).
 */
import type { CardRender, OutputMeta, RenderSpec, TableRender, ToolMeta } from '../types';
import { canonicalNfCoreUrl } from './fromNfCore';

/** Words PyYAML's implicit resolvers turn into booleans or null. */
const YAML_BOOL_OR_NULL = /^(y|yes|n|no|true|false|on|off|null|~)$/i;

/** True if a scalar can be emitted plain (no quotes) in YAML flow context.
 *
 *  The leading character MUST be a letter or `_`. That is the whole point: every
 *  scalar PyYAML resolves to a non-string starts with a digit, sign, dot or
 *  tilde — `30`, `1.5`, `.inf`, `2024-01-01` (a date), `12:30` (sexagesimal).
 *  Emitting those plain produced `dict_kwargs: {nbinsx: 30}`, which the catalog
 *  model (`dict_kwargs: dict[str, str]`) rejects outright, since Pydantic v2
 *  does not coerce int/bool → str. Letters/digits/_-./: after the first char
 *  keep URLs (https://…) unquoted; spaces and globs (`*`) still get quoted, and
 *  no `: ` (colon-space) can occur since spaces aren't allowed — safe in both
 *  block and flow contexts.
 */
function isPlainSafe(s: string): boolean {
  if (!/^[A-Za-z_][A-Za-z0-9_.\-/:]*$/.test(s)) return false;
  return !YAML_BOOL_OR_NULL.test(s);
}

/** Serialize a scalar for a YAML flow mapping value. */
function flowScalar(v: string): string {
  if (isPlainSafe(v)) return v;
  return JSON.stringify(v); // valid YAML double-quoted string
}

/** `[a, b]` flow sequence of scalars (e.g. a card's `attrition_cols`). */
function flowList(values: string[]): string {
  return `[${values.map(flowScalar).join(', ')}]`;
}

/** `{k1: v1, k2: v2}` flow mapping from ordered [key, value] pairs. A value
 *  that is a column LIST (a sankey's steps, a sunburst's ranks) is written as a
 *  flow sequence — `Render.roles` types those as `list[str]`. */
function flowMap(pairs: [string, string | string[]][]): string {
  return `{${pairs.map(([k, v]) => `${k}: ${flowValue(v)}`).join(', ')}}`;
}

const flowValue = (v: string | string[]): string =>
  Array.isArray(v) ? flowList(v) : flowScalar(v);

/** One `renders_as` list item as a compact flow mapping. When set, the optional
 *  `id` is emitted first (matching the catalog convention) so the render is
 *  addressable by a dashboard via `use: <tool>/<id>`. */
export function renderToFlow(render: RenderSpec): string {
  // `id: X, ` prefix, injected right after the opening brace when present.
  const idp = render.id ? `id: ${flowScalar(render.id)}, ` : '';
  if (render.component === 'figure') {
    // Code mode: emit the snippet as `code` (a double-quoted scalar preserves
    // its newlines via \n). UI mode: visu_type + dict_kwargs.
    if (render.code != null) {
      return `{ ${idp}component: figure, code: ${flowScalar(render.code)} }`;
    }
    const kwargs = flowMap(Object.entries(render.dict_kwargs ?? {}).map(([k, v]) => [k, v]));
    return `{ ${idp}component: figure, visu_type: ${render.visu_type}, dict_kwargs: ${kwargs} }`;
  }
  if (render.component === 'card') {
    const head: [string, string][] = [
      ['component', 'card'],
      ['column', render.column],
      ['aggregation', render.aggregation],
    ];
    const parts = [
      ...head.map(([k, v]) => `${k}: ${flowScalar(v)}`),
      ...cardFieldFragments(render),
    ];
    return `{ ${idp}${parts.join(', ')} }`;
  }
  if (render.component === 'table') {
    const parts = ['component: table', ...tableFieldFragments(render)];
    return `{ ${idp}${parts.join(', ')} }`;
  }
  if (render.component === 'interactive') {
    return (
      `{ ${idp}component: interactive, interactive_type: ${render.interactive_type}, ` +
      `column_name: ${flowScalar(render.column_name)} }`
    );
  }
  // advanced_viz
  const roles = flowMap(Object.entries(render.roles).map(([k, v]) => [k, v]));
  return `{ ${idp}component: advanced_viz, kind: ${render.kind}, roles: ${roles} }`;
}

/** Every optional card field, as ordered `key: value` fragments.
 *
 *  Single source for both the flow and the block writer — they used to carry
 *  their own copies of the field list and drifted apart. The set mirrors the
 *  card block of `Render` in the catalog model; numeric fields are emitted
 *  unquoted on purpose (the model types them as int/float, unlike dict_kwargs). */
function cardFieldFragments(render: CardRender): string[] {
  const bits: string[] = [];
  // aggregations is a flow SEQUENCE, not a mapping.
  if (render.aggregations?.length) bits.push(`aggregations: [${render.aggregations.join(', ')}]`);
  if (render.secondary_layout) bits.push(`secondary_layout: ${render.secondary_layout}`);
  if (render.breakdown_col) bits.push(`breakdown_col: ${flowScalar(render.breakdown_col)}`);
  if (typeof render.top_n_count === 'number') bits.push(`top_n_count: ${render.top_n_count}`);
  if (typeof render.coverage_max === 'number') bits.push(`coverage_max: ${render.coverage_max}`);
  if (typeof render.threshold_value === 'number')
    bits.push(`threshold_value: ${render.threshold_value}`);
  if (render.threshold_direction)
    bits.push(`threshold_direction: ${render.threshold_direction}`);
  if (typeof render.threshold_warn === 'number')
    bits.push(`threshold_warn: ${render.threshold_warn}`);
  if (render.attrition_cols?.length)
    bits.push(`attrition_cols: ${flowList(render.attrition_cols)}`);
  if (render.trend_col) bits.push(`trend_col: ${flowScalar(render.trend_col)}`);
  if (render.filter_expr) bits.push(`filter_expr: ${flowScalar(render.filter_expr)}`);
  return bits;
}

/** Every optional table field, as ordered `key: value` fragments — the same
 *  single-source arrangement as `cardFieldFragments`, for the same reason. */
function tableFieldFragments(render: TableRender): string[] {
  const bits: string[] = [];
  if (render.columns?.length) bits.push(`columns: ${flowList(render.columns)}`);
  if (typeof render.page_size === 'number') bits.push(`page_size: ${render.page_size}`);
  if (typeof render.sortable === 'boolean') bits.push(`sortable: ${render.sortable}`);
  if (typeof render.filterable === 'boolean') bits.push(`filterable: ${render.filterable}`);
  if (render.row_selection_enabled) bits.push('row_selection_enabled: true');
  if (render.row_selection_column)
    bits.push(`row_selection_column: ${flowScalar(render.row_selection_column)}`);
  return bits;
}

/** Above this rendered width a flow `{ … }` item is expanded to block YAML so
 *  long renders (many dict_kwargs, code snippets, role maps) stay readable. */
const MAX_FLOW_WIDTH = 72;

/** Block-YAML lines for a render (no leading "- "), used when the flow form is
 *  too long. Mirrors renderToFlow's fields, one per line. */
function renderToBlock(render: RenderSpec): string[] {
  const idLine = render.id ? [`id: ${flowScalar(render.id)}`] : [];
  if (render.component === 'figure') {
    const lines = [...idLine, 'component: figure'];
    if (render.visu_type) lines.push(`visu_type: ${render.visu_type}`);
    const kw = render.dict_kwargs ?? {};
    const keys = Object.keys(kw);
    if (keys.length) {
      lines.push('dict_kwargs:');
      for (const k of keys) lines.push(`  ${k}: ${flowScalar(kw[k])}`);
    }
    return lines;
  }
  if (render.component === 'card') {
    return [
      ...idLine,
      'component: card',
      `column: ${flowScalar(render.column)}`,
      `aggregation: ${render.aggregation}`,
      ...cardFieldFragments(render),
    ];
  }
  if (render.component === 'table') {
    return [...idLine, 'component: table', ...tableFieldFragments(render)];
  }
  if (render.component === 'advanced_viz') {
    const lines = [...idLine, 'component: advanced_viz', `kind: ${render.kind}`];
    const roles = Object.entries(render.roles);
    if (roles.length) {
      lines.push('roles:');
      for (const [k, v] of roles) lines.push(`  ${k}: ${flowValue(v)}`);
    }
    return lines;
  }
  return [renderToFlow(render)];
}

/** The `renders_as` list-item body WITHOUT the leading "- ". Multi-line for
 *  code-mode figures (block scalar) or any render whose flow form exceeds
 *  MAX_FLOW_WIDTH; a single flow mapping otherwise. */
export function renderItemLines(render: RenderSpec): string[] {
  if (render.component === 'figure' && render.code != null) {
    const idLine = render.id ? [`id: ${flowScalar(render.id)}`] : [];
    return [...idLine, 'component: figure', 'code: |-', ...render.code.split('\n').map((l) => `  ${l}`)];
  }
  const flow = renderToFlow(render);
  if (`- ${flow}`.length <= MAX_FLOW_WIDTH) return [flow];
  return renderToBlock(render);
}

/** The full `renders_as` snippet for one render, as it appears in the output
 *  YAML (leading "- " + aligned continuation) — reused by the designer's
 *  per-render card so what it shows matches what gets written. */
export function renderToSnippet(render: RenderSpec): string {
  return renderItemLines(render)
    .map((l, i) => (i === 0 ? `- ${l}` : `  ${l}`))
    .join('\n');
}

/** The output id derived from tool + output slug (e.g. `mosdepth_coverage`). */
export function outputId(toolId: string, slug: string): string {
  return `${toolId}_${slug}`;
}

const indentBlock = (text: string, spaces: number) =>
  text
    .split('\n')
    .map((l) => (l ? ' '.repeat(spaces) + l : l))
    .join('\n');

export interface AppendResult {
  /** The merged YAML text (what gets committed / downloaded). Unchanged from
   *  the input when `problem` is set. */
  yaml: string;
  /** 0-based indices (into `yaml.split('\n')`) of the inserted render lines,
   *  so the Export preview can highlight exactly what was appended. */
  addedLines: number[];
  /** Set when the file's `renders_as` is in a shape this textual splice cannot
   *  edit safely. The caller must surface it and refuse to write — silently
   *  producing broken YAML (or a second `renders_as` key, which YAML resolves
   *  to the LAST one, dropping every existing render) is far worse than asking
   *  for a hand edit. */
  problem?: string;
}

/** The `renders_as:` line, or -1. Only a top-level (column 0) key counts: an
 *  indented one belongs to something else, and appending a second top-level key
 *  would silently shadow it. */
function findRendersAsLine(lines: string[]): number {
  return lines.findIndex((l) => /^renders_as\s*:/.test(l));
}

/**
 * Append new `renders_as` items to an existing output YAML's raw text, leaving
 * everything else (comments, identity, fixture, existing renders) untouched, and
 * report which lines were inserted (for the preview highlight).
 *
 * Deliberately textual rather than a YAML round-trip: the catalog files carry
 * comments, a schema header and hand-tuned formatting that a re-dump would
 * flatten. The cost is that a few legal shapes cannot be spliced safely — those
 * come back as `problem` rather than as silently mangled output.
 */
export function appendRenders(rawYaml: string, renders: RenderSpec[]): AppendResult {
  if (!renders.length) return { yaml: rawYaml, addedLines: [] };
  const crlf = /\r\n/.test(rawYaml);
  const source = crlf ? rawYaml.replace(/\r\n/g, '\n') : rawYaml;
  const eol = crlf ? '\r\n' : '\n';
  const done = (parts: string[], addedLines: number[]): AppendResult => {
    // `lines` carries a trailing '' from the final newline; drop any trailing
    // blanks so the file ends with exactly one newline.
    const trimmed = [...parts];
    while (trimmed.length && trimmed[trimmed.length - 1].trim() === '') trimmed.pop();
    return { yaml: trimmed.join(eol) + eol, addedLines };
  };
  const refuse = (problem: string): AppendResult => ({ yaml: rawYaml, addedLines: [], problem });

  const itemLines = renders.map((r) => indentBlock(renderToSnippet(r), 2)).join('\n').split('\n');
  const range = (start: number) => Array.from({ length: itemLines.length }, (_, i) => start + i);
  const lines = source.replace(/\n*$/, '\n').split('\n'); // trailing '' from the final \n
  const idx = findRendersAsLine(lines);

  if (idx === -1) {
    // Guard the nested case before treating "no key" as "append a fresh block":
    // a second top-level renders_as would win and drop the existing renders.
    if (lines.some((l) => /^\s+renders_as\s*:/.test(l))) {
      return refuse(
        'This file nests `renders_as` under another key. Appending a second top-level ' +
          '`renders_as` would silently replace the existing one, so edit the file by hand.',
      );
    }
    // No renders_as key at all: append a fresh block at EOF (drop the trailing '').
    const body = lines.slice(0, -1);
    return done([...body, 'renders_as:', ...itemLines], range(body.length + 1));
    // NB: addedLines is offset by the 'renders_as:' line we just inserted.
  }

  const keyLine = lines[idx];
  // `renders_as: []` — optionally followed by a comment, which the old anchored
  // regex missed, sending an empty list down the block path and splicing block
  // items straight after an inline sequence (invalid YAML).
  const emptyInline = keyLine.match(/^renders_as\s*:\s*\[\s*\](\s*#.*)?$/);
  if (emptyInline) {
    lines[idx] = `renders_as:${emptyInline[1] ?? ''}`;
    lines.splice(idx + 1, 0, ...itemLines);
    return done(lines, range(idx + 1));
  }
  // A non-empty FLOW sequence (`renders_as: [ {...}, ... ]`, possibly spanning
  // lines). Splicing block items into it produces invalid YAML, and matching
  // brackets properly here would mean writing a YAML parser.
  if (/^renders_as\s*:\s*\[/.test(keyLine)) {
    return refuse(
      'This file writes `renders_as` as a flow sequence (`[ … ]`). Converting it to block ' +
        'style is a judgement call about the file\'s formatting, so edit it by hand.',
    );
  }

  // Block style. Find the end: the first later line at column 0 that isn't blank
  // (a new top-level key or comment), else EOF; then back up over blank lines so
  // the new items sit right after the last existing item.
  let end = idx + 1;
  while (end < lines.length && (lines[end].trim() === '' || /^\s/.test(lines[end]))) end++;
  let insertAt = end;
  while (insertAt > idx + 1 && lines[insertAt - 1].trim() === '') insertAt--;
  lines.splice(insertAt, 0, ...itemLines);
  return done(lines, range(insertAt));
}

/** As {@link appendRenders} but returning only the merged YAML text. */
export function appendRendersToYaml(rawYaml: string, renders: RenderSpec[]): string {
  return appendRenders(rawYaml, renders).yaml;
}

export function genModuleYaml(tool: ToolMeta): string {
  const lines: string[] = [
    // Per-shape schema: catalog.schema.json describes a whole flat ENTRY
    // (`required: [id, name, outputs]`, extras forbidden), so pointing a
    // module.yaml at it made every schema-aware editor red-underline the file
    // the contributor had just generated.
    '# yaml-language-server: $schema=../module.schema.json',
    `id: ${flowScalar(tool.id)}`,
    `name: ${flowScalar(tool.name)}`,
  ];
  if (tool.description) lines.push(`description: ${flowScalar(tool.description)}`);
  if (tool.homepage) lines.push(`homepage: ${flowScalar(tool.homepage)}`);
  if (tool.source_url) lines.push(`source_url: ${flowScalar(tool.source_url)}`);
  if (tool.nf_core_url)
    lines.push(`nf_core_url: ${flowScalar(canonicalNfCoreUrl(tool.nf_core_url))}`);
  if (tool.biotools_url) lines.push(`biotools_url: ${flowScalar(tool.biotools_url)}`);
  return lines.join('\n') + '\n';
}

export function genOutputYaml(
  tool: ToolMeta,
  output: OutputMeta,
  fixtureFileName: string,
  renders: RenderSpec[],
): string {
  const lines: string[] = [
    '# yaml-language-server: $schema=../output.schema.json',
    `id: ${flowScalar(outputId(tool.id, output.slug))}`,
  ];
  if (output.description) lines.push(`description: ${flowScalar(output.description)}`);
  lines.push(`find: ${flowMap([['path_glob', output.path_glob]])}`);
  lines.push(`fixture: ${flowScalar(fixtureFileName)}`);
  lines.push('renders_as:');
  for (const r of renders) {
    const [first, ...rest] = renderItemLines(r);
    lines.push(`  - ${first}`);
    for (const l of rest) lines.push(`    ${l}`);
  }
  return lines.join('\n') + '\n';
}

export interface GeneratedEntry {
  toolId: string;
  outputSlug: string;
  moduleYaml: string;
  outputYaml: string;
  outputYamlName: string; // `<slug>.yaml`
  fixtureName: string;
  fixtureContent: string;
}

export function generateEntry(args: {
  tool: ToolMeta;
  output: OutputMeta;
  fixtureFileName: string;
  fixtureContent: string;
  renders: RenderSpec[];
}): GeneratedEntry {
  const { tool, output, fixtureFileName, fixtureContent, renders } = args;
  return {
    toolId: tool.id,
    outputSlug: output.slug,
    moduleYaml: genModuleYaml(tool),
    outputYaml: genOutputYaml(tool, output, fixtureFileName, renders),
    outputYamlName: `${output.slug}.yaml`,
    fixtureName: fixtureFileName,
    fixtureContent,
  };
}
