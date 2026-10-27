/**
 * What the genome browser tile last rendered, for the metadata panel.
 *
 * The panel (popover and inspector Info tab) lives outside the tile and has no
 * handle on its payload, so the tile writes it here, keyed by dashboard id and
 * component index, and `MetadataBody` reads it with `useGenomeTracks`. In-memory
 * and never a filter: writing changes nothing any tile fetches. An entry is
 * kept when the tile unmounts (a `LazyMount` scrolling away), so the panel
 * still shows the last known tracks.
 */
import { useCallback, useRef, useSyncExternalStore } from 'react';

import type { JBrowseSessionResponse } from '../../api';

export interface GenomeTracksEntry {
  dashboardId: string;
  index: string;
  /** Null until the first payload arrives (only the locus may be known). */
  payload: JBrowseSessionResponse | null;
  /** The visible locus ("chr8:1..2"), null before the view has blocks. */
  locus: string | null;
  /** Write order, so an index-only read picks the latest tile. */
  seq: number;
}

const entries = new Map<string, GenomeTracksEntry>();
const listeners = new Set<() => void>();
let seq = 0;

function keyOf(dashboardId: string, index: string): string {
  return `${dashboardId}::${index}`;
}

function write(
  dashboardId: string,
  index: string,
  patch: Partial<Pick<GenomeTracksEntry, 'payload' | 'locus'>>,
): void {
  const key = keyOf(dashboardId, index);
  const prev = entries.get(key);
  if (prev && (Object.keys(patch) as Array<keyof typeof patch>).every((k) => prev[k] === patch[k])) {
    return;
  }
  entries.set(key, {
    dashboardId,
    index,
    payload: prev?.payload ?? null,
    locus: prev?.locus ?? null,
    ...patch,
    seq: ++seq,
  });
  listeners.forEach((l) => l());
}

export function setGenomeTracksPayload(
  dashboardId: string,
  index: string,
  payload: JBrowseSessionResponse,
): void {
  write(dashboardId, index, { payload });
}

export function setGenomeTracksLocus(
  dashboardId: string,
  index: string,
  locus: string | null,
): void {
  write(dashboardId, index, { locus });
}

/** The entry of a tile. Without `dashboardId` (the panel only knows the
 *  component index) the most recently written entry with that index wins. */
export function getGenomeTracks(index: string, dashboardId?: string): GenomeTracksEntry | null {
  if (dashboardId) return entries.get(keyOf(dashboardId, index)) ?? null;
  let best: GenomeTracksEntry | null = null;
  for (const entry of entries.values()) {
    if (entry.index === index && (!best || entry.seq > best.seq)) best = entry;
  }
  return best;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The tile's last render, re-read whenever it writes. */
export function useGenomeTracks(index: string, dashboardId?: string): GenomeTracksEntry | null {
  const snapshot = useCallback(() => getGenomeTracks(index, dashboardId), [index, dashboardId]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

/**
 * Sample → track colour over every genome browser tile of a dashboard, from
 * the manifest colours their payloads carry (a recipe colouring by design
 * group gives every library of a group one colour). Another tile drawing the
 * same samples (a genome view's lanes) reads it to wear the same colours. The
 * first tile written wins a sample two tiles colour differently. Without
 * `dashboardId` (a tile that is not handed one), the dashboard of the latest
 * write: the one on screen.
 */
export function trackSampleColours(dashboardId?: string): Record<string, string> {
  const out: Record<string, string> = {};
  let dashboard = dashboardId;
  if (dashboard === undefined) {
    let latest: GenomeTracksEntry | null = null;
    for (const e of entries.values()) if (e.payload && (!latest || e.seq > latest.seq)) latest = e;
    if (!latest) return out;
    dashboard = latest.dashboardId;
  }
  const ordered = [...entries.values()]
    .filter((e) => e.dashboardId === dashboard && e.payload)
    .sort((a, b) => a.seq - b.seq);
  for (const entry of ordered) {
    for (const row of entry.payload?.track_rows ?? []) {
      if (row.sample && row.color && !(row.sample in out)) out[row.sample] = row.color;
    }
  }
  return out;
}

/** `trackSampleColours`, re-read when a tile writes; the same object while
 *  the colours stay the same, so a consumer can key on it. */
export function useTrackSampleColours(dashboardId?: string): Record<string, string> {
  const cache = useRef<{ key: string; value: Record<string, string> }>({ key: '{}', value: {} });
  const snapshot = useCallback(() => {
    const value = trackSampleColours(dashboardId);
    const key = JSON.stringify(value);
    if (key !== cache.current.key) cache.current = { key, value };
    return cache.current.value;
  }, [dashboardId]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

/** Test seam: forget everything. */
export function resetGenomeTracks(): void {
  entries.clear();
  listeners.forEach((l) => l());
}
