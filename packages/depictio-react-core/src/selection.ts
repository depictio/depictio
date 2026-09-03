/**
 * Helpers for chart/table/map selection-as-filter wiring.
 *
 * The Dash viewer stores selections in ``interactive-values-store`` with a
 * ``source`` discriminator (``scatter_selection`` / ``table_selection`` /
 * ``map_selection`` / ``tree_selection``) so passive components can merge them
 * alongside regular interactive filters. The React viewer mirrors that protocol via
 * ``InteractiveFilter.source`` and uses the helpers below to extract values
 * from Plotly/AG Grid events and to merge / clear by ``(index, source)``.
 */

import type { InteractiveFilter, InteractiveFilterSource, StoredMetadata } from './api';

/**
 * Values a given map currently has selected, read back out of the filter list.
 *
 * A map's own selection is stripped before it fetches (it must keep showing
 * every point), so the filter list is the only record of what is selected. The
 * map re-derives it from here to repaint the highlight — which matters most
 * after a tab switch, where the map remounts from scratch while the selection
 * it made is still filtering the rest of the dashboard.
 */
export function mapSelectionValues(
  filters: InteractiveFilter[],
  componentIndex: string,
): string[] {
  for (const f of filters) {
    if (f.index !== componentIndex || f.source !== 'map_selection') continue;
    if (Array.isArray(f.value)) return f.value.map((v) => String(v));
  }
  return [];
}

/**
 * The filter entry a map emits for a set of selected values.
 *
 * Shared so that every way of selecting on a map — lassoing points, clicking
 * one, ticking rows in its underlying-data table — produces the *same* entry.
 * They are all one selection: they land on the same `(index, 'map_selection')`
 * key, so whichever was used last replaces the others, and the map's highlight
 * reads back out of it. Passing `[]` clears.
 */
export function mapSelectionFilter(
  metadata: StoredMetadata,
  values: string[],
): InteractiveFilter {
  const selectionColumn =
    typeof metadata.selection_column === 'string'
      ? (metadata.selection_column as string)
      : undefined;
  return {
    index: metadata.index,
    value: values,
    source: 'map_selection',
    column_name: selectionColumn,
    interactive_component_type: 'MultiSelect',
    metadata: {
      dc_id: metadata.dc_id,
      column_name: selectionColumn,
      interactive_component_type: 'MultiSelect',
      selection_column: selectionColumn,
    },
  };
}

/**
 * Whether a map should emit selections at all.
 *
 * Choropleth is excluded because its shapes are non-point geometries that
 * Plotly's selection events don't cover. `hasHandler` folds in the caller's own
 * "is anyone listening" check, so read-only hosts light up no lasso affordance.
 */
export function isMapSelectionEnabled(metadata: StoredMetadata, hasHandler: boolean): boolean {
  return (
    Boolean(metadata.selection_enabled) &&
    (metadata.map_type as string) !== 'choropleth_map' &&
    hasHandler
  );
}

/**
 * The DC column an advanced_viz component emits its selection on, or
 * `undefined` when it cannot emit one at all.
 *
 * Only two viz kinds draw one marker per source row and therefore have a
 * per-row identity to select on; every other kind aggregates (bins, taxa,
 * intersections) and would emit an envelope pointing at nothing. Both are
 * opt-in per component, so a shipped dashboard keeps the drag behaviour it has
 * today until its YAML asks for the lasso.
 *
 * Embedding falls back to `sample_id_col` because that is already the value it
 * writes into every point's customdata. Manhattan has no defensible fallback:
 * one point there is a row of a long variant table keyed by (sample,
 * chromosome, position), so selecting on the sample column and selecting on a
 * per-variant label are two different questions and only the dashboard knows
 * which one it is asking.
 *
 * This is the single source of truth for the capability: the two renderers
 * gate their Plotly handlers on it and `supportsSelectionGrouping` gates the
 * chrome's marker on it, so the affordance and the behaviour cannot disagree.
 */
export function advancedVizSelectionColumn(metadata: StoredMetadata): string | undefined {
  const config = (metadata.config ?? {}) as Record<string, unknown>;
  if (config.selection_enabled !== true) return undefined;
  const named =
    typeof config.selection_column === 'string' && config.selection_column
      ? config.selection_column
      : undefined;
  switch (typeof metadata.viz_kind === 'string' ? metadata.viz_kind : '') {
    case 'embedding': {
      const sampleIdCol =
        typeof config.sample_id_col === 'string' && config.sample_id_col
          ? config.sample_id_col
          : undefined;
      return named ?? sampleIdCol;
    }
    case 'manhattan':
      return named;
    default:
      return undefined;
  }
}

/**
 * The filter entry an advanced_viz renderer emits for a set of selected
 * values, in the same `scatter_selection` shape FigureRenderer produces.
 *
 * Deliberately not a source of its own (the phylogeny's `tree_selection` is,
 * and that is exactly why its selections cross-filter but can never become an
 * analysis group: `SELECTION_SOURCES` in selectionGroups.ts does not list it).
 * Reusing `scatter_selection` means these renderers reach the Analysis panel
 * through the path scatter figures already use. Passing `[]` clears.
 */
export function advancedVizSelectionFilter(
  metadata: StoredMetadata,
  selectionColumn: string,
  values: string[],
): InteractiveFilter {
  return {
    index: metadata.index,
    value: values,
    source: 'scatter_selection',
    column_name: selectionColumn,
    interactive_component_type: 'MultiSelect',
    metadata: {
      dc_id: metadata.dc_id,
      column_name: selectionColumn,
      interactive_component_type: 'MultiSelect',
      selection_column: selectionColumn,
    },
  };
}

