/**
 * Browser-local persistence of a dashboard's filter state, per dashboard.
 *
 * This is the instant half of the hybrid persistence: read synchronously in
 * the `useState` initializer so the very first fetch is already filtered
 * (an effect-based hydration would fetch once unfiltered, then again), while
 * the server-side copy (`fetchDashboardFilterState`) reconciles asynchronously
 * for the returning-from-another-device case.
 *
 * The "Remember filters" toggle is stored separately from the state itself so
 * turning it off can drop the saved filters without forgetting the choice.
 * Absent key = ON: persistence is the default behavior.
 */

import type { InteractiveFilter } from 'depictio-react-core';

const STATE_VERSION = 1;
const stateKey = (dashboardId: string) => `depictio.filterState.v1:${dashboardId}`;
const rememberKey = (dashboardId: string) => `depictio.filterState.remember.v1:${dashboardId}`;

export interface StoredFilterState {
  v: number;
  filters: InteractiveFilter[];
  /** Epoch ms of the last write; compared against the server copy's
   *  `updated_at` so an older device doesn't clobber a newer view. */
  updatedAt: number;
}

export function readLocalFilterState(dashboardId: string): StoredFilterState | null {
  try {
    const raw = window.localStorage.getItem(stateKey(dashboardId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredFilterState>;
    if (parsed?.v !== STATE_VERSION) return null;
    if (!Array.isArray(parsed.filters)) return null;
    return {
      v: STATE_VERSION,
      filters: parsed.filters,
      updatedAt: typeof parsed.updatedAt === 'number' ? parsed.updatedAt : 0,
    };
  } catch {
    return null;
  }
}

export function writeLocalFilterState(
  dashboardId: string,
  filters: InteractiveFilter[],
): void {
  try {
    if (filters.length === 0) {
      // Deriving "empty → remove" from the array keeps "Reset all" honest:
      // clearing the filters clears the stored copy with no extra wiring.
      window.localStorage.removeItem(stateKey(dashboardId));
      return;
    }
    const payload: StoredFilterState = { v: STATE_VERSION, filters, updatedAt: Date.now() };
    window.localStorage.setItem(stateKey(dashboardId), JSON.stringify(payload));
  } catch {
    // Storage unavailable (private mode, quota): filters just won't survive
    // the visit. The server copy still can, for authenticated users.
  }
}

export function clearLocalFilterState(dashboardId: string): void {
  try {
    window.localStorage.removeItem(stateKey(dashboardId));
  } catch {
    // A failed clear leaves a stale entry the sanitization pass discards.
  }
}

/** Absent = ON — remembering is the default. */
export function readRememberToggle(dashboardId: string): boolean {
  try {
    return window.localStorage.getItem(rememberKey(dashboardId)) !== '0';
  } catch {
    return true;
  }
}

export function writeRememberToggle(dashboardId: string, on: boolean): void {
  try {
    if (on) window.localStorage.removeItem(rememberKey(dashboardId));
    else window.localStorage.setItem(rememberKey(dashboardId), '0');
  } catch {
    // Preference simply won't stick.
  }
}
