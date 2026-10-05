/**
 * Hover highlight bus: "the reader is pointing at residues 120-125 of P04637".
 *
 * A hover is not a filter. It changes nothing any tile fetches, it lives for
 * as long as the pointer does and it fires dozens of times a second, so
 * routing it through the dashboard's filter list would refetch every tile on
 * every mouse move. Instead the protein tiles (molecule_3d, msa,
 * sequence_track, lollipop, profile) share this small in-memory bus: one
 * publisher at a time, coalesced to one event per animation frame, and a
 * React hook that re-renders only the tiles that subscribe.
 *
 * Scope: one bus per dashboard view, created by `HighlightProvider` (mounted
 * once around the dashboard grid, the editor included). Outside a provider
 * (catalog preview, record panels, tests) `useHighlight` returns null and
 * the publish function is a no-op, so a renderer needs no guard of its own.
 *
 * Positions are residue numbers (1-based); `end` defaults to `start`.
 */
import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';

import { createOpeningEntityStore, OpeningEntityContext } from './openingEntity';

export type HighlightEvent = {
  /** Index of the tile that published it; a tile ignores its own events. */
  sourceIndex: string;
  /** The protein (or family) the residues belong to, when the source knows. */
  entity?: string;
  /** Chain of a multi-chain structure the positions are numbered in (residue
   *  tables number a complex per chain). Unset: single chain, or unknown. */
  chain?: string;
  start: number;
  /** Inclusive; defaults to `start`. */
  end?: number;
  /** Row identifiers under the pointer (e.g. a variant's label), for tiles
   *  that ring rows rather than positions. */
  rowKeys?: string[];
  /** Column the positions are values of, when the source knows it (a
   *  profile's x column). Consumers that only draw on a matching axis (the
   *  profile) compare it to their own column; unset means residue numbers. */
  positionColumn?: string;
};

/** A publish call without the source, when the hook binds it. */
export type HighlightPayload = Omit<HighlightEvent, 'sourceIndex'> & { sourceIndex?: string };

export interface HighlightBus {
  /** Queue an event (or `null` to clear) for the next frame. With
   *  `sourceIndex`, a `null` only clears an event that source published, so a
   *  tile's pointer-leave never wipes the hover another tile just set. */
  publish(ev: HighlightEvent | null, sourceIndex?: string): void;
  /** The event in force (what subscribers render). */
  get(): HighlightEvent | null;
  subscribe(listener: () => void): () => void;
  /** Cancel a pending frame and drop every listener. */
  dispose(): void;
}

export interface HighlightScheduler {
  schedule(cb: () => void): unknown;
  cancel(handle: unknown): void;
}

const frameScheduler: HighlightScheduler = {
  schedule: (cb) =>
    typeof requestAnimationFrame === 'function'
      ? requestAnimationFrame(cb)
      : setTimeout(cb, 16),
  cancel: (handle) => {
    if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(handle as number);
    else clearTimeout(handle as ReturnType<typeof setTimeout>);
  },
};

function sameKeys(a?: string[], b?: string[]): boolean {
  if (a === b) return true;
  if (!a || !b || a.length !== b.length) return false;
  return a.every((k, i) => k === b[i]);
}

/** Two events that would draw the same thing (subscribers skip the render). */
export function sameHighlight(a: HighlightEvent | null, b: HighlightEvent | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.sourceIndex === b.sourceIndex &&
    a.entity === b.entity &&
    a.chain === b.chain &&
    a.start === b.start &&
    (a.end ?? a.start) === (b.end ?? b.start) &&
    a.positionColumn === b.positionColumn &&
    sameKeys(a.rowKeys, b.rowKeys)
  );
}

/**
 * A bus coalescing publishes to one per frame: the last event queued before
 * the frame wins, and subscribers hear about it only when it differs from
 * the one in force.
 */
