import { useCallback, useEffect, useState } from 'react';

const PINS_KEY = 'depictio.projects.pinned.v1';

function loadPins(): Set<string> {
  try {
    const raw = localStorage.getItem(PINS_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((s): s is string => typeof s === 'string'));
  } catch {
    return new Set();
  }
}

function savePins(set: Set<string>): void {
  try {
    localStorage.setItem(PINS_KEY, JSON.stringify(Array.from(set)));
  } catch {
    /* ignore */
  }
}

export interface UseProjectPinsResult {
  pinnedIds: Set<string>;
  togglePin: (id: string) => void;
}

/** Per-browser pinning for projects. No "recents" pile — projects are
 *  navigated less frequently than dashboards and a Pinned section + a
 *  toolbar Favorites toggle cover the same use case. */
export function useProjectPins(): UseProjectPinsResult {
  const [pinnedIds, setPinnedIds] = useState<Set<string>>(loadPins);

  useEffect(() => {
    savePins(pinnedIds);
  }, [pinnedIds]);

  const togglePin = useCallback((id: string) => {
    if (!id) return;
    setPinnedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return { pinnedIds, togglePin };
}
