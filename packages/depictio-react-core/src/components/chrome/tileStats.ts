/**
 * What a tile last drew, for the metadata panel: row, lane and gene counts,
 * the renderer. A tile with a busy header publishes them here instead of as
 * badges (the genome view), and `MetadataBody` reads them with `useTileStats`.
 * Keyed by component index; in-memory, never a filter.
 */
import { useSyncExternalStore } from 'react';

export type TileStats = Record<string, number | string>;

const entries = new Map<string, TileStats>();
const listeners = new Set<() => void>();

const same = (a: TileStats | undefined, b: TileStats | undefined) =>
  JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/** Publish (or, with undefined, drop) what tile `index` drew. */
export function setTileStats(index: string, stats: TileStats | undefined): void {
  if (same(entries.get(index), stats)) return;
  if (stats) entries.set(index, stats);
  else entries.delete(index);
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

/** What tile `index` last published, undefined before it has. */
export function useTileStats(index: string): TileStats | undefined {
  return useSyncExternalStore(
    subscribe,
    () => entries.get(index),
    () => undefined,
  );
}
