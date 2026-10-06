/**
 * Category colours: one categorical value, one colour, everywhere.
 *
 * A dashboard reads as one piece when "Athens" is the same blue on the filter
 * bar's chip, in the PCoA's points and under the bar chart's group. That only
 * holds if every surface resolves the colour the same way, so the rule lives
 * here and nowhere else:
 *
 *   1. the dashboard's own `category_colors[column][value]`;
 *   2. its main tab's (`inherited_category_colors`, child tabs only);
 *   3. the brand colorway, indexed by the value's position in the column's
 *      sorted universe (`sortCategoryValues`) — not by its position in what a
 *      filter left over, so a value keeps its colour while others come and go;
 *   4. a neutral grey.
 *
 * Steps 3 and 4 are for surfaces that must colour every value, a figure's
 * traces. A filter's chips are not one of them: a dot there says "this is the
 * colour Athens has on this dashboard", which is only true of a column the
 * author gave colours to. So the chips take `pinnedCategoryDots` — steps 1 and
 * 2, and no dot at all for a column with no entry.
 *
 * Pure on purpose: the figure code calls the same functions with the same
 * inputs and gets the same answer. `useCategoryColorMap` and
 * `useCategoryDotColors` are the React bindings.
 */
import type { CategoryColors } from './api';
import type { BrandTheme } from './brandTheme';

/** What the rule above is read from. `DashboardData` satisfies it. */
export interface CategoryColorSource {
  category_colors?: CategoryColors | null;
  inherited_category_colors?: CategoryColors | null;
  brand_theme?: BrandTheme | null;
  inherited_brand_theme?: BrandTheme | null;
}

/** Last resort: Mantine's gray-5, as a hex so Plotly can take it as well. */
export const NEUTRAL_CATEGORY_COLOR = '#adb5bd';

const COLLATOR = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

/**
 * A column's values in the order colours are handed out: distinct, non-empty,
 * natural sort (`Sample_2` before `Sample_10`, case-insensitive). Pass the
 * column's full universe (e.g. `fetchUniqueValues`), not the filtered rows.
 */
export function sortCategoryValues(values: readonly unknown[]): string[] {
  const seen = new Set<string>();
  for (const v of values) {
    if (v === null || v === undefined || v === '') continue;
    seen.add(String(v));
  }
  return [...seen].sort((a, b) => COLLATOR.compare(a, b));
}

/** The colorway a dashboard states itself, own before inherited. The brand the
 *  viewer actually draws in is resolved server-side and carries a derived
 *  colorway even when none was authored, so React callers should prefer the
 *  palette `useCategoryColorMap` reads off the theme. */
export function dashboardColorway(
  source: CategoryColorSource | null | undefined,
): readonly string[] | null {
  const own = source?.brand_theme?.plots?.colorway;
  if (own && own.length) return own;
  const inherited = source?.inherited_brand_theme?.plots?.colorway;
  return inherited && inherited.length ? inherited : null;
}

/** The colour pinned for this value, if any: own map first, then inherited. */
export function pinnedCategoryColor(
  source: CategoryColorSource | null | undefined,
  column: string | null | undefined,
  value: unknown,
): string | null {
  if (!source || !column || value === null || value === undefined) return null;
  const key = String(value);
  return (
    source.category_colors?.[column]?.[key] ||
    source.inherited_category_colors?.[column]?.[key] ||
    null
  );
}

/**
 * One value's colour.
 *
 * @param index - the value's position in `sortCategoryValues(universe)`.
 * @param palette - the colorway to fall back to; defaults to the one the
 *   dashboard states (`dashboardColorway`). Pass `null` to skip straight to
 *   the neutral grey.
 */
export function categoryColor(
  source: CategoryColorSource | null | undefined,
  column: string | null | undefined,
  value: unknown,
  index: number,
  palette?: readonly string[] | null,
): string {
  const pinned = pinnedCategoryColor(source, column, value);
  if (pinned) return pinned;
  const colorway = palette === undefined ? dashboardColorway(source) : palette;
  if (colorway && colorway.length && Number.isFinite(index) && index >= 0) {
    return colorway[Math.floor(index) % colorway.length];
  }
  return NEUTRAL_CATEGORY_COLOR;
}

/** Every value of a column mapped to its colour, indices taken from the
 *  sorted universe. Values outside the universe get no entry: look them up
 *  with `categoryColor` and an index of your own. */
export function categoryColorMap(
  source: CategoryColorSource | null | undefined,
  column: string | null | undefined,
  universe: readonly unknown[],
  palette?: readonly string[] | null,
): Map<string, string> {
  const map = new Map<string, string>();
  sortCategoryValues(universe).forEach((value, i) => {
    map.set(value, categoryColor(source, column, value, i, palette));
  });
  return map;
}

/** Whether the dashboard (or its main tab) gives `column` colours of its own. */
export function hasPinnedColors(
  source: CategoryColorSource | null | undefined,
  column: string | null | undefined,
): boolean {
  if (!source || !column) return false;
  const own = source.category_colors?.[column];
  const inherited = source.inherited_category_colors?.[column];
  return Boolean(
    (own && Object.keys(own).length) || (inherited && Object.keys(inherited).length),
  );
}

/**
 * The dots a filter's chips draw, or `null` for none.
 *
 * Only a column listed in `category_colors` (own or inherited) gets dots: there
 * the colour is the one the figures draw the value in, so the dot means
 * something. Its values each take their pinned colour, and one the author did
 * not list takes the neutral grey, so a row of chips never has a gap where a
 * dot should be. Any other column — a size class, a season — gets no dot: a
 * colour handed out by position would read as a meaning it does not have.
 */
export function pinnedCategoryDots(
  source: CategoryColorSource | null | undefined,
  column: string | null | undefined,
  universe: readonly unknown[],
): Map<string, string> | null {
  if (!hasPinnedColors(source, column)) return null;
  const map = new Map<string, string>();
  for (const value of sortCategoryValues(universe)) {
    map.set(value, pinnedCategoryColor(source, column, value) ?? NEUTRAL_CATEGORY_COLOR);
  }
  return map;
}
