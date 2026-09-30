/**
 * `always_selected` Select filters: the control always holds exactly one value.
 *
 * Some tabs show one unit at a time (one engine, one structure), and an empty
 * picker there means every unit stacked into one unreadable tile. A YAML
 * `default_value` cannot fix it, since the value would be specific to one run.
 * The flag makes the default data-derived instead: whenever the filter is
 * empty (first load, "Reset all", the user clearing it) or holds a value its
 * list no longer offers (a funnel narrowed it away, another run loaded) it
 * takes the first option of its own list, and a new pick replaces the current
 * one.
 */
import type { StoredMetadata } from '../../api';

/** An entry of the option list, in the order the Select shows it. */
export interface PickableOption {
  value: string;
  disabled?: boolean;
}

/** True when the component opts into `always_selected` (Select only). */
export function isAlwaysSelected(m: StoredMetadata): boolean {
  return m.interactive_component_type === 'Select' && m.always_selected === true;
}

/**
 * The value an `always_selected` Select should emit on its own, or `null` when
 * it should do nothing: the flag is off, the options are still loading, the
 * filter holds a value that is still on offer, or there is nothing to pick.
 * The first enabled option wins; a greyed-out one (absent from the joined
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
    if (options.some((o) => offered(o) && !o.disabled)) return null;
    if (firstEnabled) return [firstEnabled.value];
    return options.some(offered) ? null : [options[0].value];
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
