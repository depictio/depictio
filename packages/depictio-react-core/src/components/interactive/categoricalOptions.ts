/**
 * Pure rules shared by every categorical control — the Filters panel's
 * MultiSelect and SegmentedControl renderers and the filter bar's chips.
 *
 * Kept free of React so the panel and the bar cannot drift on how options are
 * ordered or what a click emits, and so the rules are unit-testable.
 */
import type { InteractiveFilter, StoredMetadata } from '../../api';

/** Up to this many values a filter bar draws chips, each in its colour (on a
 *  second line when its column is narrow); from ten, a picker listing them. */
export const MAX_STRIP_CHIPS = 9;

const COLLATOR = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

/**
 * Options in display order: values still available first (so they are
 * immediately visible), then the greyed ones; natural sort within each bucket
 * so `Sample_2` precedes `Sample_10`. `available` null means every value is.
 */
export function orderCategoricalOptions(
  options: readonly string[],
  available: ReadonlySet<string> | null,
): string[] {
  return [...options].sort((a, b) => {
    if (available) {
      const aAvail = available.has(a);
      const bAvail = available.has(b);
      if (aAvail !== bAvail) return aAvail ? -1 : 1;
    }
    return COLLATOR.compare(a, b);
  });
}

export type CategoricalDisplay = 'chips' | 'select';

/** Chips up to `max` values, a picker beyond. */
export function categoricalDisplay(optionCount: number, max = MAX_STRIP_CHIPS): CategoricalDisplay {
  return optionCount > max ? 'select' : 'chips';
}

/** `multi` toggles membership; `single` picks one value (or none). */
export type ChipSelectionMode = 'multi' | 'single';

/** A MultiSelect stays multi. A Select or a SegmentedControl is one-of-N. */
export function chipSelectionMode(interactiveType: string | undefined): ChipSelectionMode {
  return interactiveType === 'MultiSelect' ? 'multi' : 'single';
}

/** The selected values a stored filter value stands for, whichever shape the
 *  control wrote: `string[]` (MultiSelect, Select) or `string`
 *  (SegmentedControl). Anything else is no selection, i.e. "all". */
export function selectedValues(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((v) => v !== null && v !== undefined).map(String);
  if (typeof value === 'string' && value) return [value];
  return [];
}

/** The selection after clicking `value`. Clicking the only selected value in
 *  single mode clears it — nothing selected means all, as everywhere else. */
export function toggleChip(
  selected: readonly string[],
  value: string,
  mode: ChipSelectionMode,
): string[] {
  const has = selected.includes(value);
  if (mode === 'single') return has && selected.length === 1 ? [] : [value];
  return has ? selected.filter((v) => v !== value) : [...selected, value];
}

/**
 * The filter value a selection is emitted as — the shape the control's own
 * renderer emits: a list for MultiSelect and Select (`MultiSelectRenderer`),
 * one string for SegmentedControl (`SegmentedControlRenderer`), `null` when it
 * selects nothing (what the panel's reset emits).
 */
export function chipFilterValue(next: readonly string[], interactiveType: string | undefined): unknown {
  if (interactiveType === 'SegmentedControl') return next[0] ?? null;
  return [...next];
}

/** One filter event, in the shape every interactive renderer emits. */
export function filterEvent(
  metadata: Pick<StoredMetadata, 'index' | 'column_name' | 'interactive_component_type' | 'filter_expr'>,
  value: unknown,
  interactiveType: string | undefined = metadata.interactive_component_type,
): InteractiveFilter {
  return {
    index: metadata.index,
    value,
    column_name: metadata.column_name,
    interactive_component_type: interactiveType,
    filter_expr: metadata.filter_expr,
  };
}
