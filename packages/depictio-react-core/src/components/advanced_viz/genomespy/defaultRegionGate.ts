/**
 * Holding a locus tile's first fetch until the section's `default_region` lands.
 *
 * A locus section opens on the region its navigator (a `genome_view` with a
 * `default_region`) emits. But the navigator can only emit once it knows its
 * contigs, and every other tile of the section mounts in the same commit and
 * fetches straight away, with no region yet. So each coverage track and locus
 * view first read the whole genome (tens of thousands of rows, a Celery job and
 * a Plotly or WebGL upload), only to throw it away a moment later when the
 * region arrived and narrowed the fetch.
 *
 * The gate is a tiny process-wide registry rather than a new filter or context:
 * a navigator *announces* that it has a default region to emit while it
 * renders, *settles* once it has decided (emitted or not), and a follower asks
 * whether any navigator other than itself is still pending. The follower's
 * gate opens as soon as a region filter is in force, once every pending
 * navigator has settled without emitting, or after a timeout, whichever comes
 * first, so a navigator that never mounts (scrolled out of view, failed fetch)
 * cannot hold anything for longer than that.
 *
 * A navigator below the fold never renders (it sits behind `LazyMount`), so it
 * cannot announce itself before the tracks above the fold fetch. The dashboard
 * layout therefore *pre-announces* every navigator it holds from the stored
 * config at load time (`preannounceDefaultRegions`, via
 * `usePreannouncedDefaultRegions`). A pre-announced entry expires after the
 * timeout unless the navigator mounts and takes it over, and is cleared as
 * soon as the navigator settles.
 *
 * The decision is a pure function (`defaultRegionGateOpen`) so it can be tested
 * without a DOM; the hook only owns the subscription, the timer and the latch.
 */

import { useEffect, useReducer, useRef } from 'react';

import type { InteractiveFilter, StoredMetadata } from '../../../api';

/** How long a follower waits for a pending default region at most. */
export const DEFAULT_REGION_GATE_MS = 2000;

export type DefaultRegionEntry =
  /** `expiresAt` (ms) marks a pre-announcement from the dashboard layout: the
   *  navigator has not mounted yet, and may never (scrolled out of view). */
  | { state: 'pending'; expiresAt?: number }
  /** Emitted at `at` (ms): the filter is on its way through the host's state. */
  | { state: 'emitted'; at: number };

const entries = new Map<string, DefaultRegionEntry>();
/** Navigators that already decided this session: never pre-announced again. */
const settled = new Set<string>();
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of Array.from(listeners)) listener();
}

function isPreannounced(entry: DefaultRegionEntry | undefined): boolean {
  return entry?.state === 'pending' && entry.expiresAt !== undefined;
}

/** A navigator with a default region still to emit. Idempotent. */
export function announceDefaultRegion(index: string): void {
  const current = entries.get(index);
  // Pending already, or emitted: either way there is nothing new to say. A
  // pre-announcement is taken over: the mounted navigator now owns the hold,
  // and it no longer expires.
  if (current && !isPreannounced(current)) return;
  entries.set(index, { state: 'pending' });
  if (!current) notify();
}

/** The navigator decided: `emitted` says whether it published a region. */
export function settleDefaultRegion(index: string, emitted: boolean, now = Date.now()): void {
  settled.add(index);
  if (emitted) entries.set(index, { state: 'emitted', at: now });
  else entries.delete(index);
  notify();
}

/**
 * The dashboard layout's announcement for navigators that have not mounted.
 *
 * Each index is held as pending until `now + timeoutMs`, then dropped unless
 * its navigator mounted and took it over (`announceDefaultRegion`). Indexes
 * already known (announced, emitted, or settled earlier) are left alone.
 */
export function preannounceDefaultRegions(
  indexes: readonly string[],
  now = Date.now(),
  timeoutMs = DEFAULT_REGION_GATE_MS,
): void {
  const added: string[] = [];
  for (const index of indexes) {
    if (entries.has(index) || settled.has(index)) continue;
    entries.set(index, { state: 'pending', expiresAt: now + timeoutMs });
    added.push(index);
  }
  if (!added.length) return;
  notify();
  setTimeout(() => expirePreannounced(added), timeoutMs + 10);
}

/** Drop the pre-announcements among `indexes` whose navigator never showed up. */
function expirePreannounced(indexes: readonly string[], now = Date.now()): void {
  let changed = false;
  for (const index of indexes) {
    const entry = entries.get(index);
    if (entry?.state === 'pending' && entry.expiresAt !== undefined && now >= entry.expiresAt) {
      entries.delete(index);
      changed = true;
    }
  }
  if (changed) notify();
}

/**
 * The navigators a dashboard layout holds, read off the stored config: a
 * `genome_view` that publishes its region (`region_filter_enabled` not off)
 * and declares a `default_region`. Same test as the renderer's own
 * `hasDefaultRegion`.
 */
