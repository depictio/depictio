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
 * traces. A filter's chips take `chipCategoryDots`: steps 1 and 2 for a column
 * the author gave colours to, step 3 for a short column with none (a colorway
 * covers it without handing one hue to two values), no dot past that.
 *
 * Pure on purpose: the figure code calls the same functions with the same
 * inputs and gets the same answer. `useCategoryColorMap` and
 * `useCategoryDotColors` are the React bindings.
 */
import { sortNaturalOrDuration } from './durationOrder';
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

/**
 * The key a template uses for "every other value, coloured from the data"
 * (`{"*": "auto"}`). The API resolves it at import, so a stored dashboard never
 * holds it; one that slips through must not read as a value named "*".
 */
const AUTO_KEY = '*';

/** The colour pinned for this value, if any: own map first, then inherited. */
export function pinnedCategoryColor(
  source: CategoryColorSource | null | undefined,
  column: string | null | undefined,
  value: unknown,
): string | null {
  if (!source || !column || value === null || value === undefined) return null;
  const key = String(value);
  if (key === AUTO_KEY) return null;
  return (
    source.category_colors?.[column]?.[key] ||
    source.inherited_category_colors?.[column]?.[key] ||
    null
  );
}

/**
 * Every colour pinned for one column, most specific last: the main tab's
 * (`inherited_category_colors`), the tab's own (`category_colors`), then
 * `overrides`, the component's own palette for that column, which wins value
 * by value. Null when none of them names a value.
 *
 * What a renderer hands `stableColorMap` as its overrides, so a value the
 * dashboard pins keeps that colour on the tile and every other value keeps the
 * renderer's palette.
 */
export function columnCategoryColors(
  source: CategoryColorSource | null | undefined,
  column: string | null | undefined,
  overrides?: Record<string, string> | null,
): Record<string, string> | null {
  const merged: Record<string, string> = {};
  const layers = column
    ? [source?.inherited_category_colors?.[column], source?.category_colors?.[column], overrides]
    : [overrides];
  for (const layer of layers) {
    if (!layer || typeof layer !== 'object') continue;
    for (const [value, colour] of Object.entries(layer)) {
      if (value === AUTO_KEY || typeof colour !== 'string' || !colour) continue;
      merged[value] = colour;
    }
  }
  return Object.keys(merged).length ? merged : null;
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
  return columnCategoryColors(source, column) !== null;
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

/**
 * The dots a filter's chips draw, or `null` for none.
 *
 * A column with colours of its own takes them (`pinnedCategoryDots`). One
 * without still gets dots while it is short, at most `maxValues` values and no
 * more than the colorway has hues: each value then takes the colorway's hue
 * for its place in the sorted universe (step 3), the colour a figure following
 * the rule above draws it in, and no two values share one. A longer column
 * gets none: the colorway would come round again, and two values in one
 * colour on adjacent chips would read as a pair.
 */
export function chipCategoryDots(
  source: CategoryColorSource | null | undefined,
  column: string | null | undefined,
  universe: readonly unknown[],
  palette: readonly string[] | null | undefined,
  maxValues: number,
): Map<string, string> | null {
  const pinned = pinnedCategoryDots(source, column, universe);
  if (pinned) return pinned;
  if (!column || !palette || palette.length === 0) return null;
  const values = sortCategoryValues(universe);
  if (values.length === 0 || values.length > Math.min(maxValues, palette.length)) return null;
  return categoryColorMap(source, column, values, palette);
}

// ---------------------------------------------------------------------------
// Sequential scales
// ---------------------------------------------------------------------------

/** Ramps a `color_scale` can name. Each is a handful of stops interpolated
 *  linearly in RGB; the light end of the single-hue ramps is already trimmed,
 *  so the first value never vanishes on a white card. */
export const SEQUENTIAL_SCHEMES = {
  viridis: ['#440154', '#472d7b', '#3b528b', '#2c728e', '#21918c', '#28ae80', '#5ec962', '#addc30', '#fde725'],
  magma: ['#3b0f70', '#641a80', '#8c2981', '#b73779', '#de4968', '#f7705c', '#fe9f6d', '#fecf92'],
  blues: ['#c6dbef', '#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#08519c', '#08306b'],
  greens: ['#c7e9c0', '#a1d99b', '#74c476', '#41ab5d', '#238b45', '#006d2c', '#00441b'],
  oranges: ['#fdd0a2', '#fdae6b', '#fd8d3c', '#f16913', '#d94801', '#a63603', '#7f2704'],
  purples: ['#dadaeb', '#bcbddc', '#9e9ac8', '#807dba', '#6a51a3', '#54278f', '#3f007d'],
} as const satisfies Record<string, readonly string[]>;

export type SequentialScheme = keyof typeof SEQUENTIAL_SCHEMES;

export const DEFAULT_SEQUENTIAL_SCHEME: SequentialScheme = 'viridis';

/** A sequential colour scale as a component states it (`color_scale`): the
 *  column whose distinct values are coloured, an optional column giving their
 *  order, and the ramp. Mirrors `ColorScale` in depictio/models. */
export interface ColorScaleSpec {
  column: string;
  order_by?: string | null;
  scheme?: SequentialScheme | null;
}

/** `spec` when it names a column, else null (a component without a scale). */
export function readColorScale(raw: unknown): ColorScaleSpec | null {
  if (!raw || typeof raw !== 'object') return null;
  const spec = raw as Partial<ColorScaleSpec>;
  return typeof spec.column === 'string' && spec.column ? (spec as ColorScaleSpec) : null;
}

const hexToRgb = (hex: string): [number, number, number] => {
  const h = hex.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
};

const rgbToHex = (rgb: readonly number[]): string =>
  `#${rgb.map((c) => Math.round(Math.max(0, Math.min(255, c))).toString(16).padStart(2, '0')).join('')}`;

/** The colour at `t` (0 to 1, clamped) along a ramp. Unknown scheme: viridis. */
export function sequentialColor(scheme: string | null | undefined, t: number): string {
  const stops: readonly string[] =
    SEQUENTIAL_SCHEMES[(scheme ?? DEFAULT_SEQUENTIAL_SCHEME) as SequentialScheme] ??
    SEQUENTIAL_SCHEMES[DEFAULT_SEQUENTIAL_SCHEME];
  const x = Number.isFinite(t) ? Math.max(0, Math.min(1, t)) : 0;
  const pos = x * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(pos));
  const f = pos - i;
  const a = hexToRgb(stops[i]);
  const b = hexToRgb(stops[i + 1]);
  return rgbToHex(a.map((c, k) => c + (b[k] - c) * f));
}

