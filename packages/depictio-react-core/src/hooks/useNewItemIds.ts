import { useEffect, useMemo, useRef } from 'react';

/**
 * Returns the set of IDs that are present in ``currentIds`` but were NOT
 * present in the previous snapshot — where "previous" is the value of
 * ``currentIds`` captured just before the most recent ``snapshotKey`` change.
 *
 * Two ref-based gates keep this safe in non-realtime contexts:
 *
 * - ``prevRef`` starts ``null`` and is seeded on the first render where
 *   ``currentIds`` becomes non-empty. The render that does the seed returns
 *   an empty set (initial dataset is the baseline, never "new").
 * - On every subsequent ``snapshotKey`` change ``prevRef`` is rotated to the
 *   value of ``currentIds`` *at the time of the key change* (typically still
 *   the pre-fetch state, since refreshTick fires before the data refetch
 *   completes). Once the refetch lands, ``currentIds`` differs from
 *   ``prevRef`` and the diff produces the new IDs.
 * - Filter edits and theme toggles leave ``snapshotKey`` unchanged, so
 *   ``prevRef`` is not rotated and the diff vs. the (now stale) baseline
 *   is computed by ``useMemo``. ``newIds`` will look noisy in that case —
 *   but consumers gate the highlight rendering on ``useTransientFlag(snapshotKey)``,
 *   which only flips on a true ``snapshotKey`` change, so filter-driven
 *   diffs are never visually applied.
 *
 * Generic in the ID type so callers can use raw strings (image relPaths)
 * or whatever shape their selection column produces (numbers, ObjectIds…).
 */
export function useNewItemIds<T>(
  currentIds: T[],
  snapshotKey: number | string | undefined,
): Set<T> {
  const prevRef = useRef<Set<T> | null>(null);

  const sig = currentIds.length + ':' + currentIds.slice(0, 32).join(',');
  const newIds = useMemo<Set<T>>(() => {
    const prev = prevRef.current;
    if (!prev) return new Set<T>();
    const out = new Set<T>();
    for (const id of currentIds) {
      if (!prev.has(id)) out.add(id);
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, snapshotKey]);

  // Seed the baseline on the first non-empty render. ``currentIds.length``
  // gates this to avoid capturing an empty Set as the baseline (which would
  // make the very first fetch look like "everything is new").
  useEffect(() => {
    if (prevRef.current === null && currentIds.length > 0) {
      prevRef.current = new Set(currentIds);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);

  // Rotate the baseline on each ``snapshotKey`` change. We capture
  // ``currentIds`` at the moment of the key flip — typically the pre-refetch
  // state — so the post-fetch render sees a non-empty diff.
  useEffect(() => {
    if (currentIds.length > 0) {
      prevRef.current = new Set(currentIds);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshotKey]);

  return newIds;
}

export default useNewItemIds;
