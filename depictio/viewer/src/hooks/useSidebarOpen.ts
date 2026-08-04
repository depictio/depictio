import { useCallback, useEffect, useRef, useState } from 'react';
import { SIDEBAR_TOGGLE_EVENT, dispatchPanelToggle } from 'depictio-react-core';

/**
 * Persistent desktop-sidebar state, kept in sync with the Dash app's
 * `sidebar-collapsed` `dcc.Store(storage_type="local")` key. Tab switches
 * re-mount the SPA via `window.location.assign(...)`, so without persistence
 * the sidebar would always reset to its default on every navigation.
 *
 * Storage convention (matches Dash): `true` = collapsed/hidden, `false` =
 * expanded/visible. The dcc.Store JSON-encodes the value, so the localStorage
 * payload is the literal string `"true"` or `"false"`.
 */
const STORAGE_KEY = 'sidebar-collapsed';

// Mirror of Mantine AppShell's `navbar.width` and `transitionDuration` in
// App.tsx — kept in this hook so the toggle event payload is self-contained.
// If you change the AppShell config, change these constants too.
const NAVBAR_WIDTH_PX = 250;
const TRANSITION_MS = 300;

function readCollapsed(defaultCollapsed: boolean): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw == null) return defaultCollapsed;
    const parsed = JSON.parse(raw);
    return typeof parsed === 'boolean' ? parsed : defaultCollapsed;
  } catch {
    return defaultCollapsed;
  }
}

function writeCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(collapsed));
  } catch {
    // ignore quota / disabled storage
  }
}

/**
 * Returns `[opened, toggle]`, matching the shape of `useDisclosure(false)`'s
 * `[value, { toggle }]` API but with persistence baked in.
 *
 * @param defaultCollapsed - fallback when localStorage has no value yet.
 *   Defaults to `true` (collapsed/hidden) to preserve the current React
 *   viewer's first-run UX.
 */
export function useSidebarOpen(defaultCollapsed = true): [boolean, () => void] {
  const [opened, setOpened] = useState<boolean>(() => !readCollapsed(defaultCollapsed));
  const flagTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The next state is derived here rather than inside a `setOpened` updater:
  // StrictMode double-invokes updaters in dev, which would dispatch the toggle
  // event twice. `DashboardGrid` reads the second one as a genuine re-toggle
  // and applies the width delta twice, mis-sizing every figure for the length
  // of the transition (it self-corrects on the post-transition re-measure,
  // which is why this went unnoticed).
  const openedRef = useRef(opened);

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
    writeCollapsed(!next);
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
