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
import { useEffect, useMemo, useState } from 'react';

import {
  ColumnRange,
  fetchColumnRange,
  fetchColumnRangeAt,
  fetchRankedValues,
  fetchRowValues,
  fetchUniqueValuePage,
  fetchUniqueValuePageAt,
  type DataPinFields,
  type UniqueValuePage,
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

const uniqueValuesPending = new Map<string, Promise<UniqueValuePage>>();
const uniqueValuesResolved = new Map<string, UniqueValuePage>();

/** Cache key: `filter_expr` and the data pins change the option set, so they
 *  are part of it. */
const uniqueValuesKey = (
  dcId?: string,
  column?: string,
  filterExpr?: string | null,
  pinKey?: string,
  orderBy?: string | null,
) => (dcId && column ? `${dcId}|${column}|${filterExpr || ''}|${pinKey || ''}|${orderBy || ''}` : null);

/**
 * A categorical column's distinct values (`fetchUniqueValues`), in the order
 * of the `orderBy` companion column when one is named. `loading` is
 * false with no values when the metadata names no column; `error` carries the
 * failure, and the failed fetch is dropped from the cache so a later mount
 * retries.
 */
export function useUniqueValues(
  dcId: string | undefined,
  columnName: string | undefined,
  filterExpr?: string | null,
  orderBy?: string | null,
): Loadable<string[]> & { truncated: boolean } {
  const versioned = useFilterDataPins();
  const key = uniqueValuesKey(dcId, columnName, filterExpr, versioned?.key, orderBy);
  const [state, setState] = useState<Loadable<string[]> & { truncated: boolean }>(() => {
    const hit = key ? uniqueValuesResolved.get(key) : undefined;
    return {
      data: hit?.values ?? [],
      truncated: hit?.truncated ?? false,
      loading: Boolean(key) && !hit,
      error: null,
    };
  });

  useEffect(() => {
    if (!key || !dcId || !columnName) {
      setState({ data: [], truncated: false, loading: false, error: null });
      return;
    }
    const hit = uniqueValuesResolved.get(key);
    if (hit) {
      setState({ data: hit.values, truncated: hit.truncated, loading: false, error: null });
      return;
    }
    let cancelled = false;
    let pending = uniqueValuesPending.get(key);
    if (!pending) {
      pending = versioned
        ? fetchUniqueValuePageAt(versioned.dashboardId, dcId, columnName, versioned.pins, {
            filterExpr,
            orderBy,
          })
        : fetchUniqueValuePage(dcId, columnName, { filterExpr, orderBy });
      uniqueValuesPending.set(key, pending);
    }
    pending
      .then((page) => {
        uniqueValuesResolved.set(key, page);
        if (!cancelled) setState({ data: page.values, truncated: page.truncated, loading: false, error: null });
      })
      .catch((err) => {
        console.warn('[useUniqueValues] fetchUniqueValues failed:', err);
        uniqueValuesPending.delete(key);
        if (!cancelled) setState({ data: [], truncated: false, loading: false, error: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
    // `key` covers every input, the pins included.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}

// ---------------------------------------------------------- searched values

/** Wait after the last keystroke before asking the server. */
const SEARCH_DEBOUNCE_MS = 250;

/** `base`, then `extra` and `found`, without repeats. */
export function mergeValues(
  base: readonly string[],
  ...more: ReadonlyArray<readonly string[]>
): string[] {
  const seen = new Set(base);
  const out = [...base];
  for (const list of more) {
    for (const v of list) {
      if (!seen.has(v)) {
        seen.add(v);
        out.push(v);
      }
    }
  }
  return out;
}

/**
 * A column's option list that stays complete past the server's limit. When
 * the list was cut (`truncated`), what the reader types is searched on the
 * server and the matches join the list, so a value past the cut (family
 * 3,052 of 4,333) can be found and picked (#1418). `keep` holds values that
 * stay listed whatever the search (the current selection), when the list was
 * cut only: past the cut, a held value missing from the list may still be in
 * the column, so it must not read as gone (an always-selected filter would
 * re-pick its first option). A whole list that lacks it says it is gone.
 */
export function useSearchedValues(
  dcId: string | undefined,
  columnName: string | undefined,
  filterExpr: string | null | undefined,
  orderBy: string | null | undefined,
  base: readonly string[],
  truncated: boolean,
  keep: readonly string[] = [],
): { values: string[]; onSearchChange: (query: string) => void } {
  const versioned = useFilterDataPins();
  const [query, setQuery] = useState('');
  // The server's matches for `query`; null until they arrive.
  const [found, setFound] = useState<string[] | null>(null);

  useEffect(() => {
    const q = query.trim();
    setFound(null);
    if (!truncated || !q || !dcId || !columnName) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      const request = versioned
        ? fetchUniqueValuePageAt(versioned.dashboardId, dcId, columnName, versioned.pins, {
            filterExpr,
            orderBy,
            search: q,
          })
        : fetchUniqueValuePage(dcId, columnName, { filterExpr, orderBy, search: q });
      request
        .then((page) => {
          if (!cancelled) setFound(page.values);
        })
        .catch((err) => {
          console.warn('[useSearchedValues] search failed:', err);
          if (!cancelled) setFound(null);
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // `versioned.key` stands for the pins.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, truncated, dcId, columnName, filterExpr, orderBy, versioned?.key]);

  const keepKey = keep.join('\u0000');
  // While a search has its matches, they are the list (with the held values):
  // the server returned every match up to its limit, so the cut list adds
  // none, and a dropdown that shows its first N entries ranks them as it would
  // a whole list.
  const values = useMemo(() => {
    if (!truncated) return [...base];
    return found ? mergeValues(found, keep) : mergeValues(base, keep);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, truncated, keepKey, found]);
  return { values, onSearchChange: setQuery };
}

// ---------------------------------------------------------------- ranked values

const rankedPending = new Map<string, Promise<string[]>>();
const rankedResolved = new Map<string, string[]>();

/**
 * The values of a column ranked by another (`fetchRankedValues`): where an
 * `always_selected` Select with `default_by` starts. `data` is null when there
 * is nothing to rank by (no `by`, or a data version is active, whose pinned
 * data the live ranking cannot speak for), and the Select then starts on its
 * first option. A failed ranking resolves to null too: it is a preference.
 */
export function useRankedValues(
  dcId: string | undefined,
  columnName: string | undefined,
  by: string | undefined,
  order: 'asc' | 'desc' = 'desc',
): Loadable<string[] | null> {
  const pinned = useFilterDataPins() !== null;
  const key = dcId && columnName && by && !pinned ? `${dcId}|${columnName}|${by}|${order}` : null;
  const [state, setState] = useState<Loadable<string[] | null>>(() => {
    const hit = key ? rankedResolved.get(key) : undefined;
    return { data: hit ?? null, loading: Boolean(key) && !hit, error: null };
  });

  useEffect(() => {
    if (!key || !dcId || !columnName || !by) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    const hit = rankedResolved.get(key);
    if (hit) {
      setState({ data: hit, loading: false, error: null });
      return;
    }
    let cancelled = false;
    let pending = rankedPending.get(key);
    if (!pending) {
      pending = fetchRankedValues(dcId, columnName, by, order);
      rankedPending.set(key, pending);
    }
    pending
      .then((values) => {
        rankedResolved.set(key, values);
        if (!cancelled) setState({ data: values, loading: false, error: null });
      })
      .catch((err) => {
        console.warn('[useRankedValues] fetchRankedValues failed:', err);
        rankedPending.delete(key);
        if (!cancelled) setState({ data: null, loading: false, error: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
    // `key` covers every input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}

// ------------------------------------------------------------------- row values

const rowPending = new Map<string, Promise<Record<string, unknown> | null>>();
const rowResolved = new Map<string, Record<string, unknown> | null>();

/**
 * A few columns of the row a filter value names (`fetchRowValues`): the facts
 * of a scope banner. `data` is null while loading, when no row holds the value,
 * when nothing is asked, and while a data version is active (the lookup only
 * reads the newest commit, so it cannot speak for pinned data). A failed
 * lookup resolves to null too: the facts are a garnish.
 */
export function useRowValues(
  dcId: string | undefined,
  column: string | undefined,
  value: string | undefined,
  columns: readonly string[],
  filterExpr?: string | null,
): Loadable<Record<string, unknown> | null> {
  const pinned = useFilterDataPins() !== null;
  const key =
    dcId && column && value !== undefined && columns.length > 0 && !pinned
      ? JSON.stringify([dcId, column, value, columns, filterExpr ?? null])
      : null;
  const [state, setState] = useState<Loadable<Record<string, unknown> | null>>(() => {
    const hit = key !== null && rowResolved.has(key) ? rowResolved.get(key)! : null;
    return { data: hit, loading: key !== null && !rowResolved.has(key), error: null };
  });

  useEffect(() => {
    if (!key || !dcId || !column || value === undefined) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    if (rowResolved.has(key)) {
      setState({ data: rowResolved.get(key)!, loading: false, error: null });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    let pending = rowPending.get(key);
    if (!pending) {
      pending = fetchRowValues(dcId, column, value, columns, filterExpr);
      rowPending.set(key, pending);
    }
    pending
      .then((row) => {
        rowResolved.set(key, row);
        if (!cancelled) setState({ data: row, loading: false, error: null });
      })
      .catch((err) => {
        console.warn('[useRowValues] fetchRowValues failed:', err);
        rowPending.delete(key);
        if (!cancelled) setState({ data: null, loading: false, error: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
    // `key` covers every input.
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