/**
 * The filter list a selection-source component should render against: every
 * dashboard filter *except* the one it emitted itself.
 *
 * A component that filtered on its own selection would only ever draw the rows
 * it already picked, so the selection could never be widened again. It keeps
 * every row and dims the excluded ones instead.
 */
export function filtersExcludingOwn(
  filters: InteractiveFilter[],
  componentIndex: string,
  source: InteractiveFilterSource,
): InteractiveFilter[] {
  return filters.filter((f) => !(f.index === componentIndex && f.source === source));
}

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

/**
 * Enrich an emitted filter with its source component's ``dc_id`` (looked up
 * from the dashboard's ``stored_metadata`` by index) so the backend's
 * link-resolver can map cross-DC filters. Interactive renderers don't carry
 * their own dc_id in the emitted shape — this lookup is the single source of
 * truth for the view and editor apps. Returns the update unchanged when a
 * dc_id is already present or no matching source can be found.
 */
export function enrichFilterWithDcId(
  update: InteractiveFilter,
  storedMetadata: StoredMetadata[] | undefined,
): InteractiveFilter {
  if (update.metadata?.dc_id) return update;
  const src = (storedMetadata ?? []).find((m) => String(m.index) === String(update.index));
  const dcId = src?.dc_id;
  if (!dcId) return update;
  return {
    ...update,
    metadata: {
      ...(update.metadata ?? {}),
      dc_id: dcId,
      column_name: update.column_name ?? update.metadata?.column_name,
      interactive_component_type:
        update.interactive_component_type ?? update.metadata?.interactive_component_type,
    },
  };
}

/**
 * Whether this component can produce a selection that becomes an analysis
 * group ("select & compare", issue #89).
 *
 * One predicate for all four selection sources, so the capability marker the
 * chrome draws and the gates the renderers use can never disagree about what
 * is selectable. Each arm mirrors its renderer's own enable check:
 *
 * - `figure` — only scatter / scatter_3d carry the per-row customdata a
 *   meaningful selection needs; aggregated visus emit per-bin envelopes.
 * - `table`  — row selection is opt-in per component.
 * - `map`    — see `isMapSelectionEnabled` (choropleth is excluded).
 * - `image`  — a gallery selects thumbnails, which requires an image column.
 * - `advanced_viz`: see `advancedVizSelectionColumn`, i.e. the embedding and
 *   Manhattan scatters, each opt-in and each needing a resolvable column.
 *
 * `hasHandler` folds in the caller's "is anyone listening" check, so read-only
 * hosts (catalog, project previews) advertise nothing.
 */
export function supportsSelectionGrouping(
  metadata: StoredMetadata,
  hasHandler: boolean,
): boolean {
  if (!hasHandler) return false;
  switch (metadata.component_type) {
    case 'figure':
      return (
        Boolean(metadata.selection_enabled) &&
        (metadata.visu_type === 'scatter' || metadata.visu_type === 'scatter_3d')
      );
    case 'table':
      return Boolean(metadata.row_selection_enabled);
    case 'map':
      return isMapSelectionEnabled(metadata, true);
    case 'image':
      return Boolean(metadata.image_column);
    case 'advanced_viz':
      return advancedVizSelectionColumn(metadata) !== undefined;
    default:
      return false;
  }
}

/**
 * Apply an AI plan (widget updates + expression filters) on top of the
 * current filter list, first undoing whatever the PREVIOUS plan did.
 *
 * AI `set_widget` updates merge as regular widget entries (no `source`),
 * so replacing a plan cannot rely on `clearFiltersBySource` alone: a
 * widget the old plan set and the new plan ignores would silently keep
 * the old value. The `previouslyTouched` map (widget index → the entry it
 * had before the old plan, or null if it had none) is what lets the new
 * apply restore that ground state before layering its own updates.
 *
 * Returns the next filter list plus the `touched` map to remember for the
 * plan being applied now.
 */
export function applyAIPlanToFilters(
  prev: InteractiveFilter[],
  widgetUpdates: InteractiveFilter[],
  exprFilters: InteractiveFilter[],
  previouslyTouched: Map<string, InteractiveFilter | null> | null,
): { next: InteractiveFilter[]; touched: Map<string, InteractiveFilter | null> } {
  let next = revertAIPlanFilters(prev, previouslyTouched);

  // Snapshot the pre-plan state of every widget this plan touches — after
  // the revert, so a widget touched by both plans snapshots its true
  // (user-set or empty) baseline rather than the old plan's value.
  const touched = new Map<string, InteractiveFilter | null>();
  for (const update of widgetUpdates) {
    const existing = next.find((f) => f.index === update.index && f.source === undefined);
    touched.set(update.index, existing ? { ...existing } : null);
  }

  for (const update of widgetUpdates) next = mergeFiltersBySource(next, update);
  return { next: [...next, ...exprFilters], touched };
}

/** Undo an applied AI plan: drop its expression filters and restore every
 *  widget it touched to its remembered pre-plan entry. */
export function revertAIPlanFilters(
  prev: InteractiveFilter[],
  touched: Map<string, InteractiveFilter | null> | null,
): InteractiveFilter[] {
  let next = clearFiltersBySource(prev, 'ai_prompt');
  if (touched) {
    for (const [index, before] of touched) {
      next = mergeFiltersBySource(next, before ?? { index, value: null });
    }
  }
  return next;
}
