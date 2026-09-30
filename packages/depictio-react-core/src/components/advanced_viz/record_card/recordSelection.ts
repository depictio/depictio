/**
 * The selection a record card is currently following.
 *
 * The card draws nothing of its own: it shows the row somebody picked in
 * another tile, so the only question it has to answer is which of the
 * dashboard's filters is that pick. Selection filters carry a `source`
 * discriminator (see `selection.ts`), which is what separates a lasso from an
 * ordinary sidebar control, and `selection_source` narrows which of the two
 * reader gestures this card honours when several tiles select at once.
 */

import type { InteractiveFilter } from '../../../api';
import { RESIDUE_RANGE_INDEX_SUFFIX } from '../../../selection';

/** Mirrors `RecordCardConfig.selection_source`. */
export type RecordSelectionSource = 'scatter_selection' | 'table_selection' | 'any';

/** The sources a card can follow, in the order a tie is broken.
 *  `residue_selection` (a protein tile's residue pick) is followed under
 *  `any` and whenever the card is linked to the tile that emits it; it is not
 *  a `selection_source` value of its own. */
export const RECORD_SELECTION_SOURCES = [
  'scatter_selection',
  'table_selection',
  'residue_selection',
] as const;

/** Positions a residue range expands to before the card stops matching them
 *  one by one (the server has applied the range anyway). */
const MAX_RANGE_VALUES = 5000;

export type HonouredSelectionSource = (typeof RECORD_SELECTION_SOURCES)[number];

export function honouredSelectionSources(
  source?: RecordSelectionSource | null,
): readonly HonouredSelectionSource[] {
  return !source || source === 'any' ? RECORD_SELECTION_SOURCES : [source];
}

/** The emitting tile's index for either half of a residue pick. */
function residueBaseIndex(index: string): string {
  return index.endsWith(RESIDUE_RANGE_INDEX_SUFFIX)
    ? index.slice(0, -RESIDUE_RANGE_INDEX_SUFFIX.length)
    : index;
}

function filterColumn(filter: InteractiveFilter): string | null {
  return (
    filter.column_name ?? filter.metadata?.selection_column ?? filter.metadata?.column_name ?? null
  );
}

/**
 * One tile's residue pick as a record selection. The pair's entity half is
 * what the card matches its rows on (the server has already narrowed them to
 * the range); a range with no entity half (a single-protein dashboard)
 * matches on the positions it spans.
 */
function residueCandidate(
  entity: InteractiveFilter | undefined,
  range: InteractiveFilter | undefined,
  dcId: string | undefined,
): RecordSelection | null {
  const ownCollection = Boolean(dcId) && (entity ?? range)?.metadata?.dc_id === dcId;
  if (entity && Array.isArray(entity.value) && entity.value.length > 0) {
    return {
      source: 'residue_selection',
      column: filterColumn(entity),
      values: entity.value.map((v) => String(v)),
      ownCollection,
    };
  }
  if (range && Array.isArray(range.value) && range.value.length === 2) {
    const lo = Math.ceil(Math.min(Number(range.value[0]), Number(range.value[1])));
    const hi = Math.floor(Math.max(Number(range.value[0]), Number(range.value[1])));
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi < lo) return null;
    const values: string[] = [];
    for (let p = lo; p <= hi && values.length < MAX_RANGE_VALUES; p += 1) values.push(String(p));
    return {
      source: 'residue_selection',
      // Past the cap the positions are not matched client-side: the column is
      // dropped so the card keeps the server-narrowed rows as they are.
      column: hi - lo + 1 > MAX_RANGE_VALUES ? null : filterColumn(range),
      values,
      ownCollection,
    };
  }
  return null;
}

export interface RecordSelection {
  source: HonouredSelectionSource;
  /** Column the picked values belong to, when the emitting tile named one. */
  column: string | null;
  values: string[];
  /** The emitting tile reads the same collection as the card, so its values
   *  can be matched against the card's own rows without a link. */
  ownCollection: boolean;
}

/**
 * The selection driving the card, or null when nothing has been picked.
 *
 * A pick on the card's own collection wins over one that has to travel
 * through a project link, because that is the unambiguous case and a
 * dashboard with two selecting tiles should show the one that names the same
 * rows. A pick on another collection still counts: the server resolves the
 * link when the card fetches, so the card follows it rather than sitting on
 * its empty state while the rest of the dashboard is narrowed.
 *
 * `linkedIndex` (the resolved `linked_component`) names the one tile the card
 * follows. It is more precise than `selectionSource`, so when it is set only
 * that tile's selection counts, whichever of the two sources it emits.
 */
export function readRecordSelection(
  filters: readonly InteractiveFilter[] | undefined,
  options: {
    dcId?: string;
    selectionSource?: RecordSelectionSource | null;
    linkedIndex?: string | null;
  },
): RecordSelection | null {
  const honoured = new Set<string>(
    options.linkedIndex ? RECORD_SELECTION_SOURCES : honouredSelectionSources(options.selectionSource),
  );
  const candidates: RecordSelection[] = [];
  // Residue picks come as a pair (entity + `::res` range) and are read as one.
  const residuePairs = new Map<string, { entity?: InteractiveFilter; range?: InteractiveFilter }>();
  for (const filter of filters ?? []) {
    if (!filter.source || !honoured.has(filter.source)) continue;
    if (filter.source === 'residue_selection') {
      const base = residueBaseIndex(filter.index);
      if (options.linkedIndex && base !== options.linkedIndex) continue;
      const pair = residuePairs.get(base) ?? {};
      if (base === filter.index) pair.entity = filter;
      else pair.range = filter;
      residuePairs.set(base, pair);
      continue;
    }
    if (options.linkedIndex && filter.index !== options.linkedIndex) continue;
    // A cleared selection keeps its entry with an empty value list, which is
    // not a selection and must not pull the card off its empty state.
    if (!Array.isArray(filter.value) || filter.value.length === 0) continue;
    const column =
      filter.column_name ??
      filter.metadata?.selection_column ??
      filter.metadata?.column_name ??
      null;
    candidates.push({
      source: filter.source as HonouredSelectionSource,
      column,
      values: filter.value.map((value) => String(value)),
      ownCollection: Boolean(options.dcId) && filter.metadata?.dc_id === options.dcId,
    });
  }
  for (const { entity, range } of residuePairs.values()) {
    const candidate = residueCandidate(entity, range, options.dcId);
    if (candidate) candidates.push(candidate);
  }
  if (candidates.length === 0) return null;
  return candidates.find((candidate) => candidate.ownCollection) ?? candidates[0];
}
