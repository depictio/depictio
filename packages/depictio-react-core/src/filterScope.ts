/**
 * Which filters reach which components.
 *
 * A tab's filters (the left panel's, a `display: 'strip'` bar's, a lasso on a
 * map or a figure) reach every component on the tab. A section's own filter bar
 * (`filter_bar: true`, see `stripLayout.ts`) is narrower: its filters reach the
 * components of that section and nothing else. So:
 *
 *   a component in section S sees the tab's filters plus S's bar filters;
 *   a component anywhere else ignores S's bar filters.
 *
 * The rule is applied wherever filters leave the app for a component: the grid
 * cells (`DashboardGrid`), the cards' bulk compute (one request per distinct
 * filter set, `planScopedRequests`), the cross-tab host, the funnel (each
 * control's remaining values are computed against the filters its own scope
 * sees) and the maps and footer outside any section. The server needs nothing
 * new: every endpoint already filters by what the request carries, and keys its
 * caches on it.
 *
 * Scopes are keyed by filter `index`, i.e. by the interactive component that
 * emits the filter. Selections made on a chart, a table or a map carry the
 * index of the component they were made on, which is never a bar member, so
 * they stay tab-wide wherever that component sits.
 */
import type { FilterSectionSpec, InteractiveFilter, StoredMetadata } from './api';
import { isFilterActive } from './activeFilters';
import {
  barSectionNames,
  hasSectionBar,
  isBarMember,
} from './components/interactive/strip/stripLayout';

/** Filter index → the scope key of the section whose bar holds that filter. */
export type FilterScopes = ReadonlyMap<string, string>;

export const NO_FILTER_SCOPES: FilterScopes = new Map();

/**
 * The scope key of a section. A tab's own sections are keyed by name, which is
 * what their members' `section` says; a section fanned out from a sibling tab
 * is keyed by its owner too, since two tabs may each have a section of that
 * name.
 */
export function sectionScopeKey(name: string, ownerDashboardId?: string | null): string {
  return ownerDashboardId ? `\u0000${ownerDashboardId}\u0000${name}` : name;
}

/** The scopes of the bars carried by `gridSections` (a tab's, or one fanned-out
 *  section's) over `metadata`. Only sections with a bar of their own scope
 *  anything: a `display: 'strip'` bar filters the whole tab. */
export function sectionFilterScopes(
  metadata: readonly StoredMetadata[] | null | undefined,
  gridSections: readonly FilterSectionSpec[] | null | undefined,
  ownerDashboardId?: string | null,
): Map<string, string> {
  const scopes = new Map<string, string>();
  const scoped = new Set((gridSections ?? []).filter(hasSectionBar).map((s) => s.name));
  if (scoped.size === 0) return scopes;
  const bars = barSectionNames(gridSections);
  for (const m of metadata ?? []) {
    if (!isBarMember(m, bars) || !scoped.has(m.section as string)) continue;
    scopes.set(m.index, sectionScopeKey(m.section as string, ownerDashboardId));
  }
  return scopes;
}

/** Several scope maps as one; the first to claim an index keeps it. */
export function mergeFilterScopes(...maps: (FilterScopes | null | undefined)[]): FilterScopes {
  const present = maps.filter((m): m is FilterScopes => Boolean(m && m.size));
  if (present.length === 0) return NO_FILTER_SCOPES;
  if (present.length === 1) return present[0];
  const merged = new Map<string, string>();
  for (const m of present) for (const [k, v] of m) if (!merged.has(k)) merged.set(k, v);
  return merged;
}

/**
 * The filters a component in `scope` sees: every filter bound to no section,
 * plus those bound to `scope`. `null` is "outside any section bar" — the
 * unsectioned grid, a section without a bar, the maps, the footer.
 *
 * Returns `filters` itself when nothing is dropped, so a dashboard without
 * section bars hands its components the very array it always did.
 */
export function filtersInScope(
  filters: InteractiveFilter[],
  scopes: FilterScopes | null | undefined,
  scope: string | null | undefined,
): InteractiveFilter[] {
  if (!scopes || scopes.size === 0) return filters;
  const kept = filters.filter((f) => {
    const owner = scopes.get(f.index);
    return owner === undefined || owner === scope;
  });
  return kept.length === filters.length ? filters : kept;
}

/** Identity of what a filter list actually filters by: its active entries. An
 *  emptied control leaves `value: []` behind, which narrows nothing. */
export function activeFilterSignature(filters: InteractiveFilter[]): string {
  return JSON.stringify(
    filters
      .filter(isFilterActive)
      .map((f) => [f.index, f.source ?? null, f.value] as const)
      .sort((a, b) =>
        a[0] === b[0] ? String(a[1]).localeCompare(String(b[1])) : a[0].localeCompare(b[0]),
      ),
  );
}

export interface ScopedRequest {
  /** The ids sharing this filter set. */
  ids: string[];
  /** The filters to send for them. */
  filters: InteractiveFilter[];
}

/**
 * Batch per-component requests (the cards' bulk compute) by the filters each
 * component sees: one request per distinct set of active filters, ids in the
 * order given. With no section bar, or none of them filtering, that is a single
 * request carrying `filters` unchanged — what the apps sent before scopes.
 */
export function planScopedRequests(
  items: readonly { id: string; scope: string | null | undefined }[],
  filters: InteractiveFilter[],
  scopes: FilterScopes | null | undefined,
): ScopedRequest[] {
  if (items.length === 0) return [];
  if (!scopes || scopes.size === 0) return [{ ids: items.map((i) => i.id), filters }];
  const bySignature = new Map<string, ScopedRequest>();
  for (const item of items) {
    const seen = filtersInScope(filters, scopes, item.scope ?? null);
    const signature = activeFilterSignature(seen);
    const batch = bySignature.get(signature);
    if (batch) batch.ids.push(item.id);
    else bySignature.set(signature, { ids: [item.id], filters: seen });
  }
  return [...bySignature.values()];
}

/** The ids `scopes` binds to `scope`: a section bar's controls. */
export function scopedFilterIds(scopes: FilterScopes | null | undefined, scope: string): string[] {
  const ids: string[] = [];
  for (const [index, owner] of scopes ?? []) if (owner === scope) ids.push(index);
  return ids;
}
