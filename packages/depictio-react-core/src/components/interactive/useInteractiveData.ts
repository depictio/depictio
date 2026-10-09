/**
 * The data every interactive control fetches, behind one cache per kind.
 *
 * The Filters panel's renderers each used to hold a module-level cache of
 * their own, so the MultiSelect and the SegmentedControl on the same column
 * fetched twice, and a filter-bar copy of either would have fetched a third
 * time. These hooks hold the one cache, and keep the resolved values too, so a
 * second consumer of an already-fetched column renders on its first pass
 * instead of flashing a skeleton.
 *
 * Cleared on page reload — the caches have always lived that long.
 *
 * While a data version is active (`DataVersionProvider`), options and bounds
 * come from that version's data through `filter_options` instead: the
 * per-collection endpoints only know the newest commit, so a select would
 * offer values the pinned data does not hold. The pins are part of the cache
 * key, so a version's options never answer for the live ones.
 */
import { useEffect, useState } from 'react';

import {
  ColumnRange,
  fetchColumnRange,
  fetchColumnRangeAt,
  fetchUniqueValues,
  fetchUniqueValuesAt,
  type DataPinFields,
} from '../../api';
import { dataPinBody, isDataVersionActive, useDataVersions } from '../../dataVersions';

interface Loadable<T> {
  data: T;
  loading: boolean;
  error: string | null;
}

const errorMessage = (err: unknown) => (err instanceof Error ? err.message : String(err));

/**
 * The pins a filter read goes out with, or null for a live read.
 *
 * Null also when there is no dashboard to resolve a version against: the
 * versioned endpoint is per dashboard, and a host that sets pins without one
 * (none does today) keeps the live read rather than failing every control.
 */
export function useFilterDataPins(): { dashboardId: string; pins: DataPinFields; key: string } | null {
  const state = useDataVersions();
  if (!state.dashboardId || !isDataVersionActive(state)) return null;
  const pins = dataPinBody(state);
  return { dashboardId: state.dashboardId, pins, key: JSON.stringify(pins) };
}

// ---------------------------------------------------------------- unique values

const uniqueValuesPending = new Map<string, Promise<string[]>>();
const uniqueValuesResolved = new Map<string, string[]>();

/** Cache key: `filter_expr` and the data pins change the option set, so they
 *  are part of it. */
const uniqueValuesKey = (
  dcId?: string,
  column?: string,
  filterExpr?: string | null,
  pinKey?: string,
) => (dcId && column ? `${dcId}|${column}|${filterExpr || ''}|${pinKey || ''}` : null);

/**
 * A categorical column's distinct values (`fetchUniqueValues`). `loading` is
 * false with no values when the metadata names no column; `error` carries the
 * failure, and the failed fetch is dropped from the cache so a later mount
 * retries.
 */
export function useUniqueValues(
  dcId: string | undefined,
  columnName: string | undefined,
  filterExpr?: string | null,
): Loadable<string[]> {
  const versioned = useFilterDataPins();
  const key = uniqueValuesKey(dcId, columnName, filterExpr, versioned?.key);
  const [state, setState] = useState<Loadable<string[]>>(() => {
    const hit = key ? uniqueValuesResolved.get(key) : undefined;
    return { data: hit ?? [], loading: Boolean(key) && !hit, error: null };
  });

  useEffect(() => {
    if (!key || !dcId || !columnName) {
      setState({ data: [], loading: false, error: null });
      return;
    }
    const hit = uniqueValuesResolved.get(key);
    if (hit) {
      setState({ data: hit, loading: false, error: null });
      return;
    }
    let cancelled = false;
    let pending = uniqueValuesPending.get(key);
    if (!pending) {
      pending = versioned
        ? fetchUniqueValuesAt(versioned.dashboardId, dcId, columnName, versioned.pins, filterExpr)
        : fetchUniqueValues(dcId, columnName, filterExpr);
      uniqueValuesPending.set(key, pending);
    }
    pending
      .then((values) => {
        uniqueValuesResolved.set(key, values);
        if (!cancelled) setState({ data: values, loading: false, error: null });
      })
      .catch((err) => {
        console.warn('[useUniqueValues] fetchUniqueValues failed:', err);
        uniqueValuesPending.delete(key);
        if (!cancelled) setState({ data: [], loading: false, error: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
    // `key` covers every input, the pins included.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}

// ----------------------------------------------------------------- column range

const rangePending = new Map<string, Promise<ColumnRange>>();
const rangeResolved = new Map<string, ColumnRange>();

/**
 * A numeric column's precomputed bounds (`fetchColumnRange`). `data` is null
 * until they arrive, and stays null with `loading` false when the metadata
 * names no column. What a missing min/max means is the caller's call: the
 * range slider falls back to 0–100, the single slider reports an error.
 */
export function useColumnRange(
  dcId: string | undefined,
  columnName: string | undefined,
): Loadable<ColumnRange | null> {
  const versioned = useFilterDataPins();
  const key = dcId && columnName ? `${dcId}|${columnName}|${versioned?.key ?? ''}` : null;
  const [state, setState] = useState<Loadable<ColumnRange | null>>(() => {
    const hit = key ? rangeResolved.get(key) : undefined;
    return { data: hit ?? null, loading: Boolean(key) && !hit, error: null };
  });

  useEffect(() => {
    if (!key || !dcId || !columnName) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    const hit = rangeResolved.get(key);
    if (hit) {
      setState({ data: hit, loading: false, error: null });
      return;
    }
    let cancelled = false;
    let pending = rangePending.get(key);
    if (!pending) {
      pending = versioned
        ? fetchColumnRangeAt(versioned.dashboardId, dcId, columnName, versioned.pins)
        : fetchColumnRange(dcId, columnName);
      rangePending.set(key, pending);
    }
    pending
      .then((range) => {
        rangeResolved.set(key, range);
        if (!cancelled) setState({ data: range, loading: false, error: null });
      })
      .catch((err) => {
        console.warn('[useColumnRange] fetchColumnRange failed:', err);
        rangePending.delete(key);
        if (!cancelled) setState({ data: null, loading: false, error: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
