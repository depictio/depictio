import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import type { StoredMetadata } from '../api';

/** Per-component load lifecycle, as reported by each data renderer.
 *  ``deferred``/off-screen components simply never appear in the registry —
 *  they are counted as pending against the metadata-derived total. */
export type ComponentLoadStatus = 'loading' | 'ready' | 'error';

/**
 * Component types that fetch data and report a load lifecycle. The dashboard
 * total is computed from the metadata restricted to these (plus cards, handled
 * separately), so it stays honest even before off-screen panels mount: a type
 * that never reports would otherwise keep the count from ever completing.
 * Keep in sync with the renderers wired to ``useReportLoadStatus``.
 */
export const TRACKED_LOAD_TYPES: ReadonlySet<string> = new Set([
  'figure',
  'table',
  'map',
  'image',
  'advanced_viz',
]);

interface LoadingActions {
  report: (index: string, status: ComponentLoadStatus) => void;
  unregister: (index: string) => void;
}

/**
 * Carries the current component's index down to a deep child so it can report
 * its load status without threading the index through every intermediate
 * renderer. Used by the shared ``AdvancedVizFrame`` (one funnel for ~20 viz
 * kinds) — the dispatch sets it, the frame reads it.
 */
export const ComponentIndexContext = createContext<string | null>(null);

// Split into two contexts on purpose: renderers consume only the *actions*
// (a stable object) so a status change elsewhere never re-renders every panel;
// the *state* context re-renders only its readers (the progress bar).
const LoadingActionsContext = createContext<LoadingActions | null>(null);
const LoadingStateContext = createContext<Record<string, ComponentLoadStatus>>({});

/**
 * Holds the live map of component-index → load status. Wrap the dashboard view
 * (grid + progress bar) in it. Absent (no provider) → the reporting hook is a
 * no-op, so the editor and other hosts that don't need the aggregate are
 * unaffected.
 */
export const DashboardLoadingProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [statuses, setStatuses] = useState<Record<string, ComponentLoadStatus>>({});

  const report = useCallback((index: string, status: ComponentLoadStatus) => {
    setStatuses((prev) => (prev[index] === status ? prev : { ...prev, [index]: status }));
  }, []);
  const unregister = useCallback((index: string) => {
    setStatuses((prev) => {
      if (!(index in prev)) return prev;
      const next = { ...prev };
      delete next[index];
      return next;
    });
  }, []);
  const actions = useMemo<LoadingActions>(() => ({ report, unregister }), [report, unregister]);

  return (
    <LoadingActionsContext.Provider value={actions}>
      <LoadingStateContext.Provider value={statuses}>{children}</LoadingStateContext.Provider>
    </LoadingActionsContext.Provider>
  );
};

/**
 * Report a data component's current load status to the dashboard registry.
 * Pass ``null`` while the component is off-screen / not yet loading so it stays
 * counted as pending rather than as an active load. Cleans up on unmount.
 */
export function useReportLoadStatus(index: string, status: ComponentLoadStatus | null): void {
  const actions = useContext(LoadingActionsContext);
  useEffect(() => {
    if (!actions) return;
    if (status == null) {
      actions.unregister(index);
      return;
    }
    actions.report(index, status);
  }, [actions, index, status]);
  useEffect(() => () => actions?.unregister(index), [actions, index]);
}

export interface DashboardLoadSummary {
  /** Panels finished (data rendered). Includes the whole card group when its
   *  bulk-compute has settled. */
  ready: number;
  /** Panels actively fetching right now. */
  loading: number;
  /** Panels that errored on their initial load. */
  error: number;
  /** Panels neither ready nor loading — chiefly off-screen ones deferred until
   *  scrolled into view. */
  pending: number;
  /** All tracked panels + cards. */
  total: number;
  /** ``ready / total`` in [0, 1]. */
  fraction: number;
}

/**
 * Aggregate the registry against the dashboard metadata into counts for the
 * progress bar. Cards are treated as one group keyed off ``cardsLoading`` (they
 * load together via the bulk-compute endpoint, not per-panel).
 */
export function useDashboardLoadSummary(
  metadataList: StoredMetadata[],
  cardsLoading: boolean,
): DashboardLoadSummary {
  const statuses = useContext(LoadingStateContext);
  return useMemo(() => {
    let ready = 0;
    let loading = 0;
    let error = 0;
    let dataTotal = 0;
    let cardCount = 0;
    for (const m of metadataList) {
      if (m.component_type === 'card') {
        cardCount += 1;
        continue;
      }
      if (!TRACKED_LOAD_TYPES.has(m.component_type)) continue;
      dataTotal += 1;
      const s = statuses[m.index];
      if (s === 'ready') ready += 1;
      else if (s === 'loading') loading += 1;
      else if (s === 'error') error += 1;
    }
    if (cardCount > 0) {
      if (cardsLoading) loading += cardCount;
      else ready += cardCount;
    }
    const total = dataTotal + cardCount;
    const pending = Math.max(0, total - ready - loading - error);
    const fraction = total > 0 ? ready / total : 0;
    return { ready, loading, error, pending, total, fraction };
  }, [statuses, metadataList, cardsLoading]);
}
