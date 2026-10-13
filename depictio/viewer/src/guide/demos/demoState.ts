/**
 * The state a Guide demo keeps for itself: its filters and its cards' values.
 *
 * The demos draw the dashboard's own components, so what they need is what
 * the app keeps for the canvas — a filter list with the app's merge rules, a
 * debounced copy for fetching, card values from the bulk endpoint — held here
 * instead, per demo. Nothing in it reaches the dashboard's filters.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  bulkComputeCards,
  enrichFilterWithDcId,
  hasLiveValues,
  mergeFiltersBySource,
} from 'depictio-react-core';
import type {
  BulkComputeOptions,
  InteractiveFilter,
  StoredMetadata,
} from 'depictio-react-core';

/** The dashboard's own debounce before a filter change refetches. */
export const SETTLE_MS = 250;

export interface DemoFilters {
  /** As picked: what a control shows. */
  filters: InteractiveFilter[];
  /** Debounced: what fetches read. */
  settled: InteractiveFilter[];
  onFilterChange: (update: InteractiveFilter) => void;
  /** A change fetches read at once, in the same render as whatever else
   *  changed with it: a selection cleared as it becomes a group. */
  applyNow: (update: InteractiveFilter) => void;
  reset: () => void;
}

const NO_FILTERS: InteractiveFilter[] = [];

const sameFilters = (a: InteractiveFilter[], b: InteractiveFilter[]) =>
  a === b || (a.length === b.length && JSON.stringify(a) === JSON.stringify(b));

/** A filter list of the demo's own, merged as the app merges the canvas's. */
export function useDemoFilters(metadata: readonly StoredMetadata[]): DemoFilters {
  const current = useRef(NO_FILTERS);
  const [filters, setFilters] = useState(NO_FILTERS);
  const [settled, setSettled] = useState(NO_FILTERS);
  const change = useCallback(
    (update: InteractiveFilter, now: boolean) => {
      const next = mergeFiltersBySource(
        current.current,
        enrichFilterWithDcId(update, metadata as StoredMetadata[]),
      );
      // A component echoing what it was just told (a table unticking the
      // rows a cleared selection held) changes nothing.
      if (!sameFilters(current.current, next)) {
        current.current = next;
        setFilters(next);
      }
      if (now) setSettled(current.current);
    },
    [metadata],
  );
  useEffect(() => {
    const timer = setTimeout(() => setSettled(filters), SETTLE_MS);
    return () => clearTimeout(timer);
  }, [filters]);
  const onFilterChange = useCallback(
    (update: InteractiveFilter) => change(update, false),
    [change],
  );
  const applyNow = useCallback((update: InteractiveFilter) => change(update, true), [change]);
  const reset = useCallback(() => {
    current.current = NO_FILTERS;
    setFilters(NO_FILTERS);
    setSettled(NO_FILTERS);
  }, []);
  return { filters, settled, onFilterChange, applyNow, reset };
}

export interface DemoCards {
  values: Record<string, unknown>;
  secondary: Record<string, Record<string, unknown>>;
  loading: boolean;
  failed: boolean;
}

const EMPTY: DemoCards = { values: {}, secondary: {}, loading: false, failed: false };

/**
 * The values of `ids`, cards of the tab `dashboardId`, under `filters`: one
 * call to the endpoint the dashboard computes its cards with, again whenever
 * the filters or the group options change. The previous values stay up
 * while the next call runs, as on the canvas.
 */
export function useDemoCards(
  dashboardId: string | null | undefined,
  ids: readonly string[],
  filters: InteractiveFilter[],
  options?: BulkComputeOptions,
): DemoCards {
  const [state, setState] = useState<DemoCards>(EMPTY);
  const idKey = ids.join('|');
  const key = JSON.stringify([
    filters.map((f) => [f.index, f.source ?? null, f.value]),
    options ?? null,
  ]);
  useEffect(() => {
    if (!dashboardId || ids.length === 0) {
      setState(EMPTY);
      return;
    }
    const ctrl = new AbortController();
    setState((s) => ({ ...s, loading: true }));
    bulkComputeCards(dashboardId, filters, [...ids], options, ctrl.signal)
      .then((res) =>
        setState({
          values: res.values ?? {},
          secondary: res.secondary_values ?? {},
          loading: false,
          failed: false,
        }),
      )
      .catch((err) => {
        if (err?.name === 'AbortError') return;
        setState((s) => ({ ...s, loading: false, failed: true }));
      });
    return () => ctrl.abort();
    // `idKey` and `key` are the ids', filters' and options' identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, idKey, key]);
  return state;
}

/** The cards among `members`, by id, and the text tiles computed with them
 *  (live values, see `hasLiveValues`). */
export function useCardIds(members: readonly StoredMetadata[]): string[] {
  const key = members
    .filter((m) => m.component_type === 'card' || hasLiveValues(m))
    .map((m) => m.index)
    .join('|');
  return useMemo(() => (key ? key.split('|') : []), [key]);
}
