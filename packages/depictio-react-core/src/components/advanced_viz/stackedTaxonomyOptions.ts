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

/** Sample axis title: unset reads "Sample", an empty string hides it. */
export function taxonomyAxisTitle(xTitle: string | null | undefined): string | undefined {
  if (xTitle === '') return undefined;
  return xTitle ?? 'Sample';
}

/** Past this many bars the tilted labels overlap each other; hover names each
 *  bar instead. */
export const DENSE_AXIS_BARS = 40;

/** Whether `bars` samples make the axis too dense for its tick labels. */
export function isDenseTaxonomyAxis(bars: number): boolean {
  return bars > DENSE_AXIS_BARS;
}

export type TaxonomyLegendPos = 'right' | 'bottom';

/** What every placement shares: the key is titled with the rank it shows. */
const legendCommon = (title: string) => ({ title: { text: `${title} ` }, font: { size: 10 } });

/**
 * The taxa's legend. `right` (the default): a column right of the plot, clear
 * of the tilted sample labels. `bottom`: rows under the whole figure, below the
 * sample labels and the axis title; on a dense axis, whose labels are hidden,
 * rows above the bars instead, where it does not float in their empty band.
 */
export function taxonomyLegend(
  pos: TaxonomyLegendPos | null | undefined,
  denseAxis: boolean,
  title: string,
): Record<string, unknown> {
  if (pos !== 'bottom') {
    return { orientation: 'v', x: 1.02, xanchor: 'left', y: 1, yanchor: 'top', ...legendCommon(title) };
  }
  if (denseAxis) {
    return { orientation: 'h', x: 0, xanchor: 'left', y: 1.02, yanchor: 'bottom', ...legendCommon(title) };
  }
  // Anchored to the figure's own bottom edge (`yref: 'container'`), so it
  // clears the automargined sample labels whatever their length.
  return {
    orientation: 'h',
    x: 0,
    xanchor: 'left',
    y: 0,
    yref: 'container',
    yanchor: 'bottom',
    ...legendCommon(title),
  };
}

/** Extra top margin, px, a legend drawn above the bars takes. */
export function taxonomyLegendTopPx(
  pos: TaxonomyLegendPos | null | undefined,
  denseAxis: boolean,
  showLegend: boolean,
): number {
  return showLegend && pos === 'bottom' && denseAxis ? 40 : 0;
}
