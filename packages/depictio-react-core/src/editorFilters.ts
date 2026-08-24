/**
 * Per-tab persistence for the editor's interactive filter state.
 *
 * The component add/edit builder is a separate document reached by full page
 * navigation (`window.location.assign`), so the editor's in-memory filter
 * array dies twice on every builder round-trip: once on the way in (the
 * builder previews then had no filter state to apply — #329) and once on the
 * way back (the whole grid, including the freshly added component, remounted
 * unfiltered — #196).
 *
 * `sessionStorage` gives exactly the lifetime wanted (same reasoning as
 * `floatingFilters.ts`): it survives navigation within a browser tab and dies
 * when the tab closes, so an editing session's filters never leak into a
 * fresh visit. The stored dashboard id keeps them from leaking into a
 * *different* dashboard opened in the same tab — cross-dashboard filter
 * state stays scratch, only the same-dashboard round-trip survives.
 */

import type { InteractiveFilter } from './api';

const KEY = 'depictio:editor-filters';

export interface EditorFilterPayload {
  dashboardId: string;
  filters: InteractiveFilter[];
}

/** Filters persisted for `dashboardId` in this tab; `[]` when the stored
 *  entry belongs to another dashboard or cannot be parsed (the stale entry is
 *  dropped so it can't resurface later). */
export function readEditorFilters(dashboardId: string): InteractiveFilter[] {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Partial<EditorFilterPayload>;
    if (parsed?.dashboardId !== dashboardId || !Array.isArray(parsed.filters)) {
      window.sessionStorage.removeItem(KEY);
      return [];
    }
    return parsed.filters;
  } catch {
    return [];
  }
}

export function writeEditorFilters(
  dashboardId: string,
  filters: InteractiveFilter[],
): void {
  try {
    if (filters.length === 0) {
      window.sessionStorage.removeItem(KEY);
      return;
    }
    window.sessionStorage.setItem(KEY, JSON.stringify({ dashboardId, filters }));
  } catch {
    // Storage unavailable: filters simply won't survive the builder round-trip.
  }
}

export function clearEditorFilters(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // Nothing to do — a failed clear leaves a stale entry that the
    // dashboard-id check on the next read discards anyway.
  }
}
