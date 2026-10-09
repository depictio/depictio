/**
 * Reading a run-folder plan (`FromRunReport.data_collections`): which data
 * collections are ready, which found nothing, and whether the run folder is
 * plausibly the right one at all.
 *
 * Kept apart from the rendering so the counts in the summary header, the
 * sections of the list and the rule that blocks Create cannot disagree.
 */

/** The plan fields this module reads (a subset of `FromRunDCPreview`). */
export interface RunCollectionEntry {
  data_collection_tag: string;
  matched: number;
  optional: boolean;
  /** `ok`, `empty`, `missing` or `pruned`. */
  status: string;
}

/** Where a collection is listed: problems first, then what is ready, then
 *  the optional collections that found nothing (or that the template left
 *  out for this run). */
export type RunCollectionSection = 'missing' | 'ready' | 'optional';

/** Ready to ingest: something matched, or the server vouched for it without
 *  counting (`ok` with 0, a manifest or remote file fetched at ingestion). A
 *  collection the template pruned is never ready. */
export function isCollectionReady(dc: RunCollectionEntry): boolean {
  if (dc.status === 'pruned') return false;
  return dc.matched > 0 || dc.status === 'ok';
}

export function runCollectionSection(dc: RunCollectionEntry): RunCollectionSection {
  if (isCollectionReady(dc)) return 'ready';
  return dc.optional || dc.status === 'pruned' ? 'optional' : 'missing';
}

/** The collections split into their sections, each in plan order. */
export function groupRunCollections<T extends RunCollectionEntry>(
  collections: ReadonlyArray<T>,
): Record<RunCollectionSection, T[]> {
  const groups: Record<RunCollectionSection, T[]> = { missing: [], ready: [], optional: [] };
  for (const dc of collections) groups[runCollectionSection(dc)].push(dc);
  return groups;
}

/** How many collections are ready, out of those the template keeps for this
 *  run (pruned ones say nothing about the folder, so they count on neither
 *  side). */
export function runCollectionTotals(collections: ReadonlyArray<RunCollectionEntry>): {
  ready: number;
  considered: number;
} {
  const considered = collections.filter((dc) => dc.status !== 'pruned');
  return {
    ready: considered.filter(isCollectionReady).length,
    considered: considered.length,
  };
}

/** True when the folder yields nothing to ingest: no collection is left, or
 *  every collection the server could count found nothing. Almost always a run
 *  folder one level too high or too low, which is why Create is blocked on it
 *  rather than left to fail halfway through ingestion. Collections the server
 *  cannot count from the folder (`ok` with 0) neither prove nor disprove it. */
export function runFoundNothing(collections: ReadonlyArray<RunCollectionEntry>): boolean {
  const considered = collections.filter((dc) => dc.status !== 'pruned');
  if (considered.length === 0) return true;
  const countable = considered.filter((dc) => !(dc.status === 'ok' && dc.matched === 0));
  return countable.length > 0 && countable.every((dc) => dc.matched === 0);
}
