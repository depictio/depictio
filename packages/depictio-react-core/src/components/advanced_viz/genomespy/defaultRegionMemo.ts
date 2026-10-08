/**
 * Which region a `genome_view` tile opened on by itself.
 *
 * A tile with `default_region` emits that region as a filter when it loads,
 * so the dashboard holds a `genome_selection` pair the reader never made. The
 * tile's clear-selection action is for the reader's own selections, so it
 * stays hidden while the only thing selected is that opening region, and
 * appears once the reader moves the region or picks a mark.
 *
 * The renderer records the key of the pair it emitted (`ownRegionKey`) before
 * emitting it, and the dispatch, which draws the chrome, reads it back when the
 * emitted filter re-renders it. Keyed by component index, like the default
 * region gate beside this module.
 */

import type { InteractiveFilter } from '../../../api';
import type { OwnSelection } from '../../../selection';
import { ownRegionKey } from './defaultRegion';

const defaultKeys = new Map<string, string>();

export function rememberDefaultRegion(componentIndex: string, key: string): void {
  if (key) defaultKeys.set(componentIndex, key);
}

export function forgetDefaultRegion(componentIndex: string): void {
  defaultKeys.delete(componentIndex);
}

export function defaultRegionKey(componentIndex: string): string | undefined {
  return defaultKeys.get(componentIndex);
}

/**
 * The tile's selection minus its opening region: the region pair is dropped
 * when it is still exactly the one the tile emitted on load. A pick on the
 * tile, or a region the reader moved, is kept whole.
 */
export function withoutDefaultRegion(
  own: OwnSelection,
  componentIndex: string,
  defaultKey: string | undefined,
): OwnSelection {
  if (!defaultKey) return own;
  const isRegion = (f: InteractiveFilter) => f.source === 'genome_selection';
  const region = own.filters.filter(isRegion);
  if (!region.length || ownRegionKey(region, componentIndex) !== defaultKey) return own;
  const rest = own.filters.filter((f) => !isRegion(f));
  const count = rest.reduce(
    (n, f) =>
      f.index === componentIndex ? n + (Array.isArray(f.value) ? f.value.length : 1) : n,
    0,
  );
  return { filters: rest, count };
}