export function defaultRegionNavigators(metadataList: readonly StoredMetadata[]): string[] {
  const out: string[] = [];
  for (const m of metadataList) {
    if (m.component_type !== 'advanced_viz' || m.viz_kind !== 'genome_view') continue;
    const config = (m.config || {}) as { default_region?: unknown; region_filter_enabled?: unknown };
    if (config.region_filter_enabled === false) continue;
    if (typeof config.default_region !== 'string' || !config.default_region.trim()) continue;
    out.push(m.index);
  }
  return out;
}

/**
 * Pre-announce a layout's navigators before its tiles render.
 *
 * Runs during render, not in an effect, for the same reason the navigator
 * announces itself while rendering: the followers mounted in this commit read
 * the gate in their own render. Once per distinct set of navigators; `enabled`
 * is false on read-only hosts, where no navigator publishes a region.
 */
export function usePreannouncedDefaultRegions(
  metadataList: readonly StoredMetadata[],
  enabled: boolean,
): void {
  const doneKey = useRef<string | null>(null);
  const navigators = enabled ? defaultRegionNavigators(metadataList) : [];
  const key = navigators.join('\u0000');
  if (navigators.length && doneKey.current !== key) {
    doneKey.current = key;
    preannounceDefaultRegions(navigators);
  }
}

/** The navigator unmounted: nothing to wait for any more. */
export function withdrawDefaultRegion(index: string): void {
  if (!entries.delete(index)) return;
  notify();
}

export function defaultRegionEntries(): ReadonlyMap<string, DefaultRegionEntry> {
  return entries;
}

export function subscribeDefaultRegions(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Test hook: forget every announcement. */
export function resetDefaultRegionGate(): void {
  entries.clear();
  settled.clear();
  notify();
}

function hasValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  return value !== null && value !== undefined && value !== '';
}

/** True when any tile's region (a `genome_selection` filter) is in force. */
export function regionFilterActive(filters: readonly InteractiveFilter[] | null | undefined): boolean {
  return Boolean(filters?.some((f) => f.source === 'genome_selection' && hasValue(f.value)));
}

export interface GateInput {
  entries: ReadonlyMap<string, DefaultRegionEntry>;
  /** The asking tile's own index: a navigator never waits on itself. */
  ownIndex: string | null | undefined;
  filters: readonly InteractiveFilter[] | null | undefined;
  /** When the asking tile started waiting, and the current time (ms). */
  startedAt: number;
  now: number;
  timeoutMs?: number;
}

/**
 * Whether a follower may run its first fetch now.
 *
 * Open when a region is already in force, when the timeout has passed, or when
 * no other navigator is pending and none emitted within the timeout (an
 * emitted region is still travelling through the host's filter state, so the
 * follower waits for it to show up rather than fetching the whole genome one
 * render too early).
 */
export function defaultRegionGateOpen(input: GateInput): boolean {
  const timeoutMs = input.timeoutMs ?? DEFAULT_REGION_GATE_MS;
  if (regionFilterActive(input.filters)) return true;
  if (input.now - input.startedAt >= timeoutMs) return true;
  for (const [index, entry] of input.entries) {
    if (index === input.ownIndex) continue;
    if (entry.state === 'pending') {
      // A pre-announced navigator that never mounted stops holding at expiry.
      if (entry.expiresAt !== undefined && input.now >= entry.expiresAt) continue;
      return false;
    }
    if (input.now - entry.at < timeoutMs) return false;
  }
  return true;
}

/**
 * `defaultRegionGateOpen` as a latch: once open it stays open for the life of
 * the tile, so a reader who later clears the region is not held again.
 * `enabled: false` opens it at once.
 */
export function useDefaultRegionGate(
  filters: readonly InteractiveFilter[] | null | undefined,
  ownIndex: string | null | undefined,
  enabled = true,
  timeoutMs = DEFAULT_REGION_GATE_MS,
): boolean {
  const startedAt = useRef(Date.now());
  const openRef = useRef(false);
  const [, rerender] = useReducer((n: number) => n + 1, 0);

  if (!openRef.current) {
    openRef.current =
      !enabled ||
      defaultRegionGateOpen({
        entries,
        ownIndex,
        filters,
        startedAt: startedAt.current,
        now: Date.now(),
        timeoutMs,
      });
  }
  const open = openRef.current;

  useEffect(() => {
    if (open) return undefined;
    const off = subscribeDefaultRegions(rerender);
    const remaining = Math.max(0, timeoutMs - (Date.now() - startedAt.current));
    const timer = setTimeout(rerender, remaining + 10);
    return () => {
      off();
      clearTimeout(timer);
    };
  }, [open, timeoutMs]);

  return open;
}
