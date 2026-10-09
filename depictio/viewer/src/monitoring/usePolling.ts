/**
 * Polling hooks for the monitoring surfaces.
 *
 * `usePolling` is moved from AdminMonitoringPanel. `useLivePolling` exists to
 * fix a scaling problem that live step reporting would otherwise create.
 *
 * Both hooks share one fetch loop (`useFetchLoop`) and its three rules. Only
 * the latest request may land: after a filter change, a slower response for
 * the previous filters must not overwrite the new list. `load` is an effect
 * dependency, so a filter change refetches at once instead of waiting for the
 * next tick (or forever, with Auto off); callers must therefore memoize `load`
 * with `useCallback`. And a mount costs one request: StrictMode replaying the
 * effect, or a pane remounted after some live pushes, must not add a second.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from 'react';

import { REFRESH_MS } from './tokens';

export interface PollingState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/** Lets `useLivePolling` see each request go out and land, so the events that
 *  arrived in between can be applied on top of its response. */
interface FetchLoopHooks<T> {
  /** A request is about to be sent. */
  onRequest: () => void;
  /** The newest request settled. `base` is its result, or the data already
   *  held when it `failed`. Returns the data to keep. */
  onSettle: (base: T | null, failed: boolean) => T | null;
}

interface FetchLoop<T> extends PollingState<T> {
  /** The data as last written, ahead of the render that shows it, so events
   *  handled in the same tick each build on the one before. */
  dataRef: MutableRefObject<T | null>;
  commit: (next: T | null) => void;
  /** Epoch ms of the last successful fetch, 0 before the first one. */
  lastFetchRef: MutableRefObject<number>;
  inFlightRef: MutableRefObject<boolean>;
}

/** Runs `load` on mount and (when `auto`) every `intervalMs`. */
function useFetchLoop<T>(
  load: () => Promise<T>,
  auto: boolean,
  intervalMs: number,
  hooks?: FetchLoopHooks<T>,
): FetchLoop<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;
  const hooksRef = useRef(hooks);
  hooksRef.current = hooks;
  const dataRef = useRef<T | null>(null);
  const lastFetchRef = useRef(0);
  const inFlightRef = useRef(false);
  const latestRequest = useRef(0);

  const commit = useCallback((next: T | null) => {
    dataRef.current = next;
    setData(next);
  }, []);

  const refresh = useCallback(async () => {
    const request = ++latestRequest.current;
    inFlightRef.current = true;
    hooksRef.current?.onRequest();
    setLoading(true);
    try {
      const result = await loadRef.current();
      if (request !== latestRequest.current) return;
      commit(hooksRef.current ? hooksRef.current.onSettle(result, false) : result);
      setError(null);
      lastFetchRef.current = Date.now();
    } catch (err) {
      if (request !== latestRequest.current) return;
      setError(err instanceof Error ? err.message : 'Failed to load');
      if (hooksRef.current) {
        const kept = hooksRef.current.onSettle(dataRef.current, true);
        if (kept !== dataRef.current) commit(kept);
      }
    } finally {
      if (request === latestRequest.current) {
        inFlightRef.current = false;
        setLoading(false);
      }
    }
  }, [commit]);

  // What the last immediate fetch was for. StrictMode runs this effect twice
  // with nothing changed, and an interval change (an adaptive cadence) is no
  // reason to fetch either. New filters, or Auto switched on, still fetch now.
  const fetchedFor = useRef<{ load: () => Promise<T>; auto: boolean } | null>(null);
  useEffect(() => {
    const previous = fetchedFor.current;
    fetchedFor.current = { load, auto };
    if (!previous || previous.load !== load || (auto && !previous.auto)) void refresh();
    if (!auto) return undefined;
    const id = setInterval(() => void refresh(), intervalMs);
    return () => clearInterval(id);
  }, [auto, refresh, intervalMs, load]);

  return { data, loading, error, refresh, dataRef, commit, lastFetchRef, inFlightRef };
}

/** Generic polling hook: runs `load` on mount and (when `auto`) every
 *  interval. Also refreshes whenever `liveSignal` changes; the panel bumps it
 *  on each live WebSocket push so the active pane updates instantly. */
export function usePolling<T>(
  load: () => Promise<T>,
  auto: boolean,
  liveSignal = 0,
  intervalMs: number = REFRESH_MS,
): PollingState<T> {
  const { data, loading, error, refresh } = useFetchLoop(load, auto, intervalMs);

  // Compared with the value seen at mount, not with 0: a pane remounted after
  // some pushes already fetches on mount, and must not fetch a second time.
  const seenSignal = useRef(liveSignal);
  useEffect(() => {
    if (liveSignal === seenSignal.current) return;
    seenSignal.current = liveSignal;
    void refresh();
  }, [liveSignal, refresh]);

  return { data, loading, error, refresh };
}

