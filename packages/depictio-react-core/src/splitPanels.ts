/**
 * Small multiples, as a partition of rows rather than a property of any chart.
 *
 * A split is one idea: cut the rows into named subsets and draw the whole
 * component once per subset. Nothing in that sentence mentions what is being
 * drawn, which is why it works for a sunburst as readily as for a QQ plot:
 * the renderer is asked for nothing, it is simply built again against less
 * data. Whether a given kind *should* be split is a separate question, answered
 * per kind by `groupingModeForKind` at the end of this file.
 *
 * Every subset is expressed as extra `InteractiveFilter` entries appended to
 * the dashboard's own. That is the whole generalisation: because a cell is a
 * *list* of constraints and not a single "facet column", splitting by two
 * dimensions is the concatenation of two constraint lists, and splitting by
 * three is three. `crossPanels` is therefore about ten lines, and the wrapper
 * that renders panels never learns how many dimensions produced them.
 *
 * Riding on filters also means each panel goes through the ordinary fetch
 * path: server-side predicate building, cross-DC link resolution and the load
 * cache all apply, so a subset defined on one collection can narrow a
 * component reading another.
 */

import type { AdvancedVizKind, InteractiveFilter } from './api';
import { GROUP_FILTER_INDEX_PREFIX, GROUP_FILTER_SOURCE } from './selectionGroups';
import type { GroupRenderDef, GroupRenderState } from './selectionGroups';

/** One cell of a split: what to call it, and what to add to the filters. */
export interface PanelSpec {
  name: string;
  /** Tint for the panel's label. Absent means "use the default text colour". */
  color?: string;
  /** Constraints for this cell alone, appended to the dashboard's filters. */
  constraints: InteractiveFilter[];
}

/** A value constraint in the shape the group projection already uses, so the
 *  server treats a panel exactly as it treats an active group filter. */
function valueConstraint(
  key: string,
  columnName: string,
  values: string[],
  dcId?: string,
): InteractiveFilter {
  return {
    index: `${GROUP_FILTER_INDEX_PREFIX}panel:${key}`,
    value: values,
    column_name: columnName,
    interactive_component_type: 'MultiSelect',
    source: GROUP_FILTER_SOURCE,
    metadata: {
      dc_id: dcId,
      column_name: columnName,
      interactive_component_type: 'MultiSelect',
    },
  };
}

/** One panel per analysis group.
 *
 *  There is no "Other" panel: a MultiSelect projects `is_in`, and "in none of
 *  these groups" is not expressible that way. */
export function panelsFromGroups(groups: GroupRenderDef[]): PanelSpec[] {
  return groups
    .filter((g) => (g.values ?? []).length > 0)
    .map((g) => ({
      name: g.name,
      color: g.color,
      constraints: [valueConstraint(g.name, g.column_name, g.values, g.dc_id)],
    }));
}

/** One panel per distinct value of a column — the other half of the "Color by"
 *  control, where the dimension is a real column rather than saved groups. */
export function panelsFromColumnValues(
  columnName: string,
  values: string[],
  colorMap?: Record<string, string>,
  dcId?: string,
): PanelSpec[] {
  return values.map((value) => ({
    name: value,
    color: colorMap?.[value],
    constraints: [valueConstraint(`${columnName}=${value}`, columnName, [value], dcId)],
  }));
}

/**
 * Two dimensions at once: every combination of a cell from each.
 *
 * The constraints simply concatenate, because a filter list is already a
 * conjunction. Nothing downstream needs to know the panels came from two
 * sources rather than one.
 */
export function crossPanels(rows: PanelSpec[], columns: PanelSpec[]): PanelSpec[] {
  if (rows.length === 0) return columns;
  if (columns.length === 0) return rows;
  const out: PanelSpec[] = [];
  for (const row of rows) {
    for (const column of columns) {
      out.push({
        name: `${row.name} · ${column.name}`,
        color: row.color ?? column.color,
        constraints: [...row.constraints, ...column.constraints],
      });
    }
  }
  return out;
}