/** `n` evenly spaced colours along a ramp, for a legend's gradient. */
export function sequentialRamp(scheme: string | null | undefined, n = 9): string[] {
  const count = Math.max(2, Math.floor(n));
  return Array.from({ length: count }, (_, i) => sequentialColor(scheme, i / (count - 1)));
}

/** What orders values: a number when every key reads as one, else text. */
export type SequentialOrderKey = string | number | null | undefined;

/**
 * The distinct non-empty `values`, in the order a sequential scale walks them:
 * by the key `orderBy` gives each (numerically when every key present is a
 * number, naturally otherwise; a value with no key goes last), ties and the
 * no-`orderBy` case by `sortCategoryValues`' natural sort.
 */
export function sequentialOrder(
  values: readonly unknown[],
  orderBy?: ((value: string) => SequentialOrderKey) | ReadonlyMap<string, SequentialOrderKey> | null,
): string[] {
  // A ramp walks the values in time: `30min` before `1h`, `18h` after `2h`.
  const natural = sortNaturalOrDuration(sortCategoryValues(values));
  if (!orderBy) return natural;
  const keyOf = (v: string): SequentialOrderKey =>
    typeof orderBy === 'function' ? orderBy(v) : orderBy.get(v);
  const keys = new Map(natural.map((v) => [v, keyOf(v)] as const));
  const blank = (k: SequentialOrderKey) => k === null || k === undefined || k === '';
  const present = [...keys.values()].filter((k) => !blank(k));
  const numeric = present.length > 0 && present.every((k) => Number.isFinite(Number(k)));
  const rank = new Map(natural.map((v, i) => [v, i] as const));
  return [...natural].sort((a, b) => {
    const ka = keys.get(a);
    const kb = keys.get(b);
    if (blank(ka) !== blank(kb)) return blank(ka) ? 1 : -1;
    if (!blank(ka) && !blank(kb)) {
      const d = numeric ? Number(ka) - Number(kb) : COLLATOR.compare(String(ka), String(kb));
      if (d !== 0) return d;
    }
    return (rank.get(a) ?? 0) - (rank.get(b) ?? 0);
  });
}

/**
 * Every distinct value of `values` mapped to a colour on a sequential ramp:
 * the first in `sequentialOrder` takes the ramp's start, the last its end, the
 * rest spread evenly between (a lone value takes the middle). Ordinal on
 * purpose: day 0, 1 and 14 are three steps, not 1/14th apart, so a handful of
 * timepoints stay distinguishable.
 */
export function sequentialColorMap(
  values: readonly unknown[],
  orderBy?: ((value: string) => SequentialOrderKey) | ReadonlyMap<string, SequentialOrderKey> | null,
  scheme?: string | null,
): Map<string, string> {
  const ordered = sequentialOrder(values, orderBy);
  const map = new Map<string, string>();
  ordered.forEach((value, i) => {
    map.set(value, sequentialColor(scheme, ordered.length === 1 ? 0.5 : i / (ordered.length - 1)));
  });
  return map;
}
