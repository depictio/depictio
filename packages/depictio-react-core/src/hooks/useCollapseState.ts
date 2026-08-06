import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

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
  /** Collapse or expand a whole set in one write and one re-render — what the
   *  grid's "collapse all sections" control needs. */
  setAll: (keys: string[], collapsed: boolean) => void;
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

  // Mirrors `collapsed` so the mutators can derive the next set without running
  // inside a state updater. Updaters are re-invoked under StrictMode, and
  // writing to localStorage from one makes them impure.
  const collapsedRef = useRef(collapsed);

  // Switching dashboards swaps the storage key under a mounted panel.
  const keyRef = useRef(storageKey);

  const commit = useCallback((next: Set<string>) => {
    collapsedRef.current = next;
    writeCollapsed(keyRef.current, next);
    setCollapsed(next);
  }, []);

  useEffect(() => {
    if (keyRef.current === storageKey) return;
    keyRef.current = storageKey;
    const next = new Set(readCollapsed(storageKey) ?? seedRef.current);
    collapsedRef.current = next;
    setCollapsed(next);
  }, [storageKey]);

  const toggle = useCallback(
    (key: string) => {
      const next = new Set(collapsedRef.current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      commit(next);
    },
    [commit],
  );

  const setAll = useCallback(
    (keys: string[], collapsedNext: boolean) => {
      const next = new Set(collapsedRef.current);
      for (const key of keys) {
        if (collapsedNext) next.add(key);
        else next.delete(key);
      }
      // A single call only ever adds or only ever removes, so an unchanged size
      // means an unchanged set. Bailing keeps "collapse all" from pushing a
      // fresh Set through the context — and re-rendering every chrome — when
      // everything it names is already in the requested state.
      if (next.size === collapsedRef.current.size) return;
      commit(next);
    },
    [commit],
  );

  const isOpen = useCallback((key: string) => !collapsed.has(key), [collapsed]);

  // Memoised so callers can put the whole state object in a dependency array
  // without re-running on every render of their parent.
  return useMemo(() => ({ isOpen, toggle, setAll }), [isOpen, toggle, setAll]);
}

export default useCollapseState;
