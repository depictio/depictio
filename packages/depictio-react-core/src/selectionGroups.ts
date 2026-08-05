/**
 * On-the-fly selection groups ("select & compare").
 *
 * A group is a named, colored snapshot of a selection filter (lasso on a
 * scatter, ticked table rows, map selection): the column it was made on plus
 * the captured values. Groups live outside the dashboard's filter list — they
 * are per-browser annotation state, persisted in localStorage per dashboard —
 * and are only *projected* into filters at the fetch boundary. That keeps them
 * clear of `mergeFiltersBySource`'s one-entry-per-(index, source) rule, which
 * is exactly what lets a user keep several selections at once: saving a group
 * frees the selection slot for the next lasso.
 *
 * Filtering by groups rides the existing pipeline untouched: the projection
 * below is an ordinary MultiSelect-shaped value filter, so server-side
 * predicate building, cross-DC link resolution (keyed on `metadata.dc_id`) and
 * load caching all apply as if the user had picked the values by hand.
 */

import type { InteractiveFilter } from './api';
import { TAB10_PALETTE } from './colors';

export interface SelectionGroup {
  id: string;
  name: string;
  /** Hex color used for chips and for server-side figure coloring. */
  color: string;
  /** Data collection the source selection was made on (drives link resolution). */
  dcId?: string;
  /** Column the captured values belong to. */
  columnName: string;
  values: string[];
  createdAt: number;
  /** When true the group participates in the projected dashboard filter. */
  filterActive: boolean;
}

/** Payload sent to the figure render endpoint when "color by group" is on. */
export interface GroupRenderDef {
  name: string;
  column_name: string;
  values: string[];
  color: string;
}

/** What the apps thread down to figure renderers when coloring is enabled
 *  (App/EditorApp → DashboardGrid → ComponentRenderer → FigureRenderer). */
export interface GroupRenderState {
  groups: GroupRenderDef[];
  colorByGroup: boolean;
}

export const GROUP_FILTER_SOURCE = 'group_filter' as const;
export const GROUP_FILTER_INDEX_PREFIX = '__depictio_group__:';

/** Ceiling on captured values per group. Groups are persisted to localStorage
 *  (~5 MB quota shared across the origin) and echoed into request bodies, so a
 *  runaway million-point lasso must be refused rather than stored. */
export const MAX_GROUP_VALUES = 25_000;

const STORAGE_PREFIX = 'depictio:selection-groups:';
const STORAGE_VERSION = 1;

export interface SelectionGroupsPayload {
  version: number;
  groups: SelectionGroup[];
  /** Global "color figures by groups" toggle, persisted alongside. */
  colorByGroup: boolean;
}

const SELECTION_SOURCES = new Set([
  'scatter_selection',
  'table_selection',
  'map_selection',
  'image_selection',
]);

/** Active selection-event filters a group can be created from: they carry a
 *  non-empty array of values and a resolvable column. */
export function selectableSelectionFilters(
  filters: InteractiveFilter[],
): InteractiveFilter[] {
  return filters.filter(
    (f) =>
      f.source !== undefined &&
      SELECTION_SOURCES.has(f.source) &&
      Array.isArray(f.value) &&
      f.value.length > 0 &&
      Boolean(f.column_name ?? f.metadata?.selection_column ?? f.metadata?.column_name),
  );
}

/** Snapshot a selection filter into a named group. Returns null when the
 *  filter has no usable values/column or exceeds the size cap. */
