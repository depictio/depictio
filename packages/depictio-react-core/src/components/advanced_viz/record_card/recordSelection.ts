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

/** Mirrors `RecordCardConfig.selection_source`. */
export type RecordSelectionSource = 'scatter_selection' | 'table_selection' | 'any';

/** The sources a card can follow, in the order a tie is broken. */
export const RECORD_SELECTION_SOURCES = ['scatter_selection', 'table_selection'] as const;

export type HonouredSelectionSource = (typeof RECORD_SELECTION_SOURCES)[number];

export function honouredSelectionSources(
  source?: RecordSelectionSource | null,
): readonly HonouredSelectionSource[] {
  return !source || source === 'any' ? RECORD_SELECTION_SOURCES : [source];
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
  for (const filter of filters ?? []) {
    if (!filter.source || !honoured.has(filter.source)) continue;
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
  if (candidates.length === 0) return null;
  return candidates.find((candidate) => candidate.ownCollection) ?? candidates[0];
}
