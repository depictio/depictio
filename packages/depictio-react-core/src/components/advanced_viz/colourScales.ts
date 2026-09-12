/**
 * The continuous colour scales every advanced-viz renderer that exposes one
 * offers. Single definition on the React side; its Python twin is `ColourScale`
 * in depictio/models/components/advanced_viz/configs.py and must list the same
 * names in the same order, because a persisted config value is validated there.
 */
export const COLOUR_SCALES = [
  'Viridis',
  'Plasma',
  'Inferno',
  'Magma',
  'Cividis',
  'RdBu',
  'Spectral',
] as const;

export type ColourScale = (typeof COLOUR_SCALES)[number];

/** Past this many distinct values a qualitative palette has nothing left to
 *  say, so the column is read as a measurement whatever its values look like. */
export const MAX_DISCRETE_COLOUR_VALUES = 12;

/**
 * Whether a colour column should get a continuous scale or discrete swatches.
 *
 * Categorical until proven continuous: a colour column of run ids that happen
 * to be integers should still get swatches, so a column only counts as
 * continuous when every non-null entry parses AND either it carries a
 * fractional value or it has more distinct values than a small palette would
 * exhaust.
 *
 * The fractional clause is what keeps a measurement out of the id bucket. A
 * sixteen-library ChIP run colouring by an AUC ratio has eight distinct values,
 * all of them floats: under the distinct-count rule alone it drew eight
 * qualitative swatches labelled `0.31786`, `0.34048`, … and silently dropped
 * the declared `color_scale`. Ids are whole numbers; 0.31786 is not one.
 */
export function looksContinuous(values: unknown[]): boolean {
  let seen = 0;
  let fractional = false;
  const distinct = new Set<string>();
  for (const v of values) {
    if (v === null || v === undefined || v === '') continue;
    const n = Number(v);
    if (!Number.isFinite(n)) return false;
    seen += 1;
    if (!Number.isInteger(n)) fractional = true;
    if (distinct.size <= MAX_DISCRETE_COLOUR_VALUES) distinct.add(String(v));
  }
  return seen > 0 && (fractional || distinct.size > MAX_DISCRETE_COLOUR_VALUES);
}
