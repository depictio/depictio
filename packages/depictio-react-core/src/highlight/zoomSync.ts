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
 * Per tile, off by default: the link icon in a tile's hover row adds it to
 * the sync or takes it out, and a section's header has one button for all its
 * tiles. Remembered in localStorage by tile index (stable across reloads, see
 * `index_from_tag`). A tile that joins fits the window in force; with none,
 * the tile it was turned on from sends its own first.
 *
 * Tiles that can take part register while mounted, so a section knows which
 * of its tiles its button reaches. A tile that cannot send a window (the 3D
 * model: a camera shows no residue range) registers as a follower only.
 *
 * Scope: one store per dashboard view, provided by `HighlightProvider` next to
 * the hover bus. Outside a provider (record panels, catalog previews) there is
 * nothing to sync with and no icon is shown.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
} from 'react';

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
  /** The source only scrolled: followers scroll and keep their width. */
  scrollOnly?: boolean;
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
  /** Whether tile `index` zooms with the others. */
  isMember(index: string): boolean;
  /**
   * Add tiles to the sync or take them out. Joining tiles fit the window in
   * force; with none, `lead` (else the first of them that can lead) sends its
   * own first.
   */
  setMembers(indices: readonly string[], on: boolean, lead?: string): void;
  /** The tile that sends its window after the last join, or null. */
  leader(): string | null;
  /** The window in force, or null. */
  current(): ZoomWindow | null;
  /** Put a window in force. Ignored from a tile that is not a member. */
  publish(w: ZoomWindow): void;
  /**
   * Say tile `index` can take part while mounted (`leads`: it can send a
   * window, not only follow one). Returns the matching unregister.
   */
  register(index: string, leads?: boolean): () => void;
  canSync(index: string): boolean;
  canLead(index: string): boolean;
  /** Every registered tile, in registration order. */
  registered(): string[];
  subscribe(listener: () => void): () => void;
  dispose(): void;
}

/** Where the members are remembered. */
export interface ZoomSyncPersistence {
  read(): string[];
  write(members: readonly string[]): void;
}

export const ZOOM_SYNC_STORAGE_KEY = 'depictio.zoom.sync';

/** The most tile indices remembered; the oldest joins are forgotten first. */
export const ZOOM_SYNC_MAX_REMEMBERED = 200;

/** localStorage, failing quietly (private windows, blocked storage, SSR). */
export const localZoomSyncPersistence: ZoomSyncPersistence = {
  read() {
    try {
      const raw = globalThis.localStorage?.getItem(ZOOM_SYNC_STORAGE_KEY);
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : [];
    } catch {
      return [];
    }
  },
  write(members) {
    try {
      if (members.length) {
        globalThis.localStorage?.setItem(ZOOM_SYNC_STORAGE_KEY, JSON.stringify(members));
      } else globalThis.localStorage?.removeItem(ZOOM_SYNC_STORAGE_KEY);
    } catch {
      // Not remembered: the sync still works for this page.
    }
  },
};

