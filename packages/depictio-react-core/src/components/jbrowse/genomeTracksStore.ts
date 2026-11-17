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

/** The colours a tile resolved for its tracks beyond the manifest's own: the
 *  ones `color_by` / `color_scale` computed. */
export interface GenomeTracksColours {
  /** Sample → the colour its track wears. */
  samples: Record<string, string>;
  /** Value of the `color_by` / `color_scale` column → colour. */
  groups: Record<string, string>;
  /** What the colours are keyed by, for another tile's legend; absent on a tile
   *  that does not say. */
  key?: GenomeTracksColourKey | null;
}

/** The scale behind `GenomeTracksColours`: the column, its values in scale
 *  order and the sample → value map, so a genome view can key its lanes the
 *  way the browser keys its tracks (a ramp for a `color_scale`). */
export interface GenomeTracksColourKey {
  column: string;
  /** Every value of the column the browser's tracks carry, in colour order. */
  values: string[];
  /** A sequential `color_scale` (a ramp), not one hue per value. */
  ordered: boolean;
  scheme: string | null;
  /** Sample → its value of the column. */
  sampleGroups: Record<string, string>;
}

export interface GenomeTracksEntry {
  dashboardId: string;
  index: string;
  /** Null until the first payload arrives (only the locus may be known). */
  payload: JBrowseSessionResponse | null;
  /** The visible locus ("chr8:1..2"), null before the view has blocks. */
  locus: string | null;
  /** What `color_by` / `color_scale` resolved, null when the tile has neither. */
  colours: GenomeTracksColours | null;
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
  patch: Partial<Pick<GenomeTracksEntry, 'payload' | 'locus' | 'colours'>>,
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
    colours: prev?.colours ?? null,
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

const sameRecord = (a: Record<string, string>, b: Record<string, string>): boolean => {
  const ak = Object.keys(a);
  return ak.length === Object.keys(b).length && ak.every((k) => a[k] === b[k]);
};

/**
 * Publish the colours a tile resolved from `color_by` / `color_scale`, which
 * the payload does not carry (the manifest's `color` column is the only colour
 * it holds). Another tile drawing the same samples reads them back through
 * `trackSampleColours` and `trackGroupColours`. Rewritten only when they
 * change; `null` withdraws them.
 */
export function setGenomeTracksColours(
  dashboardId: string,
  index: string,
  colours: GenomeTracksColours | null,
): void {
  const prev = entries.get(keyOf(dashboardId, index))?.colours ?? null;
  const same =
    prev === colours ||
    (prev !== null &&
      colours !== null &&
      sameRecord(prev.samples, colours.samples) &&
      sameRecord(prev.groups, colours.groups) &&
      JSON.stringify(prev.key ?? null) === JSON.stringify(colours.key ?? null));
  if (same) return;
  write(dashboardId, index, { colours });
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
    // The manifest's own colour is the author's choice and wins over what the
    // tile computed from `color_by` / `color_scale`.
    for (const row of entry.payload?.track_rows ?? []) {
      if (row.sample && row.color && !(row.sample in out)) out[row.sample] = row.color;
    }
    for (const [sample, colour] of Object.entries(entry.colours?.samples ?? {})) {
      if (!(sample in out)) out[sample] = colour;
    }
  }
  return out;
}

/**
 * Value → colour of the `color_by` / `color_scale` column over every genome
 * browser tile of a dashboard (the first tile written wins a value two tiles
 * colour differently). Another tile whose rows carry the same values (a genome
 * view's category column) wears the same colours. Same dashboard rule as
 * `trackSampleColours`.
 */
export function trackGroupColours(dashboardId?: string): Record<string, string> {
  const out: Record<string, string> = {};
  let dashboard = dashboardId;
  if (dashboard === undefined) {
    let latest: GenomeTracksEntry | null = null;
    for (const e of entries.values()) if (e.colours && (!latest || e.seq > latest.seq)) latest = e;
    if (!latest) return out;
    dashboard = latest.dashboardId;
  }
  const ordered = [...entries.values()]
    .filter((e) => e.dashboardId === dashboard && e.colours)
    .sort((a, b) => a.seq - b.seq);
  for (const entry of ordered) {
    for (const [value, colour] of Object.entries(entry.colours?.groups ?? {})) {
      if (!(value in out)) out[value] = colour;
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

/** `trackGroupColours`, re-read when a tile writes; stable while unchanged. */
export function useTrackGroupColours(dashboardId?: string): Record<string, string> {
  const cache = useRef<{ key: string; value: Record<string, string> }>({ key: '{}', value: {} });
  const snapshot = useCallback(() => {
    const value = trackGroupColours(dashboardId);
    const key = JSON.stringify(value);
    if (key !== cache.current.key) cache.current = { key, value };
    return cache.current.value;
  }, [dashboardId]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

/**
 * The key to the colours the browser tiles of a dashboard resolved from
 * `color_by` / `color_scale` (the first tile that publishes one wins), or null.
 * Same dashboard rule as `trackGroupColours`.
 */
export function trackColourKey(dashboardId?: string): GenomeTracksColourKey | null {
  let dashboard = dashboardId;
  if (dashboard === undefined) {
    let latest: GenomeTracksEntry | null = null;
    for (const e of entries.values()) if (e.colours && (!latest || e.seq > latest.seq)) latest = e;
    if (!latest) return null;
    dashboard = latest.dashboardId;
  }
  const ordered = [...entries.values()]
    .filter((e) => e.dashboardId === dashboard && e.colours?.key)
    .sort((a, b) => a.seq - b.seq);
  return ordered[0]?.colours?.key ?? null;
}

/** `trackColourKey`, re-read when a tile writes; stable while unchanged. */
export function useTrackColourKey(dashboardId?: string): GenomeTracksColourKey | null {
  const cache = useRef<{ key: string; value: GenomeTracksColourKey | null }>({
    key: 'null',
    value: null,
  });
  const snapshot = useCallback(() => {
    const value = trackColourKey(dashboardId);
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

/**
 * The `locus_from` rows the genome browsers of a dashboard point at, as the
 * JSON of their keys (`picked.keys`, see `JBrowsePicked`): a string, so the
 * snapshot is stable between writes. Keyed by column name, like a dashboard
 * filter: a table of another collection that carries the same columns (an
 * isoform table next to the browser's loci) finds the same rows. `'[]'` when
 * no browser points at anything.
 */
export function pickedRowKeysJson(dashboardId: string): string {
  const keys: Array<Record<string, unknown>> = [];
  for (const e of entries.values()) {
    if (e.dashboardId === dashboardId) keys.push(...(e.payload?.picked?.keys ?? []));
  }
  return JSON.stringify(keys);
}

/** `pickedRowKeysJson`, re-read whenever a browser writes. */
export function usePickedRowKeysJson(dashboardId: string): string {
  const snapshot = useCallback(() => pickedRowKeysJson(dashboardId), [dashboardId]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
