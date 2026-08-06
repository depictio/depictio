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
 * load caching all apply as if the user had picked the values by hand. A
 * consequence, and an intended one: unlike a live selection (which is stripped
 * from the figure that emitted it), an active group filter also narrows its
 * source figure — once saved, a group is just another dashboard filter.
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

/** How the "Color by" override is displayed: series overlaid in one panel
 *  ("color") or split into small multiples ("facet"). */
export type GroupingDisplay = 'color' | 'facet';

/** What the apps thread down to figure renderers when coloring is enabled
 *  (App/EditorApp → DashboardGrid → ComponentRenderer → FigureRenderer). */
export interface GroupRenderState {
  groups: GroupRenderDef[];
  colorByGroup: boolean;
  /** Global "color by <real column>" override. The color map is the stable
   *  palette computed client-side from the column's unfiltered universe. */
  colorByColumn?: { columnName: string; colorMap?: Record<string, string> };
  /** Omitted means "color" (the default overlay display). */
  display?: GroupingDisplay;
  /** Groups mode only: false drops ungrouped rows ("Other") from figures
   *  instead of drawing them gray. Omitted means true. */
  showOther?: boolean;
}

/** The dashboard-global "Color by" control: nothing, the saved groups, or a
 *  real categorical column. */
export type ColorByState =
  | { kind: 'none' }
  | { kind: 'groups' }
  | { kind: 'column'; columnName: string };

export const COLOR_BY_NONE: ColorByState = { kind: 'none' };

/** Resolve the dashboard's "Color by" state into the payload figures send to
 *  the render endpoint: groups win over a column override (the server enforces
 *  the same precedence); `undefined` means no coloring override at all. */
export function resolveGroupRender(
  colorBy: ColorByState,
  renderGroups: GroupRenderDef[],
  colorByColumn: GroupRenderState['colorByColumn'],
  display: GroupingDisplay = 'color',
  showOther = true,
): GroupRenderState | undefined {
  if (colorBy.kind === 'groups' && renderGroups.length > 0) {
    return { groups: renderGroups, colorByGroup: true, display, showOther };
  }
  if (colorBy.kind === 'column' && colorByColumn) {
    // Split needs a known category set: until the palette resolves (or if it
    // never does) the display degrades to overlay, mirroring the server's
    // refuse-rather-than-guess guard on unknown facet cardinality. Without
    // this the first mapless render would facet on an unbounded column and
    // then visibly flip back when the palette lands.
    const hasPalette = Object.keys(colorByColumn.colorMap ?? {}).length > 0;
    return {
      groups: [],
      colorByGroup: false,
      colorByColumn,
      display: display === 'facet' && !hasPalette ? 'color' : display,
    };
  }
  return undefined;
}

export const GROUP_FILTER_SOURCE = 'group_filter' as const;
export const GROUP_FILTER_INDEX_PREFIX = '__depictio_group__:';

/** Ceiling on captured values per group. Groups are persisted to localStorage
 *  (~5 MB quota shared across the origin) and echoed into request bodies, so a
 *  runaway million-point lasso must be refused rather than stored. */
export const MAX_GROUP_VALUES = 25_000;

const STORAGE_PREFIX = 'depictio:selection-groups:';
const STORAGE_VERSION = 2;

export interface SelectionGroupsPayload {
  version: number;
  groups: SelectionGroup[];
  /** Dashboard-global "Color by" state, persisted alongside the groups. */
  colorBy: ColorByState;
  /** Global "compare groups in cards" toggle. */
  compareInCards: boolean;
  /** Overlay vs small-multiples display for the "Color by" override.
   *  Additive to v2: absent in older payloads, read as "color". */
  displayMode: GroupingDisplay;
  /** Whether ungrouped rows render as gray "Other" (groups mode).
   *  Additive to v2: absent in older payloads, read as true. */
  showOther: boolean;
  /** Whether card comparisons include the "All rows" reference entry.
   *  Additive to v2: absent in older payloads, read as true. */
  showOverall: boolean;
}

