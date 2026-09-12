/**
 * Pure logic behind the Analysis panel's two "how do I make a group?" aids:
 * the guided 1-2-3 shown while the dashboard has no group yet
 * (`GroupingSteps`) and the live read-out of the selection about to be saved
 * (`PendingGroupForm`).
 *
 * Kept out of the components so the wording rules and the value-sampling can
 * be unit-tested — the vitest setup here is node-only, so anything that has to
 * render belongs to the Playwright suite.
 */

import type { InteractiveFilter, StoredMetadata } from '../../api';
import { filterDisplayLabel } from '../../activeFilters';
import { supportsSelectionGrouping } from '../../selection';
import type { ColorByState, SelectionGroup } from '../../selectionGroups';

/**
 * How many tiles on this dashboard can emit a selection a group can be made
 * from. Counted with the same predicate that decides whether a tile shows the
 * capability marker (`supportsSelectionGrouping`), so the number the guide
 * quotes and the tiles the user can actually see marked cannot disagree.
 *
 * `hasHandler` is hard-coded true: the panel only ever renders inside a host
 * that wires `onFilterChange`, which is the condition that argument stands for.
 */
export function selectionCapableCount(components: StoredMetadata[]): number {
  return components.filter((m) => supportsSelectionGrouping(m, true)).length;
}

/** Stable identity of a live selection: the dashboard holds at most one per
 *  `(index, source)` pair, which is the same key `mergeFiltersBySource` uses. */
export function selectionKey(filter: InteractiveFilter): string {
  return `${filter.index}:${filter.source}`;
}

/**
 * Which of the three guided steps the user is on (0-based, for `Stepper`'s
 * `active`).
 *
 * Step 1 ("find a tile you can select on") cannot be observed directly — there
 * is no event for "looked at a tile" — so it counts as done as soon as the
 * dashboard has at least one capable tile, which is also exactly when those
 * tiles are marked on screen. With none, the flow is stuck on step 1 and the
 * step says so rather than sending the user hunting for a lasso that no tile
 * would answer.
 */
export function groupingActiveStep(selectableCount: number, hasSelection: boolean): number {
  if (selectableCount <= 0) return 0;
  return hasSelection ? 2 : 1;
}

/** Step 1's description: how many tiles here can feed a group, or why none can. */
export function selectionCapableSummary(count: number): string {
  if (count <= 0) {
    return 'No tile on this dashboard emits selections yet — a scatter needs its lasso enabled, a table its row selection.';
  }
  return `${count} tile${count === 1 ? '' : 's'} here can. While Analysis is on, each one is outlined and carries the group marker in its corner.`;
}

export interface PendingSelectionPreview {
  /** Values in the selection (the group would capture all of them). */
  count: number;
  /** Column the values belong to — what the saved group filters on. */
  columnName: string;
  /** Title of the component the selection came from, or null when it carries
   *  no title of its own (the label would then just repeat the column). */
  sourceLabel: string | null;
  /** The values themselves, for `ValueListPreview`. */
  values: ValueList;
}

/**
 * The ids behind a selection or a group, ready to be listed.
 *
 * Six values as truncated badges was the first attempt and it failed at the
 * only job it had: sample ids differ in a suffix, badges clip them, and a wrapped
 * row of clipped chips cannot be read down. A list of whole values can.
 */
export interface ValueList {
  /** Distinct values, in first-seen order, capped at `VALUE_LIST_LIMIT`. */
  shown: string[];
  /** How many distinct values exist. */
  distinct: number;
  /** Raw length of the underlying selection. Higher than `distinct` when a
   *  lasso caught several points of the same sample. */
  total: number;
  /** Distinct values the cap left out. */
  hidden: number;
}

/** Rendered at once. The box scrolls, so this is only a guard against a lasso
 *  over tens of thousands of points turning into tens of thousands of nodes. */
export const VALUE_LIST_LIMIT = 200;

