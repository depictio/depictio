import { columnCategoryColors, sortCategoryValues } from '../categoryColors';
import type { CategoryColorSource } from '../categoryColors';

/** What a text tile's `legend` lists at most before it says how many more. */
export const LEGEND_MAX = 24;

/** The column a fact value names with `{{legend:column}}`, or null when the
 *  value is anything else. */
export function legendColumnOf(value: string): string | null {
  const m = /^\{\{legend:([A-Za-z0-9_.-]+)\}\}$/.exec(value.trim());
  return m ? m[1] : null;
}

export interface LegendEntry {
  label: string;
  color: string;
}

/**
 * The key a text tile's `legend` draws: one entry per colour the dashboard
 * (or its main tab) pins to the column, in natural sort order. Empty when the
 * column has no pinned colours, so no key is drawn: a colour handed out by
 * position would read as a meaning it does not have.
 */
export function legendEntries(
  source: CategoryColorSource | null | undefined,
  column: string | null | undefined,
): LegendEntry[] {
  const pinned = columnCategoryColors(source, column);
  if (!pinned) return [];
  return sortCategoryValues(Object.keys(pinned)).map((label) => ({ label, color: pinned[label] }));
}