/** A stream of live events, delivered to subscribers one by one.
 *
 *  Not a "latest event" state value: React batches the state updates of
 *  several pushes that land in one tick, so a consumer reading such a value
 *  only ever sees the last of them, and the others are lost. */
export interface LiveFeed<E> {
  /** Returns the unsubscribe function. */
  subscribe: (listener: (event: E) => void) => () => void;
}

export interface LiveFeedSource<E> extends LiveFeed<E> {
  publish: (event: E) => void;
}

export function createLiveFeed<E>(): LiveFeedSource<E> {
  const listeners = new Set<(event: E) => void>();
  return {
    publish: (event) => {
      for (const listener of listeners) listener(event);
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export interface LivePollingOptions<T, E> {
  /** Apply an event to the current data. Return the new data, or `null` to say
   *  "I can't apply this", which triggers a full refetch. */
  patch: (current: T | null, event: E) => T | null;
  /** Refetch at most this often even while events keep arriving, so a long-lived
   *  view cannot drift indefinitely from the server. */
  reconcileMs?: number;
  intervalMs?: number;
}

/**
 * Polling with in-memory patching from live events.
 *
 * The problem this solves: the existing pattern turns every WebSocket push into
 * `liveSignal++`, which refetches the whole list (200 full ingestion runs).
 * That was fine when a push meant "a run started" or "a run finished" (twice
 * per run), but live step reporting emits one per step, so a single run would
 * trigger ~50 full-list refetches, and a watcher produces them continuously.
 *
 * Here an event carries the delta (< 1 KB) and `patch` applies it locally. A
 * refetch happens only when `patch` returns null (the event refers to something
 * not in the current data, e.g. a run that started after the last fetch) or
 * when `reconcileMs` has elapsed, which bounds any drift caused by a dropped
 * message.
 *
 * Every event is applied, in order. One that arrives while a request is in
 * flight is held and applied to that request's response when it lands: the
 * server may have read the list before the event happened, and patching only
 * the old data would let the response quietly undo it.
 */
export function useLivePolling<T, E>(
  load: () => Promise<T>,
  auto: boolean,
  feed: LiveFeed<E>,
  { patch, reconcileMs = 30000, intervalMs = REFRESH_MS }: LivePollingOptions<T, E>,
): PollingState<T> {
  const patchRef = useRef(patch);
  patchRef.current = patch;
  const heldEvents = useRef<E[]>([]);
  const refreshRef = useRef<() => void>(() => undefined);

  const hooks = useMemo<FetchLoopHooks<T>>(
    () => ({
      // Events received before a request is sent are in its response.
      onRequest: () => {
        heldEvents.current = [];
      },
      onSettle: (base, failed) => {
        let next = base;
        let unplaced = false;
        for (const event of heldEvents.current) {
          const patched = patchRef.current(next, event);
          if (patched === null) unplaced = true;
          else next = patched;
        }
        heldEvents.current = [];
        // An event even the fresh list cannot place is about something newer
        // than the read: fetch again, once the current request has settled.
        // Not after a failure, which would turn an erroring endpoint into one
        // request per event.
        if (unplaced && !failed) queueMicrotask(() => refreshRef.current());
        return next;
      },
    }),
    [],
  );

  const { data, loading, error, refresh, dataRef, commit, lastFetchRef, inFlightRef } =
    useFetchLoop(load, auto, intervalMs, hooks);
  refreshRef.current = refresh;

  useEffect(() => {
    const unsubscribe = feed.subscribe((event) => {
      if (inFlightRef.current) {
        heldEvents.current.push(event);
        return;
      }
      // Overdue for a full read: take it rather than patching onto data that
      // may already have diverged. The read happens after this event.
      if (Date.now() - lastFetchRef.current > reconcileMs) {
        void refresh();
        return;
      }
      const patched = patchRef.current(dataRef.current, event);
      if (patched === null) void refresh();
      else commit(patched);
    });
    return () => {
      unsubscribe();
      // An unmounted pane has nothing to replay onto, and must not refetch.
      heldEvents.current = [];
    };
  }, [feed, reconcileMs, refresh, commit, dataRef, lastFetchRef, inFlightRef]);

  return { data, loading, error, refresh };
}
