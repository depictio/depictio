/**
 * Polling hooks for the monitoring surfaces.
 *
 * `usePolling` is moved verbatim from AdminMonitoringPanel. `useLivePolling`
 * is new and exists to fix a scaling problem that live step reporting would
 * otherwise create.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { REFRESH_MS } from './tokens';

export interface PollingState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/** Generic polling hook: runs `load` immediately and (when `auto`) every
 *  interval. Also refreshes whenever `liveSignal` increments — the panel bumps
 *  it on each live WebSocket push so the active pane updates instantly. */
export function usePolling<T>(
  load: () => Promise<T>,
  auto: boolean,
  liveSignal = 0,
  intervalMs: number = REFRESH_MS,
): PollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await loadRef.current();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    if (!auto) return undefined;
    const id = setInterval(() => void refresh(), intervalMs);
    return () => clearInterval(id);
  }, [auto, refresh, intervalMs]);

  // Live push: refresh on each signal bump (skip the initial 0 to avoid a
  // duplicate of the mount fetch above).
  useEffect(() => {
    if (liveSignal > 0) void refresh();
  }, [liveSignal, refresh]);

  return { data, loading, error, refresh };
}

export interface LivePollingOptions<T, E> {
  /** Apply an event to the current data. Return the new data, or `null` to say
   *  "I can't apply this" — which triggers a full refetch. */
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
 * `liveSignal++`, which refetches the whole list — 200 full ingestion runs. That
 * was fine when a push meant "a run started" or "a run finished" (twice per
 * run), but live step reporting emits one per step, so a single run would
 * trigger ~50 full-list refetches, and a watcher produces them continuously.
 *
 * Here an event carries the delta (< 1 KB) and `patch` applies it locally. A
 * refetch happens only when `patch` returns null — meaning the event refers to
 * something not in the current data, e.g. a run that started after the last
 * fetch — or when `reconcileMs` has elapsed, which bounds any drift caused by
 * a dropped message.
 */
export function useLivePolling<T, E>(
  load: () => Promise<T>,
  auto: boolean,
  lastEvent: E | null,
  { patch, reconcileMs = 30000, intervalMs = REFRESH_MS }: LivePollingOptions<T, E>,
): PollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;
  const lastFetchRef = useRef(0);
  const patchRef = useRef(patch);
  patchRef.current = patch;

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await loadRef.current();
      setData(result);
      setError(null);
      lastFetchRef.current = Date.now();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    if (!auto) return undefined;
    const id = setInterval(() => void refresh(), intervalMs);
    return () => clearInterval(id);
  }, [auto, refresh, intervalMs]);

  useEffect(() => {
    if (lastEvent == null) return;
    // Reconcile first: if we are overdue for a full read, take it rather than
    // patching onto data that may already have diverged.
    if (Date.now() - lastFetchRef.current > reconcileMs) {
      void refresh();
      return;
    }
    setData((current) => {
      const patched = patchRef.current(current, lastEvent);
      if (patched === null) {
        // The event is about something we don't have. Defer the refetch out of
        // the state updater — calling it inline would fire during render.
        queueMicrotask(() => void refresh());
        return current;
      }
      return patched;
    });
  }, [lastEvent, refresh, reconcileMs]);

  return { data, loading, error, refresh };
}
