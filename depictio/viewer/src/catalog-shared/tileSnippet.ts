/**
 * The dashboard-YAML block that reproduces one catalog render.
 *
 * Both catalog surfaces used to hand out `use: <tool>/<render>` on its own. That
 * line is not a tile: a tile is resolved against a workflow and a data
 * collection, so pasted into a dashboard YAML the snippet bound to nothing. And
 * it was offered for `advanced_viz` only, which read as "the others cannot be
 * referenced" — they can. The difference is what `use:` *does*:
 *
 *   - `advanced_viz` — `use:` EXPANDS. `_expand_catalog_use` resolves it to the
 *     render's `viz_kind` + `config`, so the three keys below are the whole tile.
 *   - everything else — `use:` is PROVENANCE. `LiteComponent` derives
 *     `catalog_source` from it (models/models/dashboards.py), but the component's
 *     own configuration still has to be spelled out. So we spell it out, from the
 *     same `renders_as` entry the preview just drew.
 *
 * Emitting the same block on both surfaces is also what makes them one catalog
 * rather than two: the docs page and the picker now answer "how do I get this?"
 * with the identical text.
 */
import type { CatalogRender } from 'depictio-react-core';

/** Stand-ins used when there is no project in context — the docs gallery has no
 *  workflow and no ingested collection, and a placeholder that is obviously a
 *  placeholder beats a plausible-looking wrong tag. */
export const WF_PLACEHOLDER = '<your-workflow-tag>';
export const DC_PLACEHOLDER = '<your-data-collection-tag>';

export interface TileSnippetContext {
  toolId: string;
  outputId: string;
  /** Ingested collection tag; omitted in the docs gallery. */
  dcTag?: string | null;
  /** Workflow tag; omitted in the docs gallery. */
  wfTag?: string | null;
  /** Human title for the tile. */
  title?: string | null;
}

/** Drop the redundant `<tool>_` prefix an output id carries inside its tool. */
function outputShort(outputId: string, toolId: string): string {
  return outputId.startsWith(`${toolId}_`) ? outputId.slice(toolId.length + 1) : outputId;
}

/** `<tool>/<render-id or output>` — the handle `use:` takes.
 *
 *  A render id is tool-unique and points at one render; without one the handle
 *  falls back to the output, which is what a card or a table references anyway
 *  (they carry their own config, so there is nothing finer to point at). */
export function catalogUseRef(
  toolId: string,
  outputId: string,
  render: CatalogRender,
): string {
  return `${toolId}/${render.id || outputShort(outputId, toolId)}`;
}

/** Minimal YAML for a scalar. Quotes only when the value would otherwise parse
 *  as something else, so the common case stays readable. */
function scalar(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean' || typeof value === 'number') return String(value);
  const s = String(value);
  if (s === '') return "''";
  if (/^[\w./|@+-]+$/.test(s) && !/^[-+.]?\d/.test(s)) return s;
  return JSON.stringify(s);
}

function line(key: string, value: unknown, indent: string): string {
  return `${indent}${key}: ${scalar(value)}`;
}

/** The component-specific half of the tile. */
function configLines(render: CatalogRender, indent: string): string[] {
  const out: string[] = [];
  const push = (k: string, v: unknown) => {
    if (v !== undefined && v !== null && !(Array.isArray(v) && v.length === 0)) {
      out.push(line(k, v, indent));
    }
  };

  switch (render.component) {
    case 'advanced_viz':
      // `use:` expands into viz_kind + config. Nothing to add.
      break;
    case 'card':
      push('column_name', render.column ?? render.column_name);
      push('aggregation', render.aggregation);
      if (render.aggregations?.length) {
        out.push(`${indent}aggregations: [${render.aggregations.map(scalar).join(', ')}]`);
      }
      push('secondary_layout', render.secondary_layout);
      push('breakdown_col', render.breakdown_col);
      push('top_n_count', render.top_n_count);
      push('coverage_max', render.coverage_max);
      push('threshold_value', render.threshold_value);
      push('threshold_direction', render.threshold_direction);
      push('threshold_warn', render.threshold_warn);
      push('trend_col', render.trend_col);
      if (render.attrition_cols?.length) {
        out.push(`${indent}attrition_cols: [${render.attrition_cols.map(scalar).join(', ')}]`);
      }
      break;
    case 'figure':
      if (render.code) {
        out.push(line('mode', 'code', indent));
        push('visu_type', render.visu_type);
        // The snippet stays a reference, not a transcript: a code figure's body
        // is tens of lines and lives in the catalog recipe, which the panel
        // links to. Inlining it here would bury the three lines that matter.
        out.push(`${indent}code_content: |`);
        out.push(`${indent}  # see depictio/catalog/${'${tool}'}/ for this render's code`);
      } else {
        push('visu_type', render.visu_type ?? 'scatter');
        const kwargs = render.dict_kwargs || {};
        const keys = Object.keys(kwargs);
        if (keys.length) {
          out.push(`${indent}dict_kwargs:`);
          for (const k of keys) out.push(line(k, kwargs[k], `${indent}  `));
        }
      }
      break;
    case 'table':
      push('row_selection_enabled', render.row_selection_enabled);
      push('row_selection_column', render.row_selection_column);
      push('page_size', render.page_size);
      break;
    case 'multiqc':
      // The module the render surfaces. The plot within it is resolved from the
      // ingested report, so a dashboard that omits `selected_plot` gets the
      // module's first renderable plot.
      push('selected_module', render.section);
      break;
    case 'interactive':
      push('interactive_type', render.interactive_type);
      push('column_name', render.column_name ?? render.column);
      break;
    default:
      break;
  }
  return out;
}

/** The full tile block, ready to paste under a dashboard's `components:`. */
export function buildTileSnippet(ctx: TileSnippetContext, render: CatalogRender): string {
  const indent = '  ';
  const lines = [
    `- component_type: ${render.component}`,
    line('workflow_tag', ctx.wfTag || WF_PLACEHOLDER, indent),
    line('data_collection_tag', ctx.dcTag || DC_PLACEHOLDER, indent),
    line('use', catalogUseRef(ctx.toolId, ctx.outputId, render), indent),
  ];
  lines.push(...configLines(render, indent));
  if (ctx.title) lines.push(line('title', ctx.title, indent));
  return lines
    .join('\n')
    .replace('${tool}', ctx.toolId);
}

/** True when the snippet still carries placeholders the reader must replace. */
export function snippetNeedsBinding(ctx: TileSnippetContext): boolean {
  return !ctx.wfTag || !ctx.dcTag;
}
