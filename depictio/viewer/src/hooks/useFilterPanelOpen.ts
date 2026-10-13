import { useCallback, useEffect, useRef, useState } from 'react';
import { FILTER_PANEL_TOGGLE_EVENT, dispatchPanelToggle } from 'depictio-react-core';

/**
 * Persistent collapsed/expanded state for the left filter panel, modelled on
 * `useSidebarOpen`. Same storage convention (`true` = collapsed, JSON-encoded)
 * and same toggle event contract, but scoped per dashboard *family*: which
 * filters matter is a property of the dashboard, not of the app as a whole —
 * and a tab switch is a full page navigation to a sibling dashboard document,
 * so a per-tab key would reopen the panel on every switch. The apps pass the
 * family id once it resolves (the tab's own id stands in before that), and the
 * key-swap effect below re-reads storage when it lands.
 *
 * Defaults to open, like the tab sidebar: the filters are the point of the
 * page, so hiding them on first visit would bury the feature. A dashboard can
 * say otherwise (`filter_panel_default: collapsed`, e.g. a prose landing tab);
 * that only decides the first visit — a stored toggle always wins.
 */
const STORAGE_KEY_PREFIX = 'filter-panel-collapsed:';

/** Mirrors the CSS transition on the panel's grid column. See `app.css`. */
export const FILTER_PANEL_TRANSITION_MS = 300;

function storageKey(dashboardId: string | null): string {
  return `${STORAGE_KEY_PREFIX}${dashboardId ?? 'unknown'}`;
}

function readStored(dashboardId: string | null): boolean | null {
  try {
    const raw = localStorage.getItem(storageKey(dashboardId));
    if (raw == null) return null;
    const parsed = JSON.parse(raw);
    return typeof parsed === 'boolean' ? parsed : null;
  } catch {
    return null;
  }
}

function readCollapsed(dashboardId: string | null, defaultCollapsed: boolean): boolean {
  return readStored(dashboardId) ?? defaultCollapsed;
}

function writeCollapsed(dashboardId: string | null, collapsed: boolean): void {
  try {
    localStorage.setItem(storageKey(dashboardId), JSON.stringify(collapsed));
  } catch {
    // ignore quota / disabled storage
  }
}

/**
 * @param dashboardId - scopes persistence (the family id, in practice — see
 *   above); `null` falls back to a shared key.
 * @param swingPx - px the content column gains when the panel collapses, i.e.
 *   `panelWidth - railWidth`. Read at toggle time so a resize between toggles
 *   is accounted for.
 * @param defaultCollapsed - the dashboard's `filter_panel_default`, used
 *   only while nothing is stored for this family.
 * @returns `[open, toggle]`, matching `useSidebarOpen`.
 */
export function useFilterPanelOpen(
  dashboardId: string | null,
  swingPx: number,
  defaultCollapsed = false,
): [boolean, () => void] {
  const [opened, setOpened] = useState<boolean>(
    () => !readCollapsed(dashboardId, defaultCollapsed),
  );
  const flagTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // `toggle` is called from an event handler, so reading the live swing from a
  // ref keeps the callback stable while still using the current panel width.
  const swingRef = useRef(swingPx);
  swingRef.current = swingPx;

  // The next state is derived here rather than inside a `setOpened` updater:
  // StrictMode double-invokes updaters in dev, which would persist and — worse
  // — dispatch the toggle event twice. `DashboardGrid` treats a second event
  // mid-transition as a genuine re-toggle and would apply the width delta
  // twice, mis-sizing every figure until the post-transition re-measure.
  const openedRef = useRef(opened);

  // Switching dashboards swaps the storage key under a mounted panel, and the
  // dashboard's default only arrives with its document, after first render.
  // Either one re-reads; a stored toggle still wins over the default.
  const dashboardRef = useRef(dashboardId);
  const defaultRef = useRef(defaultCollapsed);
  useEffect(() => {
    if (dashboardRef.current === dashboardId && defaultRef.current === defaultCollapsed) return;
    dashboardRef.current = dashboardId;
    defaultRef.current = defaultCollapsed;
    const next = !readCollapsed(dashboardId, defaultCollapsed);
    if (next === openedRef.current) return;
    openedRef.current = next;
    setOpened(next);
  }, [dashboardId, defaultCollapsed]);

  const toggle = useCallback(() => {
    // Mark `<body>` so the dashboard grid matches its item transition duration
    // to the panel's — see `app.css`.
    document.body.classList.add('panel-transitioning');
    if (flagTimerRef.current) clearTimeout(flagTimerRef.current);
    flagTimerRef.current = setTimeout(() => {
      document.body.classList.remove('panel-transitioning');
      flagTimerRef.current = null;
    }, FILTER_PANEL_TRANSITION_MS + 20); // slack so the final frame settles

    const next = !openedRef.current;
    openedRef.current = next;
    writeCollapsed(dashboardRef.current, !next);
    dispatchPanelToggle(FILTER_PANEL_TOGGLE_EVENT, {
      willBeOpen: next,
      swingPx: swingRef.current,
      durationMs: FILTER_PANEL_TRANSITION_MS,
    });
    setOpened(next);
  }, []);

  useEffect(
    () => () => {
      if (flagTimerRef.current) clearTimeout(flagTimerRef.current);
      document.body.classList.remove('panel-transitioning');
    },
    [],
  );

  return [opened, toggle];
}

export default useFilterPanelOpen;