export function groupFromSelectionFilter(
  filter: InteractiveFilter,
  name: string,
  color: string,
): SelectionGroup | null {
  if (!Array.isArray(filter.value) || filter.value.length === 0) return null;
  if (filter.value.length > MAX_GROUP_VALUES) return null;
  const columnName =
    filter.column_name ?? filter.metadata?.selection_column ?? filter.metadata?.column_name;
  if (!columnName) return null;
  const trimmed = name.trim();
  if (!trimmed) return null;
  return {
    id: `grp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    name: trimmed,
    color,
    dcId: filter.metadata?.dc_id,
    columnName,
    values: filter.value.map((v) => String(v)),
    createdAt: Date.now(),
    filterActive: false,
  };
}

/**
 * Project filter-active groups into dashboard filters: one union entry per
 * `(dcId, columnName)` pair, so two groups on the same column mean "row is in
 * group A OR group B" (the natural compare-two-cohorts semantics), while groups
 * on different columns AND together like any two dashboard filters.
 */
export function groupsToFilters(groups: SelectionGroup[]): InteractiveFilter[] {
  const buckets = new Map<string, { dcId?: string; columnName: string; values: string[] }>();
  const seen = new Map<string, Set<string>>();
  for (const g of groups) {
    if (!g.filterActive || g.values.length === 0) continue;
    const key = `${g.dcId ?? ''}:${g.columnName}`;
    let bucket = buckets.get(key);
    let seenVals = seen.get(key);
    if (!bucket) {
      bucket = { dcId: g.dcId, columnName: g.columnName, values: [] };
      seenVals = new Set<string>();
      buckets.set(key, bucket);
      seen.set(key, seenVals);
    }
    for (const v of g.values) {
      if (seenVals!.has(v)) continue;
      seenVals!.add(v);
      bucket.values.push(v);
    }
  }
  return Array.from(buckets.entries()).map(([key, b]) => ({
    index: GROUP_FILTER_INDEX_PREFIX + key,
    value: b.values,
    column_name: b.columnName,
    interactive_component_type: 'MultiSelect',
    source: GROUP_FILTER_SOURCE,
    metadata: {
      dc_id: b.dcId,
      column_name: b.columnName,
      interactive_component_type: 'MultiSelect',
    },
  }));
}

/** All groups (filter-active or not) in render-payload shape for the figure
 *  endpoint. The server matches groups by column presence in the frame, so
 *  sending every group is what makes coloring work on any DC that carries the
 *  column (directly or via a join key). */
export function groupsRenderPayload(groups: SelectionGroup[]): GroupRenderDef[] {
  return groups
    .filter((g) => g.values.length > 0)
    .map((g) => ({
      name: g.name,
      column_name: g.columnName,
      values: g.values,
      color: g.color,
    }));
}

/** First palette color not already used by an existing group; wraps around
 *  when every color is taken. */
export function nextGroupColor(
  existing: SelectionGroup[],
  palette: readonly string[] = TAB10_PALETTE,
): string {
  const used = new Set(existing.map((g) => g.color));
  for (const c of palette) {
    if (!used.has(c)) return c;
  }
  return palette[existing.length % palette.length];
}

export function readSelectionGroups(dashboardId: string): SelectionGroupsPayload | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + dashboardId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<SelectionGroupsPayload>;
    if (parsed?.version !== STORAGE_VERSION) return null;
    if (!Array.isArray(parsed.groups)) return null;
    const groups = parsed.groups.filter(
      (g): g is SelectionGroup =>
        typeof g === 'object' &&
        g !== null &&
        typeof g.id === 'string' &&
        typeof g.name === 'string' &&
        typeof g.color === 'string' &&
        typeof g.columnName === 'string' &&
        Array.isArray(g.values),
    );
    return {
      version: STORAGE_VERSION,
      groups,
      colorByGroup: Boolean(parsed.colorByGroup),
    };
  } catch {
    return null;
  }
}

export function writeSelectionGroups(
  dashboardId: string,
  groups: SelectionGroup[],
  colorByGroup: boolean,
): void {
  try {
    const key = STORAGE_PREFIX + dashboardId;
    if (groups.length === 0 && !colorByGroup) {
      window.localStorage.removeItem(key);
      return;
    }
    window.localStorage.setItem(
      key,
      JSON.stringify({ version: STORAGE_VERSION, groups, colorByGroup }),
    );
  } catch {
    // Storage unavailable/full: groups simply won't survive a reload.
  }
}
