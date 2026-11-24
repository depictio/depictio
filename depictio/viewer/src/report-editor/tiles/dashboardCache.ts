import { useEffect, useState } from 'react';
import { fetchDashboard } from 'depictio-react-core';
import type { DashboardData, StoredMetadata } from 'depictio-react-core';

/** How long a tab's dashboard is reused before the next tile reads it again. */
const TTL_MS = 2 * 60 * 1000;

interface Entry {
  at: number;
  promise: Promise<DashboardData>;
}

const cache = new Map<string, Entry>();

/** A tab's dashboard, read once and shared by every tile of the tab. */
export function loadTabDashboard(tabId: string): Promise<DashboardData> {
  const hit = cache.get(tabId);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.promise;
  const promise = fetchDashboard(tabId);
  cache.set(tabId, { at: Date.now(), promise });
  // A failed read is not kept: the next tile asks again.
  promise.catch(() => {
    if (cache.get(tabId)?.promise === promise) cache.delete(tabId);
  });
  return promise;
}

export function findComponent(
  dashboard: DashboardData | null,
  componentId: string,
): StoredMetadata | null {
  return (dashboard?.stored_metadata ?? []).find((m) => String(m.index) === componentId) ?? null;
}

export interface TabComponent {
  /** Undefined until read. */
  metadata: StoredMetadata | null | undefined;
  error: string | null;
}

/** The component's stored metadata, from the tab's shared dashboard. Reads
 *  nothing while `enabled` is false. `null` = read, but the component is not there. */
export function useTabComponent(tabId: string, componentId: string, enabled: boolean): TabComponent {
  const [state, setState] = useState<TabComponent>({ metadata: undefined, error: null });
  useEffect(() => {
    if (!enabled || !tabId) return;
    let cancelled = false;
    loadTabDashboard(tabId)
      .then((d) => {
        if (!cancelled) setState({ metadata: findComponent(d, componentId), error: null });
      })
      .catch((err) => {
        if (!cancelled) setState({ metadata: undefined, error: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, tabId, componentId]);
  return state;
}

/** A tab's whole dashboard, from the shared read; `null` until it is in. A
 *  tile hands it to `CategoryColorsContext`, as the viewer does, so it draws
 *  "Bacteria" in the colour its tab pins rather than the palette's next hue. */
export function useTabDashboard(tabId: string): DashboardData | null {
  const [doc, setDoc] = useState<DashboardData | null>(null);
  useEffect(() => {
    if (!tabId) return;
    let cancelled = false;
    loadTabDashboard(tabId)
      .then((d) => {
        if (!cancelled) setDoc(d);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [tabId]);
  return doc;
}
