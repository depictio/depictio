/**
 * How many collections of a run plan are ready, counted so an optional
 * collection the run did not produce never reads as a shortfall: it is
 * reported on its own, and the ready ratio is over the required ones.
 */
import { groupRunCollections } from 'depictio-react-core';
import type { RunCollectionEntry } from 'depictio-react-core';

import { plural } from './plural';

export interface CollectionCounts {
  /** Collections with their files (or vouched for by the server). */
  ready: number;
  /** Ready ones plus the required ones without files yet. */
  required: number;
  /** Optional collections this run did not produce (pruned ones excluded). */
  optionalAbsent: number;
}

export function collectionCounts(collections: ReadonlyArray<RunCollectionEntry>): CollectionCounts {
  const groups = groupRunCollections(collections);
  const ready = groups.ready.length;
  return {
    ready,
    required: ready + groups.missing.length,
    optionalAbsent: groups.optional.filter((dc) => dc.status !== 'pruned').length,
  };
}

/** "2 optional ones not in this run" (empty when there are none). */
export function optionalAbsentText(n: number): string {
  if (n === 0) return '';
  return n === 1 ? '1 optional one not in this run' : `${n} optional ones not in this run`;
}

/** "21 collections ready · 2 optional ones not in this run". */
export function readySummary(c: CollectionCounts): string {
  const head =
    c.ready === c.required
      ? `${plural(c.ready, 'collection')} ready`
      : `${c.ready} of ${plural(c.required, 'collection')} ready`;
  const tail = optionalAbsentText(c.optionalAbsent);
  return tail ? `${head} · ${tail}` : head;
}