export function createHighlightBus(scheduler: HighlightScheduler = frameScheduler): HighlightBus {
  let current: HighlightEvent | null = null;
  let pending: HighlightEvent | null = null;
  let handle: unknown = null;
  const listeners = new Set<() => void>();

  const flush = () => {
    handle = null;
    if (sameHighlight(current, pending)) return;
    current = pending;
    for (const l of [...listeners]) l();
  };

  return {
    publish(ev, sourceIndex) {
      if (ev === null && sourceIndex !== undefined) {
        // Clear only what this source put up (queued or in force).
        const shown = handle !== null ? pending : current;
        if (shown && shown.sourceIndex !== sourceIndex) return;
      }
      pending = ev ? { ...ev, end: ev.end ?? ev.start } : null;
      if (handle === null) handle = scheduler.schedule(flush);
    },
    get: () => current,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    dispose() {
      if (handle !== null) scheduler.cancel(handle);
      handle = null;
      listeners.clear();
      current = null;
      pending = null;
    },
  };
}

/** What a tile should draw for the event in force: `null` when there is
 *  none or it is the tile's own (a publisher ignores its own events). */
export function highlightFor(
  ev: HighlightEvent | null,
  ownIndex: string | undefined,
): HighlightEvent | null {
  if (!ev) return null;
  if (ownIndex !== undefined && ev.sourceIndex === ownIndex) return null;
  return ev;
}

// ---------------------------------------------------------------------------
// React glue
// ---------------------------------------------------------------------------

const HighlightContext = createContext<HighlightBus | null>(null);

/**
 * One bus for the tiles below it. Mount once per dashboard view (it sits in
 * `DashboardGrid`). Nest-safe: under another provider it reuses that bus, so
 * a host that also wraps the whole page (to reach pinned sections rendered
 * outside the grid) keeps one scope rather than splitting it in two.
 */
export function HighlightProvider({ children }: { children?: ReactNode }) {
  const parent = useContext(HighlightContext);
  const parentOpening = useContext(OpeningEntityContext);
  const [own] = useState(() => (parent ? null : createHighlightBus()));
  // The protein tiles' opening-entity agreement shares the bus's scope.
  const [ownOpening] = useState(() => (parentOpening ? null : createOpeningEntityStore()));
  useEffect(() => () => own?.dispose(), [own]);
  useEffect(() => () => ownOpening?.dispose(), [ownOpening]);
  return createElement(
    HighlightContext.Provider,
    { value: parent ?? own },
    createElement(OpeningEntityContext.Provider, { value: parentOpening ?? ownOpening }, children),
  );
}

const noopSubscribe = () => () => {};
const nullSnapshot = () => null;

/**
 * The highlight in force, re-rendering the caller only when it changes.
 * Pass the tile's own index to ignore the events it published itself, and
 * `enabled: false` for a tile that is not on a residue axis right now (it
 * then does not subscribe at all, so a hover elsewhere never re-renders it).
 * Returns null outside a provider.
 */
export function useHighlight(ownIndex?: string, enabled = true): HighlightEvent | null {
  const ctx = useContext(HighlightContext);
  const bus = enabled ? ctx : null;
  const ev = useSyncExternalStore(
    bus ? bus.subscribe : noopSubscribe,
    bus ? bus.get : nullSnapshot,
    nullSnapshot,
  );
  return highlightFor(ev, ownIndex);
}

/**
 * A stable `publishHighlight(ev | null)` for one tile. The bound
 * `sourceIndex` fills events that omit it, and `null` clears only this
 * tile's own highlight. A no-op outside a provider.
 */
export function usePublishHighlight(
  sourceIndex?: string,
): (ev: HighlightPayload | null) => void {
  const bus = useContext(HighlightContext);
  return useCallback(
    (ev: HighlightPayload | null) => {
      if (!bus) return;
      if (ev === null) {
        bus.publish(null, sourceIndex);
        return;
      }
      const src = ev.sourceIndex ?? sourceIndex;
      if (src === undefined) return;
      bus.publish({ ...ev, sourceIndex: src });
    },
    [bus, sourceIndex],
  );
}
