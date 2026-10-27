import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { fetchJBrowseCalls, type InteractiveFilter, type JBrowseCall } from '../../api';
import type { NamedLocusSource } from './locusSources';
import {
  nearQuery,
  normalizeEnabledSources,
  parseStoredSources,
  sourcesBody,
  sourcesStorageKey,
  versionFields,
  type VisibleRegion,
} from './navigatorSteps';

interface UseCallNavigatorArgs {
  dashboardId: string;
  index: string;
  /** The filters the tile renders with (its own selection excluded). */
  filters: InteractiveFilter[];
  /** The data-version request body; only the pins are sent to the calls list. */
  versionBody: Record<string, unknown>;
  /** Off for a tile with no `locus_from`, or with `call_stepper: false`. */
  enabled: boolean;
  /** Anything that makes the loaded counts stale (filters, pins, a refresh). */
  resetKey: string;
  /** The tile's `locus_from` sources, primary first. */
  sources: NamedLocusSource[];
}

export interface CallNavigator {
  /** Merged regions under the filters and the enabled sources; 0 until counted. */
  total: number;
  /** The region the navigator stands on (a step or a picker click), if any. */
  current: JBrowseCall | null;
  busy: boolean;
  /** Names of the sources switched on; persisted per tile. */
  enabledSources: string[];
  setEnabledSources: (names: string[]) => void;
  /** The nearest merged region left (-1) or right (1) of the visible span, on
   *  to the next chromosome of `chromOrder` when the chromosome has none.
   *  Resolves to the region to navigate to (also made current), null at an end. */
  step: (
    direction: 1 | -1,
    visible: VisibleRegion[],
    chromOrder: string[],
  ) => Promise<JBrowseCall | null>;
  /** A region the reader picked in the region picker. */
  select: (call: JBrowseCall) => void;
  setCurrent: (call: JBrowseCall | null) => void;
}

function readStoredSources(index: string): string[] | null {
  try {
    return parseStoredSources(window.localStorage.getItem(sourcesStorageKey(index)));
  } catch {
    return null;
  }
}

function writeStoredSources(index: string, names: string[]): void {
  try {
    window.localStorage.setItem(sourcesStorageKey(index), JSON.stringify(names));
  } catch {
    // Private mode or blocked storage: the choice just lasts the session.
  }
}

const isAbort = (err: unknown) => (err as { name?: string } | null)?.name === 'AbortError';

/**
 * Spatial previous / next over the merged regions of a tile's `locus_from`.
 * One `limit: 1` call counts the regions; a step asks the backend for the
 * region nearest the visible span, so nothing is paged and 224k peaks cost the
 * same as ten. The navigator only reads: it never touches the filters, and the
 * view is moved by whoever calls `step` with the region it gets back.
 */
export function useCallNavigator({
  dashboardId,
  index,
  filters,
  versionBody,
  enabled,
  resetKey,
  sources,
}: UseCallNavigatorArgs): CallNavigator {
  const [total, setTotal] = useState(0);
  const [current, setCurrent] = useState<JBrowseCall | null>(null);
  const [busy, setBusy] = useState(false);
  const names = useMemo(() => sources.map((s) => s.name), [sources]);
  const namesKey = names.join('\u0000');
  // Stored per dashboard: a YAML `index` recurs across templates.
  const [chosen, setChosen] = useState<string[] | null>(() =>
    readStoredSources(`${dashboardId}.${index}`),
  );
  const enabledSources = useMemo(
    () => normalizeEnabledSources(chosen, names),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [chosen, namesKey],
  );
  const enabledKey = enabledSources.join('\u0000');

  const argsRef = useRef({ dashboardId, index, filters, versionBody });
  argsRef.current = { dashboardId, index, filters, versionBody };
  const sourcesRef = useRef<string[] | null>(null);
  sourcesRef.current = sourcesBody(enabledSources, names);
  const countGen = useRef(0);
  const stepGen = useRef(0);
  const stepAbort = useRef<AbortController | null>(null);

  const setEnabledSources = useCallback(
    (next: string[]) => {
      const normalized = normalizeEnabledSources(next, names);
      setChosen(normalized);
      writeStoredSources(`${argsRef.current.dashboardId}.${argsRef.current.index}`, normalized);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [namesKey],
  );

  useEffect(() => {
    const gen = (countGen.current += 1);
    if (!enabled) {
      setTotal(0);
      return;
    }
    const ctrl = new AbortController();
    const a = argsRef.current;
    fetchJBrowseCalls(
      a.dashboardId,
      a.index,
      {
        filters: a.filters,
        limit: 1,
        merge: true,
        sources: sourcesRef.current,
        ...versionFields(a.versionBody),
      },
      ctrl.signal,
    )
      .then((res) => {
        if (gen === countGen.current) setTotal(res.total);
      })
      .catch((err) => {
        if (isAbort(err) || gen !== countGen.current) return;
        // The count is a convenience: without it the navigator just stays hidden.
        setTotal(0);
        console.warn('jbrowse: cannot count the regions', err);
      });
    return () => {
      countGen.current += 1;
      ctrl.abort();
    };
  }, [enabled, resetKey, enabledKey]);

  // A newer step, or a tile that goes away, drops the request still in flight.
  useEffect(
    () => () => {
      stepGen.current += 1;
      stepAbort.current?.abort();
    },
    [],
  );

  const step = useCallback(
    async (
      direction: 1 | -1,
      visible: VisibleRegion[],
      chromOrder: string[],
    ): Promise<JBrowseCall | null> => {
      const near = nearQuery(direction, visible, chromOrder);
      if (!near) return null;
      stepAbort.current?.abort();
      const ctrl = new AbortController();
      stepAbort.current = ctrl;
      const gen = (stepGen.current += 1);
      setBusy(true);
      try {
        const a = argsRef.current;
        const res = await fetchJBrowseCalls(
          a.dashboardId,
          a.index,
          {
            filters: a.filters,
            limit: 1,
            near,
            merge: true,
            sources: sourcesRef.current,
            ...versionFields(a.versionBody),
          },
          ctrl.signal,
        );
        if (gen !== stepGen.current) return null;
        const call = res.rows[0];
        if (!call?.locus) return null;
        setCurrent(call);
        return call;
      } catch (err) {
        if (!isAbort(err)) console.warn('jbrowse: cannot step to the next region', err);
        return null;
      } finally {
        if (gen === stepGen.current) setBusy(false);
      }
    },
    [],
  );

  const select = useCallback((call: JBrowseCall) => setCurrent(call), []);

  return {
    total,
    current,
    busy,
    enabledSources,
    setEnabledSources,
    step,
    select,
    setCurrent,
  };
}
