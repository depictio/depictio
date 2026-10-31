/**
 * View window: "the genome browser shows chr8:1,000-5,000 right now".
 *
 * The sibling of the hover bus for a window instead of a pointer. A genome
 * browser tile publishes the stretch of one contig it has on screen; genomic
 * plots on the same tab (the coverage track) fit their x axis to it. Like the
 * hover it is in-memory and never a filter: nothing any tile fetches changes,
 * so panning a browser does not refetch the dashboard.
 *
 * One window in force at a time, the last one published (a dashboard rarely
 * holds two genome browsers). The publisher debounces its own pan; the store
 * only drops repeats. A `null` publish with `sourceIndex` clears only a window
 * that source put up, so one browser unmounting never wipes another's.
 *
 * Positions are 1-based and inclusive, like the hover bus's.
 *
 * Scope: one store per dashboard view, provided by `HighlightProvider` next to
 * the hover bus. Outside a provider `useViewWindow` returns null and the
 * publish function is a no-op.
 */
import {
  createContext,
  useCallback,
  useContext,
  useSyncExternalStore,
} from 'react';

export type ViewWindowEvent = {
  /** Index of the tile that published it; a tile ignores its own windows. */
  sourceIndex: string;
  /** The contig the window is on. */
  entity: string;
  /** Other names of the contig (the browser's aliases for its canonical name). */
  entityAliases?: string[];
  start: number;
  /** Inclusive. */
  end: number;
};

/** A publish call without the source, when the hook binds it. */
export type ViewWindowPayload = Omit<ViewWindowEvent, 'sourceIndex'> & { sourceIndex?: string };

export interface ViewWindowStore {
  /** Put a window in force (or `null` to clear). With `sourceIndex`, a `null`
   *  only clears a window that source published. */
  publish(ev: ViewWindowEvent | null, sourceIndex?: string): void;
  get(): ViewWindowEvent | null;
  subscribe(listener: () => void): () => void;
  dispose(): void;
}

function sameAliases(a?: string[], b?: string[]): boolean {
  if (a === b) return true;
  if (!a || !b || a.length !== b.length) return false;
  return a.every((k, i) => k === b[i]);
}

/** Two windows that would put every follower in the same place. */
export function sameViewWindow(a: ViewWindowEvent | null, b: ViewWindowEvent | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.sourceIndex === b.sourceIndex &&
    a.entity === b.entity &&
    sameAliases(a.entityAliases, b.entityAliases) &&
    a.start === b.start &&
    a.end === b.end
  );
}

export function createViewWindowStore(): ViewWindowStore {
  let current: ViewWindowEvent | null = null;
  const listeners = new Set<() => void>();
  const notify = () => {
    for (const l of [...listeners]) l();
  };
  return {
    publish(ev, sourceIndex) {
      if (ev === null && sourceIndex !== undefined && current?.sourceIndex !== sourceIndex) return;
      if (sameViewWindow(current, ev)) return;
      current = ev;
      notify();
    },
    get: () => current,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    dispose() {
      listeners.clear();
      current = null;
    },
  };
}

/** The window a tile should follow: `null` when there is none or it is the
 *  tile's own. */
export function viewWindowFor(
  ev: ViewWindowEvent | null,
  ownIndex: string | undefined,
): ViewWindowEvent | null {
  if (!ev) return null;
  if (ownIndex !== undefined && ev.sourceIndex === ownIndex) return null;
  return ev;
}

export const ViewWindowContext = createContext<ViewWindowStore | null>(null);

const noopSubscribe = () => () => {};
const nullSnapshot = () => null;

/**
 * The window in force, re-rendering the caller only when it changes. Pass the
 * tile's own index to ignore its own windows, and `enabled: false` for a tile
 * that is not on a genomic axis right now (it then does not subscribe at all).
 * Returns null outside a provider.
 */
export function useViewWindow(ownIndex?: string, enabled = true): ViewWindowEvent | null {
  const ctx = useContext(ViewWindowContext);
  const store = enabled ? ctx : null;
  const ev = useSyncExternalStore(
    store ? store.subscribe : noopSubscribe,
    store ? store.get : nullSnapshot,
    nullSnapshot,
  );
  return viewWindowFor(ev, ownIndex);
}

/**
 * A stable `publishViewWindow(ev | null)` for one tile. The bound
 * `sourceIndex` fills events that omit it, and `null` clears only this tile's
 * own window. A no-op outside a provider.
 */
export function usePublishViewWindow(
  sourceIndex?: string,
): (ev: ViewWindowPayload | null) => void {
  const store = useContext(ViewWindowContext);
  return useCallback(
    (ev: ViewWindowPayload | null) => {
      if (!store) return;
      if (ev === null) {
        store.publish(null, sourceIndex);
        return;
      }
      const src = ev.sourceIndex ?? sourceIndex;
      if (src === undefined) return;
      store.publish({ ...ev, sourceIndex: src });
    },
    [store, sourceIndex],
  );
}
