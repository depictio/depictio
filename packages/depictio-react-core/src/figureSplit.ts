import { MAX_PANELS } from './splitPanels';

/**
 * Chart types the server cannot cut into one panel per group: Plotly Express
 * gives them no `facet_col` (pie, hierarchies, polar, ternary, 3D, tile maps,
 * scatter matrix, parallel plots), or the group override never touches them
 * (the whole-frame types, `_WHOLE_FRAME_VISU` server-side). Split draws them
 * once per group instead, each from that group's rows.
 */
const FACETLESS_VISU = new Set([
  'pie', 'sunburst', 'treemap', 'icicle', 'funnel_area',
  'bar_polar', 'line_polar', 'scatter_polar', 'line_ternary', 'scatter_ternary',
  'scatter_3d', 'line_3d', 'scatter_map', 'scatter_mapbox', 'line_map', 'line_mapbox',
  'density_map', 'density_mapbox', 'choropleth_map', 'choropleth_mapbox',
  'scatter_matrix', 'parallel_coordinates', 'parallel_categories',
  'heatmap', 'imshow', 'scatter_geo', 'choropleth',
]);

const NAMES_GROUPS = /depictio_group|__depictio_group__/;

type FigureDefinition = Record<string, unknown> & {
  mode?: unknown;
  code_content?: unknown;
  visu_type?: unknown;
};

/**
 * Whether Split draws this figure once per panel rather than asking the server
 * to facet it (#1476).
 *
 * - A code figure that never names the groups: the server never rewrites code,
 *   so its split is the whole figure per group. One that spreads
 *   `depictio_group_kwargs` places the groups itself and is trusted.
 * - A chart type that cannot facet, known up front.
 * - Any other UI figure the server answered `group_split: false` for: it was
 *   grouped but came out whole.
 */
export function drawnOncePerPanel(
  definition: FigureDefinition,
  groupSplit?: boolean | null,
): boolean {
  if (definition.mode === 'code') return !NAMES_GROUPS.test(String(definition.code_content ?? ''));
  if (FACETLESS_VISU.has(String(definition.visu_type ?? '').toLowerCase())) return true;
  return groupSplit === false;
}

/** Enough panels to split on, and few enough to read. The "what's new" split
 *  (`keepColor`) keeps its earlier rule: any panel at all. */
export function splitPanelsUsable(count: number, keepColor: boolean): boolean {
  return keepColor ? count > 0 : count > 1 && count <= MAX_PANELS;
}
