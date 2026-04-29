import { useCallback, useState } from 'react';

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

  const toggle = useCallback(() => {
    setOpened((prev) => {
      const next = !prev;
      writeCollapsed(!next);
      return next;
    });
  }, []);

  return [opened, toggle];
}
