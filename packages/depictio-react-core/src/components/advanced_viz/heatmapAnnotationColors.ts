/**
 * Recolouring the categorical annotation strips of a plotly-complexheatmap
 * figure.
 *
 * The server builds the figure and picks each strip's colours from its own
 * palettes (Set2 beside the rows, Dark2 above the columns), so a condition
 * pinned in the dashboard's `category_colors` came out in a colour no other
 * tile drew it in. The strips are recoloured here, once the figure is back,
 * rather than by sending the colours with the request: the figure is cached
 * on a hash of that request, so a dashboard colour edit would recompute every
 * heatmap for what is a restyle.
 *
 * A categorical strip is one heatmap trace per block, hovering
 * `<strip>: %{customdata}`, whose z is the category's position in the strip's
 * categories and whose colorscale gives each position a band of its own. The
 * library also emits one legend entry per category, named
 * `<strip>: <category>`, in that same order, which is where the position of
 * each category is read from: a block of a split heatmap may hold only some of
 * the categories, so its own cells cannot say which band is which.
 */

export type Trace = Record<string, unknown>;

const STRIP_HOVER = /^(.*): %\{customdata\}<extra><\/extra>$/;

/** The categories of each strip, in band order, read off the legend entries. */
export function annotationStripCategories(data: readonly Trace[]): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const t of data) {
    const group = t.legendgroup;
    const name = t.name;
    if (t.type !== 'scatter' || typeof group !== 'string' || typeof name !== 'string') continue;
    const prefix = `${group}: `;
    if (!name.startsWith(prefix)) continue;
    const category = name.slice(prefix.length);
    const list = out.get(group) ?? [];
    if (!list.includes(category)) list.push(category);
    out.set(group, list);
  }
  return out;
}

/**
 * The figure's traces with each categorical strip's values in the colours
 * `coloursFor(strip)` gives them; a value it does not name keeps the colour
 * the server drew it in. Traces are copied, never mutated, and a strip whose
 * bands do not line up with its legend is left as it was rather than coloured
 * wrong.
 */
export function recolourAnnotationStrips(
  data: readonly Trace[],
  coloursFor: (strip: string) => Record<string, string> | null,
): Trace[] {
  const categories = annotationStripCategories(data);
  if (categories.size === 0) return [...data];
  const colours = new Map<string, Record<string, string>>();
  for (const strip of categories.keys()) {
    const pinned = coloursFor(strip);
    if (pinned && Object.keys(pinned).length) colours.set(strip, pinned);
  }
  if (colours.size === 0) return [...data];

  return data.map((t) => {
    // A legend entry: its marker is the swatch.
    const group = typeof t.legendgroup === 'string' ? t.legendgroup : null;
    if (t.type === 'scatter' && group && colours.has(group) && typeof t.name === 'string') {
      const colour = colours.get(group)![t.name.slice(group.length + 2)];
      if (!colour) return t;
      return { ...t, marker: { ...((t.marker as Record<string, unknown>) ?? {}), color: colour } };
    }
    // A strip block: one colorscale band per category.
    if (t.type !== 'heatmap' || typeof t.hovertemplate !== 'string') return t;
    const strip = STRIP_HOVER.exec(t.hovertemplate)?.[1];
    const pinned = strip === undefined ? undefined : colours.get(strip);
    const cats = strip === undefined ? undefined : categories.get(strip);
    const scale = t.colorscale;
    if (!pinned || !cats || !Array.isArray(scale) || scale.length !== cats.length * 2) return t;
    const n = cats.length;
    const recoloured = cats.flatMap((cat, i) => {
      const colour = pinned[cat] ?? (scale[2 * i] as [number, string])[1];
      return [
        [i / n, colour],
        [(i + 1) / n, colour],
      ];
    });
    return { ...t, colorscale: recoloured };
  });
}
