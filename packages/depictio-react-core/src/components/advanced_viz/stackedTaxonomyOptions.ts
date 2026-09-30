/**
 * Presentation options of the stacked composition bar that do not depend on
 * the data: which controls the tile offers, what the sample axis is called and
 * where the legend sits. Pure, so the choices are tested without Plotly.
 *
 * The kind stacks any per-sample composition, not only taxa (CCS outcomes per
 * library, structural categories per sample), so a tile can drop the taxonomy
 * controls that mean nothing for it. Every default reproduces the taxonomy
 * tile as it was.
 */

export type TaxonomyControl = 'rank' | 'sample_sort' | 'top_n' | 'normalise';

const ALL_CONTROLS: readonly TaxonomyControl[] = ['rank', 'sample_sort', 'top_n', 'normalise'];

/** Which primary controls the tile offers, given the config's hidden list. */
export function visibleTaxonomyControls(
  hidden: readonly string[] | null | undefined,
): Record<TaxonomyControl, boolean> {
  const off = new Set(hidden ?? []);
  return Object.fromEntries(ALL_CONTROLS.map((c) => [c, !off.has(c)])) as Record<
    TaxonomyControl,
    boolean
  >;
}

/** Sample axis title: unset falls back to the column name, empty hides it. */
export function taxonomyAxisTitle(
  xTitle: string | null | undefined,
  sampleIdCol: string,
): string | undefined {
  if (xTitle === '') return undefined;
  return xTitle ?? sampleIdCol;
}

export type TaxonomyLegendPos = 'bottom' | 'right';

/** Legend under the bars (the taxonomy default) or beside them, where the
 *  tilted sample labels and the axis title cannot run into it. */
export function taxonomyLegend(
  pos: TaxonomyLegendPos | null | undefined,
  denseAxis = false,
): Record<string, unknown> {
  if (pos === 'right') return { orientation: 'v', x: 1.02, xanchor: 'left', y: 1, yanchor: 'top' };
  // A dense axis hides its tick labels, so a bottom legend would float in
  // their empty space; it goes above the bars instead.
  return denseAxis
    ? { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }
    : { orientation: 'h', y: -0.25 };
}

/** Past this many bars the rotated labels overlap each other; hover names each bar. */
export const DENSE_AXIS_BARS = 40;
