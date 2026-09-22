import { useCallback, useEffect, useRef, useState } from 'react';
import { SIDEBAR_TOGGLE_EVENT, dispatchPanelToggle } from 'depictio-react-core';

/**
 * Persistent desktop state of the dashboard tab sidebar, scoped per dashboard
 * *family* like `useFilterPanelOpen`: a tab switch is a full page navigation
 * to a sibling dashboard document (`window.location.assign(...)`), so a
 * per-tab key would reset the sidebar on every switch, and a single global key
 * would let one "close" hide it on every dashboard. The apps pass the family
 * id once it resolves (the tab's own id stands in before that), and the
 * key-swap effect below re-reads storage when it lands.
 *
 * Defaults to open: the tab list is how a multi-tab dashboard is navigated, so
 * it stays visible unless the viewer closed it on this dashboard last time.
 *
 * Storage convention (shared with `useFilterPanelOpen`): `true` = collapsed,
 * JSON-encoded, so the payload is the literal string `"true"` or `"false"`.
 */
const STORAGE_KEY_PREFIX = 'tab-sidebar-collapsed:';

// Mirror of Mantine AppShell's `navbar.width` and `transitionDuration` in
// App.tsx — kept in this hook so the toggle event payload is self-contained.
// If you change the AppShell config, change these constants too.
const NAVBAR_WIDTH_PX = 250;
const TRANSITION_MS = 300;

function storageKey(scopeId: string | null): string {
  return `${STORAGE_KEY_PREFIX}${scopeId ?? 'unknown'}`;
}

function readCollapsed(scopeId: string | null): boolean {
  try {
    const raw = localStorage.getItem(storageKey(scopeId));
    if (raw == null) return false;
    const parsed = JSON.parse(raw);
    return typeof parsed === 'boolean' ? parsed : false;
  } catch {
    return false;
  }
}

function writeCollapsed(scopeId: string | null, collapsed: boolean): void {
  try {
    localStorage.setItem(storageKey(scopeId), JSON.stringify(collapsed));
  } catch {
    // ignore quota / disabled storage
  }
}

/**
 * Returns `[opened, toggle]`, matching the shape of `useDisclosure(false)`'s
 * `[value, { toggle }]` API but with persistence baked in.
 *
 * @param scopeId - scopes persistence (the dashboard family id, in practice;
 *   see above); `null` falls back to a shared key.
 */
export function useSidebarOpen(scopeId: string | null): [boolean, () => void] {
  const [opened, setOpened] = useState<boolean>(() => !readCollapsed(scopeId));
  const flagTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The next state is derived here rather than inside a `setOpened` updater:
  // StrictMode double-invokes updaters in dev, which would dispatch the toggle
  // event twice. `DashboardGrid` reads the second one as a genuine re-toggle
  // and applies the width delta twice, mis-sizing every figure for the length
  // of the transition (it self-corrects on the post-transition re-measure,
  // which is why this went unnoticed).
  const openedRef = useRef(opened);

  // Resolving the family id swaps the storage key under a mounted sidebar.
  const scopeRef = useRef(scopeId);
  useEffect(() => {
    if (scopeRef.current === scopeId) return;
    scopeRef.current = scopeId;
    const next = !readCollapsed(scopeId);
    openedRef.current = next;
    setOpened(next);
  }, [scopeId]);

  const toggle = useCallback(() => {
    // Mark `<body>` so width-aware grids can swap their item transition
    // duration to match the parent (`300ms`) — see `app.css`.
    document.body.classList.add('sidebar-transitioning');
    if (flagTimerRef.current) clearTimeout(flagTimerRef.current);
    flagTimerRef.current = setTimeout(() => {
      document.body.classList.remove('sidebar-transitioning');
      flagTimerRef.current = null;
    }, TRANSITION_MS + 20); // 300ms + 20ms slack so the final frame settles

    const next = !openedRef.current;
    openedRef.current = next;
    writeCollapsed(scopeRef.current, !next);
    // Tell the dashboard grid the predicted final container delta so it
    // can `setContainerWidth` to the destination value once at the start
    // of the transition. RGL then computes new item transforms once,
    // CSS animates them smoothly over 300ms in lockstep with the parent.
    // This avoids the ResizeObserver→setState→render race which was
    // producing 20–30Hz "stair-step" item updates against the parent's
    // 60Hz compositor-driven width animation.
    // The navbar collapses to nothing, so its full width is also its swing.
    dispatchPanelToggle(SIDEBAR_TOGGLE_EVENT, {
      willBeOpen: next,
      swingPx: NAVBAR_WIDTH_PX,
      durationMs: TRANSITION_MS,
    });
    setOpened(next);
  }, []);

  useEffect(
    () => () => {
      if (flagTimerRef.current) clearTimeout(flagTimerRef.current);
      document.body.classList.remove('sidebar-transitioning');
    },
    [],
  );

  return [opened, toggle];
}