export function valueList(values: string[], limit: number = VALUE_LIST_LIMIT): ValueList {
  const seen = new Set<string>();
  const distinctValues: string[] = [];
  for (const v of values) {
    const s = String(v);
    if (seen.has(s)) continue;
    seen.add(s);
    distinctValues.push(s);
  }
  return {
    shown: distinctValues.slice(0, limit),
    distinct: distinctValues.length,
    total: values.length,
    hidden: Math.max(0, distinctValues.length - limit),
  };
}

/** Per-value display cap, still used where one value has to fit on one line. */
export const PREVIEW_VALUE_MAX_CHARS = 22;

export function truncateValue(value: string, max = PREVIEW_VALUE_MAX_CHARS): string {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
}

/**
 * What the user is about to save, in display shape: how many values, on which
 * column, from which tile, and a sample of the values themselves.
 *
 * The column resolution mirrors `groupFromSelectionFilter` exactly — the panel
 * must not promise a column the save would then resolve differently — and
 * returns null on the same inputs it refuses (no values, no resolvable
 * column), so a null preview means "nothing to save".
 */
export function selectionPreview(
  filter: InteractiveFilter,
  components: StoredMetadata[],
  limit: number = VALUE_LIST_LIMIT,
): PendingSelectionPreview | null {
  if (!Array.isArray(filter.value) || filter.value.length === 0) return null;
  const columnName =
    filter.column_name ?? filter.metadata?.selection_column ?? filter.metadata?.column_name;
  if (!columnName) return null;
  const values = filter.value.map((v) => String(v));
  // `filterDisplayLabel` falls back to the column name for a titleless
  // component; that would render as "on sample_id from sample_id", so the
  // fallback is dropped here and the copy leaves the clause out instead.
  const label = filterDisplayLabel(filter, components);
  return {
    count: values.length,
    columnName,
    sourceLabel: label === columnName ? null : label,
    values: valueList(values, limit),
  };
}

/** A saved group, in display shape. Mirrors `PendingSelectionPreview`: the
 *  card that lists a saved group should answer the same questions the card
 *  that was about to save it did, or the two read as different features. */
export interface SavedGroupPreview {
  count: number;
  columnName: string;
  /** Data collection the selection was made on, when it can be named. */
  datasetLabel: string | null;
  values: ValueList;
}

/**
 * What a saved group actually holds.
 *
 * The list used to render one line per group — a swatch, the name and a bare
 * count — so two groups drawn on different columns, or on different datasets,
 * were indistinguishable until one of them silently failed to reach a figure.
 * Naming the column and the dataset is what makes "grouped (1 of 2)" on a tile
 * explicable from the panel.
 */
export function groupPreview(
  group: SelectionGroup,
  components: StoredMetadata[],
  limit: number = VALUE_LIST_LIMIT,
): SavedGroupPreview {
  const values = group.values ?? [];
  // Only a tag: a bare ObjectId says nothing a reader can act on, and the
  // column name already carries the useful half on a single-dataset board.
  const meta = group.dcId
    ? components.find((m) => m.dc_id === group.dcId && m.data_collection_tag)
    : undefined;
  return {
    count: values.length,
    columnName: group.columnName,
    datasetLabel: (meta?.data_collection_tag as string) || null,
    values: valueList(values, limit),
  };
}

/**
 * Which segment of the "Color figures by" control reads as chosen.
 *
 * Not simply `colorBy.kind`. Picking "A column" before naming one leaves the
 * override off — there is no column to apply yet — so a control bound straight
 * to `colorBy.kind` snapped the indicator back to "Nothing" the instant it was
 * clicked, and the segment looked broken rather than pending. `columnPending`
 * is that intermediate state, and it only speaks while nothing else is on.
 */
export function colorBySegmentValue(colorBy: ColorByState, columnPending: boolean): string {
  if (colorBy.kind === 'none' && columnPending) return 'column';
  return colorBy.kind;
}