export function createZoomSyncStore(
  persistence: ZoomSyncPersistence = localZoomSyncPersistence,
): ZoomSyncStore {
  // Insertion order is join order, so the cap drops the oldest.
  const members = new Set(persistence.read());
  // Mount count and whether the tile can lead, by index: a tile drawn twice
  // (a floating copy) stays registered until both are gone.
  const registry = new Map<string, { count: number; leads: boolean }>();
  let lead: string | null = null;
  let current: ZoomWindow | null = null;
  const listeners = new Set<() => void>();
  const notify = () => {
    for (const l of [...listeners]) l();
  };
  const canLead = (index: string) => registry.get(index)?.leads ?? false;
  return {
    isMember: (index) => members.has(index),
    setMembers(indices, on, by) {
      const changed = indices.filter((i) => members.has(i) !== on);
      if (!changed.length) return;
      if (on) {
        // The window in force holds only while a tile that sent it is still in.
        const held = current !== null && members.has(current.sourceIndex);
        for (const i of changed) {
          members.delete(i);
          members.add(i);
        }
        while (members.size > ZOOM_SYNC_MAX_REMEMBERED) {
          members.delete(members.values().next().value as string);
        }
        if (held) lead = null;
        else {
          current = null;
          lead =
            by !== undefined && changed.includes(by)
              ? by
              : (changed.find(canLead) ?? changed[0] ?? null);
        }
      } else {
        for (const i of changed) members.delete(i);
        lead = null;
        // A window kept with nobody left would pull the next joiner back.
        if (!members.size) current = null;
      }
      persistence.write([...members]);
      notify();
    },
    leader: () => lead,
    current: () => current,
    publish(w) {
      if (!members.has(w.sourceIndex) || sameWindow(current, w)) return;
      current = { ...w };
      notify();
    },
    register(index, leads = true) {
      const entry = registry.get(index);
      if (entry) {
        entry.count += 1;
        entry.leads = entry.leads || leads;
      } else registry.set(index, { count: 1, leads });
      notify();
      let done = false;
      return () => {
        if (done) return;
        done = true;
        const e = registry.get(index);
        if (!e) return;
        e.count -= 1;
        if (e.count <= 0) registry.delete(index);
        notify();
      };
    },
    canSync: (index) => registry.has(index),
    canLead,
    registered: () => [...registry.keys()],
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    dispose() {
      listeners.clear();
      registry.clear();
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
 * One tile's switch: `available` once the tile has registered (it can take
 * part, inside a provider), `member` re-renders the caller when it flips.
 */
export function useZoomSyncMember(index: string | undefined): {
  available: boolean;
  member: boolean;
  setMember: (on: boolean) => void;
} {
  const store = useContext(ZoomSyncContext);
  const subscribe = store ? store.subscribe : noopSubscribe;
  const available = useSyncExternalStore(
    subscribe,
    store && index ? () => store.canSync(index) : offSnapshot,
    offSnapshot,
  );
  const member = useSyncExternalStore(
    subscribe,
    store && index ? () => store.isMember(index) : offSnapshot,
    offSnapshot,
  );
  const setMember = useCallback(
    (on: boolean) => {
      if (store && index) store.setMembers([index], on, index);
    },
    [store, index],
  );
  return { available, member, setMember };
}

/**
 * The tiles that can take part now, re-rendering the caller only when one
 * registers or leaves (a section header deciding whether to offer its button).
 */
export function useZoomSyncRegistered(): ReadonlySet<string> {
  const store = useContext(ZoomSyncContext);
  const text = useSyncExternalStore(
    store ? store.subscribe : noopSubscribe,
    () => (store ? store.registered().sort().join('\u0000') : ''),
    () => '',
  );
  return useMemo(() => new Set(text ? text.split('\u0000') : []), [text]);
}

export type ZoomSyncGroupState = 'none' | 'some' | 'all';

/**
 * A group of tiles' switch (a section's button): `tiles` are those of
 * `indices` that can take part now, in their order; `state` says how many of
 * them are in. Turning the group on leads from its first tile that can lead.
 */
export function useZoomSyncGroup(indices: readonly string[]): {
  tiles: string[];
  state: ZoomSyncGroupState;
  setAll: (on: boolean) => void;
} {
  const store = useContext(ZoomSyncContext);
  // A string snapshot: equal by value, so an unrelated window re-renders nothing.
  const snapshot = useSyncExternalStore(
    store ? store.subscribe : noopSubscribe,
    () => {
      if (!store) return '';
      const tiles = indices.filter((i) => store.canSync(i));
      const on = tiles.filter((i) => store.isMember(i)).length;
      const state = on === 0 ? 'none' : on === tiles.length ? 'all' : 'some';
      return `${state}\u0001${tiles.join('\u0000')}`;
    },
    () => '',
  );
  const [stateText = 'none', tilesText = ''] = snapshot.split('\u0001');
  const tiles = useMemo(() => (tilesText ? tilesText.split('\u0000') : []), [tilesText]);
  const setAll = useCallback(
    (on: boolean) => {
      if (!store || !tiles.length) return;
      store.setMembers(tiles, on, tiles.find((i) => store.canLead(i)));
    },
    [store, tiles],
  );
  return { tiles, state: stateText as ZoomSyncGroupState, setAll };
}

/** What a renderer hands its residue panel to take part in zoom sync. */
export interface ZoomSyncHandle {
  store: ZoomSyncStore;
  peer: ZoomPeer;
}

/**
 * The handle for one tile, or null outside a provider or with `enabled`
 * false (an axis sync cannot follow: per-protein scales, chains of a
 * complex). While there is a handle, the tile is registered, so its hover
 * icon and its section's button show. The panel reads membership at each
 * move, so joining or leaving re-renders no panel. `leads` false: the tile
 * only follows (it cannot say which residues it shows).
 */
export function useZoomSyncHandle(
  index: string | undefined,
  entity: string | null | undefined,
  positionColumn: string | null | undefined,
  enabled = true,
  leads = true,
): ZoomSyncHandle | null {
  const store = useContext(ZoomSyncContext);
  const handle = useMemo(
    () =>
      store && index && enabled
        ? { store, peer: { index, entity: entity ?? null, positionColumn: positionColumn ?? null } }
        : null,
    [store, index, entity, positionColumn, enabled],
  );
  const on = handle !== null;
  useEffect(() => {
    if (!on || !store || !index) return undefined;
    return store.register(index, leads);
  }, [on, store, index, leads]);
  return handle;
}
