import { useCallback, useEffect, useState } from 'react';

import {
  RECENTS_EVENT,
  type RecentEntry,
  readRecents,
} from '../lib/dashboardRecents';

const PINS_KEY = 'depictio.dashboards.pinned.v1';

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

export interface UsePinsAndRecentsResult {
  pinnedIds: Set<string>;
  recents: RecentEntry[];
  togglePin: (id: string) => void;
}

export function useDashboardPinsAndRecents(): UsePinsAndRecentsResult {
  const [pinnedIds, setPinnedIds] = useState<Set<string>>(loadPins);
  const [recents, setRecents] = useState<RecentEntry[]>(() => readRecents());

  useEffect(() => {
    savePins(pinnedIds);
  }, [pinnedIds]);

  // Keep recents in sync if another tab or the open-action handler updates
  // localStorage. The custom event fires within the same tab; the storage
  // event covers cross-tab updates.
  useEffect(() => {
    const refresh = () => setRecents(readRecents());
    window.addEventListener(RECENTS_EVENT, refresh);
    window.addEventListener('storage', refresh);
    return () => {
      window.removeEventListener(RECENTS_EVENT, refresh);
      window.removeEventListener('storage', refresh);
    };
  }, []);

  const togglePin = useCallback((id: string) => {
    if (!id) return;
    setPinnedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return { pinnedIds, recents, togglePin };
}
