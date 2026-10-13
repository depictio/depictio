import { useEffect, useMemo, useState } from 'react';
import { fetchDashboard } from 'depictio-react-core';
import type { DashboardData, DashboardSummary, SpotlightTab } from 'depictio-react-core';

/**
 * The tabs the dashboard search looks through, with their components.
 *
 * The tab being read is already in memory — in the editor with its unsaved
 * edits, which is what an author searching wants to find. Every other tab's
 * components are fetched the first time the palette opens, through the same
 * `/dashboards/get` the page itself loads with, so a public or anonymous
 * reader sees exactly what they could open, and nothing the viewer cannot.
 * Nothing is fetched for a reader who never searches.
 *
 * Fetches are kept per page load: switching tabs is a page load, so a cache
 * that outlived one would only ever serve a stale copy of the tab just left.
 */

/** Tabs fetched at once: enough to fill a family quickly, few enough not to
 *  queue in front of the page's own figure requests. */
const CONCURRENCY = 4;

const cache = new Map<string, Promise<DashboardData>>();

function loadTab(id: string): Promise<DashboardData> {
  let pending = cache.get(id);
  if (!pending) {
    pending = fetchDashboard(id);
    // A failure is not cached: the next opening tries again.
    pending.catch(() => cache.delete(id));
    cache.set(id, pending);
  }
  return pending;
}

/** The pill label the sidebar gives a tab. */
export function tabLabel(tab: DashboardSummary): string {
  const isParent = !tab.parent_dashboard_id;
  return (isParent ? tab.main_tab_name || tab.title : tab.title) || tab.dashboard_id;
}

export interface SpotlightTabsState {
  tabs: SpotlightTab[];
  /** Tabs whose components are still on their way. */
  pending: number;
  /** Tabs whose components could not be loaded. */
  failed: number;
}

export function useSpotlightTabs({
  tabs,
  currentId,
  current,
  opens,
}: {
  /** The family, in sidebar order. */
  tabs: DashboardSummary[];
  currentId: string | null;
  /** The tab being read, as the page holds it. */
  current: DashboardData | null;
  /** How many times the palette has been opened. Zero fetches nothing; each
   *  opening fetches what is missing and retries what failed. */
  opens: number;
}): SpotlightTabsState {
  const [loaded, setLoaded] = useState<Record<string, DashboardData | 'error'>>({});

  const others = useMemo(
    () => tabs.map((t) => t.dashboard_id).filter((id) => id !== currentId),
    [tabs, currentId],
  );

  useEffect(() => {
    if (opens === 0) return;
    const queue = others.filter((id) => !(id in loaded) || loaded[id] === 'error');
    if (queue.length === 0) return;
    let cancelled = false;
    const worker = async () => {
      for (let id = queue.shift(); id !== undefined; id = queue.shift()) {
        let result: DashboardData | 'error';
        try {
          result = await loadTab(id);
        } catch {
          result = 'error';
        }
        if (cancelled) return;
        setLoaded((prev) => ({ ...prev, [id]: result }));
      }
    };
    for (let i = 0; i < Math.min(CONCURRENCY, queue.length); i += 1) void worker();
    return () => {
      cancelled = true;
    };
    // `loaded` is read to skip what is already in, not to re-run on each arrival.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opens, others]);

  return useMemo(() => {
    let pending = 0;
    let failed = 0;
    const out: SpotlightTab[] = tabs.map((t) => {
      const isCurrent = t.dashboard_id === currentId;
      const data = isCurrent ? current : loaded[t.dashboard_id];
      if (!isCurrent && data === undefined) pending += 1;
      if (data === 'error') failed += 1;
      return {
        id: t.dashboard_id,
        label: tabLabel(t),
        description: t.subtitle?.trim() || null,
        group: t.tab_group ?? null,
        components: data && data !== 'error' ? (data.stored_metadata ?? []) : undefined,
      };
    });
    // A dashboard whose tab list has not arrived yet still searches itself.
    if (currentId && current && !tabs.some((t) => t.dashboard_id === currentId)) {
      out.unshift({
        id: currentId,
        label: String(current.title || currentId),
        components: current.stored_metadata ?? [],
      });
    }
    return { tabs: out, pending: opens > 0 ? pending : 0, failed };
  }, [tabs, currentId, current, loaded, opens]);
}