/** The dashboard's filters plus one cell's constraints. */
export function panelFilters(base: InteractiveFilter[], panel: PanelSpec): InteractiveFilter[] {
  return [...base, ...panel.constraints];
}

/**
 * The cells the dashboard's "Color by … / Split" control is asking for.
 *
 * The two halves of that control are two partitions of the same kind: saved
 * groups are value sets on a column, a categorical column is its own values.
 * Resolving both here is what lets one wrapper serve both, and what leaves
 * room for a second dimension later — `crossPanels` takes it from here without
 * anything downstream changing.
 */
/** The values a categorical control pins `columnName` to, or `null` when
 *  nothing in `filters` narrows that column to a named set. Ranges, free text
 *  and empty selections all answer `null`: they scope rows without naming
 *  which values survive, so they cannot say what the cells should be. */
function pinnedValues(
  columnName: string,
  filters: readonly InteractiveFilter[],
): Set<string> | null {
  const pinned = new Set<string>();
  for (const filter of filters) {
    if ((filter.column_name ?? filter.metadata?.column_name) !== columnName) continue;
    const kind = filter.interactive_component_type ?? filter.metadata?.interactive_component_type;
    if (kind !== 'MultiSelect' && kind !== 'Select' && kind !== 'SegmentedControl') continue;
    const raw = filter.value;
    for (const value of Array.isArray(raw) ? raw : [raw]) {
      if (typeof value === 'string' || typeof value === 'number') pinned.add(String(value));
    }
  }
  return pinned.size > 0 ? pinned : null;
}

export function panelsForGrouping(
  groupRender: GroupRenderState | undefined,
  filters: readonly InteractiveFilter[] = [],
): PanelSpec[] {
  if (!groupRender || groupRender.display !== 'facet') return [];
  if (groupRender.colorByGroup) return panelsFromGroups(groupRender.groups ?? []);
  const column = groupRender.colorByColumn;
  // A column split needs its value set up front, and the palette the dashboard
  // computed from the column's unfiltered universe is exactly that.
  if (!column?.colorMap) return [];
  const universe = Object.keys(column.colorMap);
  if (universe.length === 0) return [];
  // A filter on that same column is the user naming the cells they want, so a
  // column with more values than a grid can hold becomes splittable by being
  // narrowed first rather than being refused outright. Colours still come from
  // the unfiltered palette, so a value keeps its tint however far you narrow.
  const pinned = pinnedValues(column.columnName, filters);
  const values = pinned ? universe.filter((value) => pinned.has(value)) : universe;
  // An empty intersection means the filter names values this palette never saw,
  // which is a different column wearing the same name. Split on nothing.
  if (values.length === 0) return [];
  return panelsFromColumnValues(column.columnName, values, column.colorMap);
}

/** Above this many groups the split is refused and the component renders whole.
 *  One fetch per panel, and small multiples stop being legible well before
 *  this. Deliberately well under the server's `MAX_FACET_CATEGORIES` (12),
 *  which faces a single query rather than one per panel. */
export const MAX_PANELS = 6;

/** What a chart type does when the dashboard asks to split by groups: deal
 *  itself into panels, colour its marks by group in one panel, or neither. */
export type GroupingMode = 'split' | 'colour' | 'none';

/**
 * The split policy, per kind.
 *
 * Keyed on the kind rather than on anything the rows could reveal, because the
 * answer is about what the chart means, not about what it was fed. Typed over
 * every kind the client knows, so a new kind does not compile until someone
 * has placed it.
 */
