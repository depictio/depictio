/**
 * What the two "Group A / Group B" pickers offer, and what each choice means
 * to the server.
 *
 * Two kinds of group meet here. A *saved selection group* is a lasso the
 * reader drew on an embedding or a scatter and kept ("select & compare"): it
 * carries the column its values belong to and the values themselves, which is
 * already a row selector. A *label value* is one value of the component's
 * `group_col`, the precomputed clustering or condition the matrix shipped
 * with. Both collapse to the same `{label, column, values}` selector, so the
 * comparison never has to know which one it was handed.
 *
 * Kept out of the renderer because the interesting part is the collapsing and
 * the default pair, not the Mantine `Select` around them.
 */

import type { GroupCompareSelector } from '../../../api';
import type { GroupRenderDef } from '../../../selectionGroups';

/** Group heading in the Select, and the prefix of an option's value. */
export const SAVED_GROUP_SOURCE = 'Saved selection groups';
export const LABEL_VALUE_SOURCE = 'Label column';

export interface GroupCompareOption {
  /** Opaque, stable key: the picker's value and the effect dependency. */
  value: string;
  label: string;
  /** Which of the two sources the option came from, for the Select's groups. */
  source: typeof SAVED_GROUP_SOURCE | typeof LABEL_VALUE_SOURCE;
  selector: GroupCompareSelector;
}

/**
 * Every group the reader may compare, saved selections first.
 *
 * Saved groups lead because they are what the reader just made, and because a
 * dashboard that has any is one where the lasso flow is the point. Empty
 * groups are dropped: a selector with no values cannot name rows and the
 * server would refuse it with a 400.
 */
export function groupCompareOptions(
  savedGroups: GroupRenderDef[] | undefined,
  groupCol: string | null | undefined,
  labelValues: string[] | undefined,
): GroupCompareOption[] {
  const options: GroupCompareOption[] = [];
  for (const g of savedGroups ?? []) {
    if (!g.column_name || !g.values?.length) continue;
    options.push({
      value: `saved:${g.name}`,
      label: g.name,
      source: SAVED_GROUP_SOURCE,
      selector: { label: g.name, column: g.column_name, values: g.values.map(String) },
    });
  }
  if (groupCol) {
    for (const v of labelValues ?? []) {
      if (v === null || v === undefined || v === '') continue;
      options.push({
        value: `col:${v}`,
        label: String(v),
        source: LABEL_VALUE_SOURCE,
        selector: { label: String(v), column: groupCol, values: [String(v)] },
      });
    }
  }
  return options;
}

/**
 * The pair to start on: the first two options from the same source.
 *
 * Same source, because a saved lasso and a cluster label usually overlap, and
 * an opening view where most observations belong to both arms teaches the
 * reader nothing. Returns nulls when fewer than two comparable options exist,
 * which is the renderer's cue to say so rather than run anything.
 */
export function defaultGroupPair(
  options: GroupCompareOption[],
): [string | null, string | null] {
  for (const source of [SAVED_GROUP_SOURCE, LABEL_VALUE_SOURCE] as const) {
    const fromSource = options.filter((o) => o.source === source);
    if (fromSource.length >= 2) return [fromSource[0].value, fromSource[1].value];
  }
  return [null, null];
}

/** The selector behind a picked option value, or null when it no longer exists
 *  (the reader deleted the group, or a filter emptied the label column). */
export function selectorFor(
  options: GroupCompareOption[],
  value: string | null,
): GroupCompareSelector | null {
  if (!value) return null;
  return options.find((o) => o.value === value)?.selector ?? null;
}

/**
 * The option a configured default names, or null. A default is a plain name
 * (the YAML author does not know the `saved:` / `col:` prefixes): a saved
 * selection group of that name wins over a label value of the same spelling,
 * because a group the reader saved is the more deliberate choice.
 */
export function resolveGroupDefault(
  options: GroupCompareOption[],
  name: string | null | undefined,
): string | null {
  if (!name) return null;
  for (const source of [SAVED_GROUP_SOURCE, LABEL_VALUE_SOURCE] as const) {
    const hit = options.find((o) => o.source === source && o.label === name);
    if (hit) return hit.value;
  }
  return null;
}

/**
 * The pair to open on when the config names one (`default_group_a`,
 * `default_group_b`), else the automatic pair. Both defaults must resolve to
 * two different options; a half-resolved pair falls back as a whole, so the
 * opening comparison is never one configured arm against an arbitrary one.
 */
export function configuredGroupPair(
  options: GroupCompareOption[],
  defaultA: string | null | undefined,
  defaultB: string | null | undefined,
): [string | null, string | null] {
  const a = resolveGroupDefault(options, defaultA);
  const b = resolveGroupDefault(options, defaultB);
  if (a && b && a !== b) return [a, b];
  return defaultGroupPair(options);
}
