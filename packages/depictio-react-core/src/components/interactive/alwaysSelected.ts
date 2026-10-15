/**
 * `always_selected` Select filters: the control always holds exactly one value.
 *
 * Some tabs show one unit at a time (one structure, one family), and an empty
 * picker there means every unit stacked into one unreadable tile, or each tile
 * falling back on a different "first" unit. A YAML `default_value` cannot fix
 * it, since the value would be specific to one run. The flag makes the default
 * data-derived instead: whenever the filter is empty (first load, "Reset all",
 * the user clearing it) or holds a value its list no longer offers (a funnel
 * narrowed it away, another run loaded) it takes the first option of its own
 * list, and a new pick replaces the current one.
 *
 * The automatic pick is made by `AlwaysSelectedPickers`, which a host mounts
 * once for its filters, so it happens whether or not the control itself is on
 * screen (a collapsed filter panel, a folded section, the phone drawer). The
 * controls only keep a user's change to one value and drop their clear
 * affordances: the panel's Select, the filter bar's chips and picker, the
 * active-filter summary.
 */
import type { InteractiveFilter, StoredMetadata } from '../../api';
import { selectedValues } from './categoricalOptions';

/** An entry of the option list, in the order the Select shows it. */
export interface PickableOption {
  value: string;
  disabled?: boolean;
}

/**
 * The options in the order an automatic pick walks them: the ranked values
 * first, best first (those the option list holds), then the rest as listed. An
 * `always_selected` Select with `default_by` keeps its alphabetical list for
 * the reader and starts on the best-ranked option that is still enabled.
 * `ranking` null leaves the list as it is.
 */
export function rankPickOptions<T extends PickableOption>(
  options: readonly T[],
  ranking: readonly string[] | null,
): T[] {
  if (!ranking || ranking.length === 0) return [...options];
  const byValue = new Map(options.map((o) => [o.value, o]));
  const ranked: T[] = [];
  for (const v of ranking) {
    const o = byValue.get(v);
    if (o) {
      ranked.push(o);
      byValue.delete(v);
    }
  }
  return [...ranked, ...options.filter((o) => byValue.has(o.value))];
}

/** True when the component opts into `always_selected` (Select only). */
export function isAlwaysSelected(
  m: Pick<StoredMetadata, 'interactive_component_type' | 'always_selected'> | null | undefined,
): boolean {
  return m?.interactive_component_type === 'Select' && m.always_selected === true;
}

/** The values a filter list holds for one control: its own, not a selection
 *  made on a chart (which carries a `source`). */
export function ownFilterValues(filters: readonly InteractiveFilter[], index: string): string[] {
  return selectedValues(filters.find((f) => f.index === index && f.source === undefined)?.value);
}

/**
 * The value an `always_selected` Select should emit on its own, or `null` when
 * it should do nothing: the flag is off, the options are still loading, the
 * filter holds a value that is still on offer, or there is nothing to pick.
 * The first enabled option wins (`rankPickOptions` puts a `default_by` ranking
 * first); a greyed-out one (absent from the joined
 * data) is only taken when every option is greyed out.
 *
 * A held value that is greyed out or gone from the list is replaced by the
 * first enabled option. When every option is greyed out, a held value that is
 * still listed stays: re-picking another greyed-out one would change nothing
 * the reader can see.
 */
export function autoPickValue(args: {
  enabled: boolean;
  loading: boolean;
  selected: readonly string[];
  options: readonly PickableOption[];
}): string[] | null {
  const { enabled, loading, selected, options } = args;
  if (!enabled || loading || options.length === 0) return null;
  const firstEnabled = options.find((o) => !o.disabled);
  if (selected.length > 0) {
    const offered = (o: PickableOption) => selected.includes(o.value);
    // Exactly one value, still on offer: nothing to do. Several values (a
    // state written before the flag was set) collapse to the first offered.
    const held = options.filter((o) => offered(o) && !o.disabled);
    if (held.length > 0) return selected.length === 1 ? null : [held[0].value];
    if (firstEnabled) return [firstEnabled.value];
    if (options.some(offered)) {
      return selected.length === 1 ? null : [options.find(offered)!.value];
    }
    return [options[0].value];
  }
  return [(firstEnabled ?? options[0]).value];
}

/**
 * The value to emit for a user change on an `always_selected` Select. The
 * control is a multi-value input underneath, so adding an option appends it:
 * keep only the newest one. Removing the only value falls back to the first
 * option straight away, so the tiles never see an empty filter in between.
 */
export function singlePick(
  next: readonly string[],
  options: readonly PickableOption[],
): string[] {
  if (next.length > 1) return [next[next.length - 1]];
  if (next.length === 1) return [next[0]];
  return autoPickValue({ enabled: true, loading: false, selected: [], options }) ?? [];
}
