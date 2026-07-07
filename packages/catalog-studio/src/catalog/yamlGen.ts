/**
 * Generate the on-disk catalog files for a tool entry, matching the format the
 * loader (`_load_tool_dir`) + Pydantic models expect and the aesthetic of the
 * committed examples (flow-style `renders_as` items, `# yaml-language-server`
 * header). `columns` is deliberately OMITTED — the exported fixture grounds the
 * bindings in CI (schema-ownership rule: fixture present ⇒ grounding deferred).
 */
import type { OutputMeta, RenderSpec, ToolMeta } from '../types';

/** True if a scalar can be emitted plain (no quotes) in YAML flow context. */
function isPlainSafe(s: string): boolean {
  // Letters/digits/_-./: — enough to keep URLs (https://…) unquoted while still
  // quoting spaced names and globs (`*`). No `: ` (colon-space) can occur since
  // spaces aren't allowed, so this is safe in both block and flow contexts.
  return /^[A-Za-z0-9_][A-Za-z0-9_.\-/:]*$/.test(s);
}

/** Serialize a scalar for a YAML flow mapping value. */
function flowScalar(v: string): string {
  if (isPlainSafe(v)) return v;
  return JSON.stringify(v); // valid YAML double-quoted string
}

/** `{k1: v1, k2: v2}` flow mapping from ordered [key, value] pairs. */
function flowMap(pairs: [string, string][]): string {
  return `{${pairs.map(([k, v]) => `${k}: ${flowScalar(v)}`).join(', ')}}`;
}

/** One `renders_as` list item as a compact flow mapping. */
export function renderToFlow(render: RenderSpec): string {
  if (render.component === 'figure') {
    const kwargs = flowMap(Object.entries(render.dict_kwargs).map(([k, v]) => [k, v]));
    return `{ component: figure, visu_type: ${render.visu_type}, dict_kwargs: ${kwargs} }`;
  }
  if (render.component === 'card') {
    return `{ component: card, column: ${flowScalar(render.column)}, aggregation: ${render.aggregation} }`;
  }
  if (render.component === 'table') {
    return `{ component: table }`;
  }
  // advanced_viz
  const roles = flowMap(Object.entries(render.roles).map(([k, v]) => [k, v]));
  return `{ component: advanced_viz, kind: ${render.kind}, roles: ${roles} }`;
}

/** The output id derived from tool + output slug (e.g. `mosdepth_coverage`). */
export function outputId(toolId: string, slug: string): string {
  return `${toolId}_${slug}`;
}

export function genModuleYaml(tool: ToolMeta): string {
  const lines: string[] = [
    '# yaml-language-server: $schema=../catalog.schema.json',
    `id: ${flowScalar(tool.id)}`,
    `name: ${flowScalar(tool.name)}`,
  ];
  if (tool.description) lines.push(`description: ${flowScalar(tool.description)}`);
  if (tool.homepage) lines.push(`homepage: ${flowScalar(tool.homepage)}`);
  if (tool.nf_core_url) lines.push(`nf_core_url: ${flowScalar(tool.nf_core_url)}`);
  if (tool.biotools_url) lines.push(`biotools_url: ${flowScalar(tool.biotools_url)}`);
  return lines.join('\n') + '\n';
}

export function genOutputYaml(
  tool: ToolMeta,
  output: OutputMeta,
  fixtureFileName: string,
  renders: RenderSpec[],
): string {
  const lines: string[] = [`id: ${flowScalar(outputId(tool.id, output.slug))}`];
  if (output.description) lines.push(`description: ${flowScalar(output.description)}`);
  lines.push(`find: ${flowMap([['path_glob', output.path_glob]])}`);
  lines.push(`fixture: ${flowScalar(fixtureFileName)}`);
  lines.push('renders_as:');
  for (const r of renders) {
    lines.push(`  - ${renderToFlow(r)}`);
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
