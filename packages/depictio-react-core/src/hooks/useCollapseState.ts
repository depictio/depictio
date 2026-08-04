import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Persistent open/closed state for a set of collapsible regions.
 *
 * Stores the *collapsed* keys rather than the open ones so a group or section
 * added after the user last visited defaults to open instead of silently
 * hiding new filters. Mirrors the per-dashboard localStorage convention used
 * by the notes footer (`notes-footer-open:{dashboardId}`).
 */
export interface CollapseState {
  isOpen: (key: string) => boolean;
  toggle: (key: string) => void;
}

function readCollapsed(storageKey: string): string[] | null {
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw == null) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((k) => typeof k === 'string') : null;
  } catch {
    return null;
  }
}

function writeCollapsed(storageKey: string, keys: Set<string>): void {
  try {
    localStorage.setItem(storageKey, JSON.stringify([...keys]));
  } catch {
    // ignore quota / disabled storage
  }
}

/**
 * @param storageKey - localStorage key, typically suffixed with the dashboard id.
 * @param initiallyCollapsed - keys collapsed when nothing is stored yet, e.g.
 *   sections a dashboard author declared `collapsed: true`. Consulted only on
 *   first visit and on a dashboard switch, so it never overrides a user's choice.
 */
export function useCollapseState(
  storageKey: string,
  initiallyCollapsed: string[] = [],
): CollapseState {
  // Kept current rather than frozen: the seed is read only when localStorage
  // has no entry, so tracking the latest value can't clobber a user's choice.
  const seedRef = useRef(initiallyCollapsed);
  seedRef.current = initiallyCollapsed;

  const [collapsed, setCollapsed] = useState<Set<string>>(
    () => new Set(readCollapsed(storageKey) ?? initiallyCollapsed),
  );

  // Switching dashboards swaps the storage key under a mounted panel.
  const keyRef = useRef(storageKey);
  useEffect(() => {
    if (keyRef.current === storageKey) return;
    keyRef.current = storageKey;
    setCollapsed(new Set(readCollapsed(storageKey) ?? seedRef.current));
  }, [storageKey]);

  const toggle = useCallback((key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      writeCollapsed(keyRef.current, next);
      return next;
    });
  }, []);

  const isOpen = useCallback((key: string) => !collapsed.has(key), [collapsed]);

  return { isOpen, toggle };
}

export default useCollapseState;