function parseColorBy(raw: unknown): ColorByState {
  if (typeof raw !== 'object' || raw === null) return COLOR_BY_NONE;
  const kind = (raw as { kind?: unknown }).kind;
  if (kind === 'groups') return { kind: 'groups' };
  if (kind === 'column') {
    const columnName = (raw as { columnName?: unknown }).columnName;
    if (typeof columnName === 'string' && columnName) return { kind: 'column', columnName };
  }
  return COLOR_BY_NONE;
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

/** Mirrors the server's ``MAX_NAME_LENGTH`` in ``sanitize_group_defs``: names
 *  are truncated to this many chars on the wire, so client-side uniqueness
 *  must hold on the truncated form too. */
const SERVER_NAME_LIMIT = 80;

/**
 * Group names are identity on the wire: the server dedups payload entries by
 * name (first wins) and the card comparison keys rows on it, so two groups
 * sharing a name would silently drop one from coloring and comparison while
 * the panel still lists both. Returns ``desired`` untouched when free,
 * otherwise suffixed with the first free ``" 2"``, ``" 3"``, …
 */
export function uniqueGroupName(
  desired: string,
  groups: SelectionGroup[],
  excludeId?: string,
): string {
  const clip = (s: string) => s.slice(0, SERVER_NAME_LIMIT);
  const taken = new Set(groups.filter((g) => g.id !== excludeId).map((g) => clip(g.name)));
  const base = clip(desired.trim());
  if (!base || !taken.has(base)) return base;
  for (let i = 2; ; i += 1) {
    const suffix = ` ${i}`;
    const candidate = base.slice(0, SERVER_NAME_LIMIT - suffix.length) + suffix;
    if (!taken.has(candidate)) return candidate;
  }
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
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const version = parsed?.version;
    if (version !== 1 && version !== STORAGE_VERSION) return null;
    if (!Array.isArray(parsed.groups)) return null;
    const groups = (parsed.groups as unknown[]).filter(
      (g): g is SelectionGroup =>
        typeof g === 'object' &&
        g !== null &&
        typeof (g as SelectionGroup).id === 'string' &&
        typeof (g as SelectionGroup).name === 'string' &&
        typeof (g as SelectionGroup).color === 'string' &&
        typeof (g as SelectionGroup).columnName === 'string' &&
        Array.isArray((g as SelectionGroup).values),
    );
    // v1 stored a single `colorByGroup` boolean; migrate on read (the next
    // write persists v2, so migration is one-shot per dashboard).
    const colorBy: ColorByState =
      version === 1
        ? parsed.colorByGroup
          ? { kind: 'groups' }
          : COLOR_BY_NONE
        : parseColorBy(parsed.colorBy);
    return {
      version: STORAGE_VERSION,
      groups,
      colorBy,
      compareInCards: version === 1 ? false : Boolean(parsed.compareInCards),
      displayMode: parsed.displayMode === 'facet' ? 'facet' : 'color',
      showOther: parsed.showOther !== false,
      showOverall: parsed.showOverall !== false,
    };
  } catch {
    return null;
  }
}

export function writeSelectionGroups(
  dashboardId: string,
  groups: SelectionGroup[],
  colorBy: ColorByState,
  compareInCards: boolean,
  displayMode: GroupingDisplay = 'color',
  showOther = true,
  showOverall = true,
): void {
  try {
    const key = STORAGE_PREFIX + dashboardId;
    if (groups.length === 0 && colorBy.kind === 'none' && !compareInCards) {
      window.localStorage.removeItem(key);
      return;
    }
    window.localStorage.setItem(
      key,
      JSON.stringify({
        version: STORAGE_VERSION,
        groups,
        colorBy,
        compareInCards,
        displayMode,
        showOther,
        showOverall,
      }),
    );
  } catch {
    // Storage unavailable/full: groups simply won't survive a reload.
  }
}
