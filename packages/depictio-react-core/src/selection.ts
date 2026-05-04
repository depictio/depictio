/**
 * Helpers for chart/table/map selection-as-filter wiring.
 *
 * The Dash viewer stores selections in ``interactive-values-store`` with a
 * ``source`` discriminator (``scatter_selection`` / ``table_selection`` /
 * ``map_selection``) so passive components can merge them alongside regular
 * interactive filters. The React viewer mirrors that protocol via
 * ``InteractiveFilter.source`` and uses the helpers below to extract values
 * from Plotly/AG Grid events and to merge / clear by ``(index, source)``.
 */

import type { InteractiveFilter, InteractiveFilterSource } from './api';

/**
 * Pick selection values from a Plotly ``selectedData`` / ``clickData`` event.
 * Mirrors ``extract_scatter_selection_values`` in
 * ``depictio/dash/modules/figure_component/callbacks/selection.py``.
 *
 * Plotly puts the original row identifier into ``customdata`` (an array of
 * arrays). ``selectionColumnIndex`` is the offset within each customdata row
 * that holds the value to filter on.
 */
export function extractScatterSelection(
  eventData: { points?: Array<{ customdata?: unknown }> } | null | undefined,
  selectionColumnIndex: number,
): string[] {
  if (!eventData || !eventData.points || eventData.points.length === 0) return [];

  const out: string[] = [];
  const seen = new Set<string>();
  for (const pt of eventData.points) {
    const cd = pt?.customdata;
    // Plotly may deliver per-point customdata as a plain Array, OR — when the
    // trace was built with the typed-array transport (``{dtype, bdata, shape}``)
    // and expanded by ``_fullData`` — as an object with numeric keys (``{0: 1}``).
    // Both cases support ``cd[i]`` lookup, so we just guard against scalars/null.
    if (cd == null || (typeof cd !== 'object')) continue;
    const raw = (cd as Record<number, unknown>)[selectionColumnIndex];
    if (raw === null || raw === undefined) continue;
    const v = String(raw);
    if (seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

/**
 * Pick selection values from AG Grid's selected rows. Mirrors
 * ``extract_row_selection_values`` in
 * ``depictio/dash/modules/table_component/callbacks/selection.py``.
 */
export function extractRowSelection(
  selectedRows: Array<Record<string, unknown>> | null | undefined,
  selectionColumn: string,
): string[] {
  if (!selectedRows || selectedRows.length === 0) return [];

  const out: string[] = [];
  const seen = new Set<string>();
  for (const row of selectedRows) {
    const raw = row?.[selectionColumn];
    if (raw === null || raw === undefined) continue;
    const v = String(raw);
    if (seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

/**
 * Add or replace a filter, deduping by ``(index, source)``.
 *
 * Regular interactive components have ``source === undefined`` and are keyed
 * by ``index`` alone. Selection sources (scatter/table/map) coexist with the
 * same ``index`` because a chart can both be filtered as a passive component
 * AND emit a selection — so we key by the tuple.
 *
 * Passing ``value === null | undefined | []`` clears the matching entry.
 */
export function mergeFiltersBySource(
  filters: InteractiveFilter[],
  next: InteractiveFilter,
): InteractiveFilter[] {
  const matches = (f: InteractiveFilter) =>
    f.index === next.index && (f.source ?? null) === (next.source ?? null);

  const cleared =
    next.value === null ||
    next.value === undefined ||
    (Array.isArray(next.value) && next.value.length === 0);

  if (cleared) return filters.filter((f) => !matches(f));

  const without = filters.filter((f) => !matches(f));
  return [...without, next];
}

/**
 * Remove every filter with the given ``source``. Pass ``index`` to scope to a
 * single component (e.g. clearing one chart's lasso without touching others).
 */
export function clearFiltersBySource(
  filters: InteractiveFilter[],
  source: InteractiveFilterSource,
  index?: string,
): InteractiveFilter[] {
  return filters.filter((f) => {
    if (f.source !== source) return true;
    if (index !== undefined && f.index !== index) return true;
    return false;
  });
}

/**
 * True when at least one filter in the list comes from a selection event
 * (used to surface a "Clear all selections" affordance in the sidebar).
 */
export function hasSelectionFilters(filters: InteractiveFilter[]): boolean {
  return filters.some((f) => f.source !== undefined);
}