export const GROUPING_MODE_BY_KIND: Readonly<Record<AdvancedVizKind, GroupingMode>> = {
  // Split. A group is a subset of the rows the chart summarises, so the chart
  // rebuilt from each subset is a real answer, and side by side is how those
  // distributions are compared.
  qq: 'split',
  rarefaction: 'split',
  coverage_track: 'split',
  stacked_taxonomy: 'split',
  sunburst: 'split',
  sankey: 'split',
  oncoplot: 'split',
  signal_matrix: 'split',

  // Colour in one panel. The marks share one coordinate space, and panels cost
  // the comparison the chart exists for: an ordination rebuilt per group is a
  // different ordination with incomparable axes, a Manhattan loses its
  // genome-wide axis. Drawn whole these also keep their selection tool, which
  // read-only panels drop, and they are where groups are drawn in the first
  // place. Each renderer colours by group itself.
  embedding: 'colour',
  manhattan: 'colour',
  scatter_xy: 'colour',
  profile: 'colour',
  volcano: 'colour',
  ma: 'colour',
  lollipop: 'colour',
  da_barplot: 'colour',
  metric_ci_bars: 'colour',

  // Neither. Either the rows are not samples a group can name (terms, truth-set
  // results, one locus's structure), or a subset re-derives the layout itself
  // (a tree, a clustered matrix, set intersections), so panels would not be
  // comparable. Drawn whole and badged, so the tile does not pass for one that
  // honoured the split. Whatever they already do with filters is untouched.
  phylogenetic: 'none',
  complex_heatmap: 'none',
  dot_plot: 'none',
  upset_plot: 'none',
  enrichment: 'none',
  pr_benchmark: 'none',
  roc_pr_curve: 'none',
  confusion_matrix: 'none',
  fusion_structure: 'none',
  gene_arrow_track: 'none',
  gsea_running_score: 'none',
  sashimi: 'none',
  // A binned matrix re-derived per group would rebuild its own bins and axes,
  // same bucket as complex_heatmap. Neither renderer takes a `groupRender`
  // prop (no selection/grouping wiring; see the kind's renderer docstring).
  contact_map: 'none',
  knee_plot: 'none',
  damage_profile: 'none',
  // Same genome-wide axis as the Manhattan, so splitting is out for the same
  // reason; the genome view colours by chromosome or by its category column
  // and does not take the dashboard's groups, so it is honest about doing
  // neither.
  genome_view: 'none',
  // Computed on demand between two groups: the groups are the input, not a
  // split to apply on top.
  group_compare: 'none',
  // One gene's lanes, a segment profile and a chord ring each read as one
  // figure; per-group copies would not share an axis worth comparing.
  transcript_structure: 'none',
  cnv_profile: 'none',
  genome_chord: 'none',
  // One row read as text: there is no mark for a group to colour and no
  // distribution for a panel to re-derive.
  record_card: 'none',
  // Every polyline already stands for one sample, and the axes are shared, so
  // splitting would redraw the same axes beside each other; the kind colours by
  // its own `group_col` rather than taking the dashboard's groups.
  parallel_coordinates: 'none',
};

/** The policy for `vizKind`.
 *
 *  A kind missing from the map (one the server knows and this client does not
 *  yet) is split, which is what every kind did before the policy existed: a
 *  new chart keeps the generic behaviour until someone decides otherwise.
 *  `ancombc_differentials` is the legacy name of `da_barplot`, still carried by
 *  dashboards saved before the two were merged. */
export function groupingModeForKind(vizKind: string): GroupingMode {
  const kind = vizKind === 'ancombc_differentials' ? 'da_barplot' : vizKind;
  return Object.prototype.hasOwnProperty.call(GROUPING_MODE_BY_KIND, kind)
    ? GROUPING_MODE_BY_KIND[kind as AdvancedVizKind]
    : 'split';
}

/** Whether the dashboard is asking for this split, the kind takes it, and it
 *  is small enough to honour. Read by the dispatch before it decides how to
 *  render. */
export function shouldSplitIntoPanels(panels: PanelSpec[], vizKind: string): boolean {
  if (groupingModeForKind(vizKind) !== 'split') return false;
  return panels.length > 1 && panels.length <= MAX_PANELS;
}
