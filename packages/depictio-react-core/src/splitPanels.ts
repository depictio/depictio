/**
 * Small multiples, as a partition of rows rather than a property of any chart.
 *
 * A split is one idea: cut the rows into named subsets and draw the whole
 * component once per subset. Nothing in that sentence mentions what is being
 * drawn, which is why it works for a sunburst and an UpSet as readily as for a
 * scatter — the renderer is asked for nothing, it is simply built again against
 * less data.
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

import type { InteractiveFilter } from './api';
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
