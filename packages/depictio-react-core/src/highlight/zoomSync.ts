/**
 * Zoom sync: "the residue tiles of this dashboard show the same residues".
 *
 * The protein panels that scroll a residue axis (sequence track, secondary
 * structure, MSA, HMM logo, domain architecture) each zoom on their own: a
 * width per residue plus a horizontal scroll. With sync on, the tile the
 * reader zooms or scrolls publishes the residue window it shows, and every
 * other tile on the same axis fits that window to its own width. Two panes of
 * different widths then show the same residues, not the same pixels.
 *
 * "Same axis" is the rule the hover bus already follows: the same position
 * column, and the same entity when both tiles know theirs. A tile without an
 * entity (the domain architecture, every protein at once) follows any window.
 *
 * Windows are in residue coordinates, residue `p` spanning `[p, p + 1)`. A
 * window marked `fit` means the source shows its whole axis; followers then
 * fit theirs, whatever its length.
 *
 * Off by default. One setting for the whole view, switched from any residue
 * tile's controls and remembered in localStorage. The tile whose switch turned
 * it on leads: its window goes out first.
 *
 * Scope: one store per dashboard view, provided by `HighlightProvider` next to
 * the hover bus. Outside a provider (record panels, catalog previews) there is
 * nothing to sync with and the switch is not shown.
 */
import { createContext, useCallback, useContext, useMemo, useSyncExternalStore } from 'react';

export interface ZoomWindow {
  /** Index of the tile that published it; a tile ignores its own windows. */
  sourceIndex: string;
  entity?: string;
  /** Column the positions are values of, when the source knows it. */
  positionColumn?: string;
  /** Residue coordinate at the left edge of the source's view. */
  start: number;
  /** Residue coordinate at its right edge. */
  end: number;
  /** The source shows its whole axis: followers fit theirs. */
  fit: boolean;
}

/** What a tile says about its own axis. */
export interface ZoomPeer {
  index: string;
  entity?: string | null;
  positionColumn?: string | null;
}

/** Whether `peer` should follow `w`: another tile's window, on its axis. */
export function followsWindow(w: ZoomWindow | null, peer: ZoomPeer): w is ZoomWindow {
  if (!w || w.sourceIndex === peer.index) return false;
  if (w.positionColumn && peer.positionColumn && w.positionColumn !== peer.positionColumn) {
    return false;
  }
  if (w.entity && peer.entity && w.entity !== peer.entity) return false;
  return true;
}

/** Residue coordinates closer than this are the same edge. */
const EDGE_EPS = 1e-3;

/** Two windows that would put every follower in the same place. */
export function sameWindow(a: ZoomWindow | null, b: ZoomWindow | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.sourceIndex === b.sourceIndex &&
    a.entity === b.entity &&
    a.positionColumn === b.positionColumn &&
    a.fit === b.fit &&
    Math.abs(a.start - b.start) < EDGE_EPS &&
    Math.abs(a.end - b.end) < EDGE_EPS
  );
}

export interface ZoomSyncStore {
  isEnabled(): boolean;
  /** Turn sync on or off. `by` is the tile whose switch did it: it leads. */
  setEnabled(on: boolean, by?: string): void;
  /** The tile that last turned sync on, or null. */
  leader(): string | null;
  /** The window in force, or null (always null while sync is off). */
  current(): ZoomWindow | null;
  /** Put a window in force. Ignored while sync is off. */
  publish(w: ZoomWindow): void;
  subscribe(listener: () => void): () => void;
  dispose(): void;
}

/** Where the switch is remembered. */
export interface ZoomSyncPersistence {
  read(): boolean;
  write(on: boolean): void;
}

export const ZOOM_SYNC_STORAGE_KEY = 'depictio.zoom.sync';

/** localStorage, failing quietly (private windows, blocked storage, SSR). */
export const localZoomSyncPersistence: ZoomSyncPersistence = {
  read() {
    try {
      return globalThis.localStorage?.getItem(ZOOM_SYNC_STORAGE_KEY) === '1';
    } catch {
      return false;
    }
  },
  write(on) {
    try {
      if (on) globalThis.localStorage?.setItem(ZOOM_SYNC_STORAGE_KEY, '1');
      else globalThis.localStorage?.removeItem(ZOOM_SYNC_STORAGE_KEY);
    } catch {
      // Not remembered: the switch still works for this page.
    }
  },
};

export function createZoomSyncStore(
  persistence: ZoomSyncPersistence = localZoomSyncPersistence,
): ZoomSyncStore {
  let enabled = persistence.read();
  let lead: string | null = null;
  let current: ZoomWindow | null = null;
  const listeners = new Set<() => void>();
  const notify = () => {
    for (const l of [...listeners]) l();
  };
  return {
    isEnabled: () => enabled,
    setEnabled(on, by) {
      if (on === enabled) return;
      enabled = on;
      lead = on ? (by ?? null) : null;
      // A window from before the switch went off would pull a tile back.
      current = null;
      persistence.write(on);
      notify();
    },
    leader: () => lead,
    current: () => current,
    publish(w) {
      if (!enabled || sameWindow(current, w)) return;
      current = { ...w };
      notify();
    },
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

// ---------------------------------------------------------------------------
// React glue
// ---------------------------------------------------------------------------

export const ZoomSyncContext = createContext<ZoomSyncStore | null>(null);

/** The view's store, or null outside a `HighlightProvider`. */
export function useZoomSyncStore(): ZoomSyncStore | null {
  return useContext(ZoomSyncContext);
}

const noopSubscribe = () => () => {};
const offSnapshot = () => false;

/**
 * The switch's state: `available` is false outside a provider (nothing to
 * sync with), `enabled` re-renders the caller when any tile flips it.
 */
export function useZoomSyncSwitch(): {
  available: boolean;
  enabled: boolean;
  setEnabled: (on: boolean, by?: string) => void;
} {
  const store = useContext(ZoomSyncContext);
  const enabled = useSyncExternalStore(
    store ? store.subscribe : noopSubscribe,
    store ? store.isEnabled : offSnapshot,
    offSnapshot,
  );
  const setEnabled = useCallback(
    (on: boolean, by?: string) => store?.setEnabled(on, by),
    [store],
  );
  return { available: store !== null, enabled, setEnabled };
}

/** What a renderer hands its residue panel to take part in zoom sync. */
export interface ZoomSyncHandle {
  store: ZoomSyncStore;
  peer: ZoomPeer;
}

/**
 * The handle for one tile, or null outside a provider or with `enabled`
 * false (an axis sync cannot follow: per-protein scales, chains of a
 * complex). The handle is there whether the switch is on or off; the panel
 * reads the switch at each move, so flipping it re-renders no panel.
 */
export function useZoomSyncHandle(
  index: string | undefined,
  entity: string | null | undefined,
  positionColumn: string | null | undefined,
  enabled = true,
): ZoomSyncHandle | null {
  const store = useContext(ZoomSyncContext);
  return useMemo(
    () =>
      store && index && enabled
        ? { store, peer: { index, entity: entity ?? null, positionColumn: positionColumn ?? null } }
        : null,
    [store, index, entity, positionColumn, enabled],
  );
}
