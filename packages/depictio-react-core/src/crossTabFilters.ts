/**
 * Cross-tab persistence for filters that are meant to outlive a tab switch.
 *
 * Dashboard tabs are separate documents reached by full page navigation, so
 * every in-memory filter dies on a tab switch. That is the right behaviour for
 * a control that lives on one tab, but not for the two kinds of component that
 * are present on all of them: the floating map panel, and any interactive
 * control inside a filter section marked `persistent: true`. A viewer who
 * selects a region or a set of samples expects the selection to still be
 * applied after switching tabs.
 *
 * Only those filters are stored, so nothing else about filter lifetime
 * changes. `sessionStorage` gives exactly the lifetime we want: it survives
 * navigation within a browser tab and dies when that tab closes, so a
 * selection never leaks into a fresh visit.
 */

import type { InteractiveFilter } from './api';
import { isFilterActive } from './activeFilters';

const KEY = 'depictio:cross-tab-filters';

export interface CrossTabFilterPayload {
  /** Family the filters belong to. Only one dashboard is open per browser tab,
   *  so a single key suffices; the id is stored to detect the case where the
   *  viewer navigated to a *different* dashboard. */
  parentDashboardId: string;
  filters: InteractiveFilter[];
}

export function readCrossTabFilters(): CrossTabFilterPayload | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<CrossTabFilterPayload>;
    if (typeof parsed?.parentDashboardId !== 'string') return null;
    if (!Array.isArray(parsed.filters)) return null;
    return { parentDashboardId: parsed.parentDashboardId, filters: parsed.filters };
  } catch {
    return null;
  }
}

export function writeCrossTabFilters(
  parentDashboardId: string,
  filters: InteractiveFilter[],
): void {
  try {
    if (filters.length === 0) {
      window.sessionStorage.removeItem(KEY);
      return;
    }
    window.sessionStorage.setItem(KEY, JSON.stringify({ parentDashboardId, filters }));
  } catch {
    // Storage unavailable: the selection simply will not survive a tab switch.
  }
}

export function clearCrossTabFilters(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // Nothing to do — a failed clear leaves a stale entry that the family-id
    // check on the next load discards anyway.
  }
}

/** The subset of `filters` worth persisting:
 *
 *  - map selections owned by a component that is currently floating. A grid
 *    map's selection is deliberately excluded, since that map does not exist
 *    on the other tabs;
 *  - values of controls inside a persistent filter section (`source` unset —
 *    a selection filter emitted *by* a persistent grid member is deliberately
 *    not persisted). These controls fan out to every tab, so their `index`
 *    resolves everywhere, which is what lets the hydrated value restore the
 *    control's UI as well as the filtering. */
export function persistableCrossTabFilters(
  filters: InteractiveFilter[],
  floatingIndices: Set<string>,
  persistentFilterIndices: Set<string>,
): InteractiveFilter[] {
  return filters.filter(
    (f) =>
      (f.source === 'map_selection' &&
        floatingIndices.has(f.index) &&
        Array.isArray(f.value) &&
        f.value.length > 0) ||
      (f.source === undefined && persistentFilterIndices.has(f.index) && isFilterActive(f)),
  );
}
