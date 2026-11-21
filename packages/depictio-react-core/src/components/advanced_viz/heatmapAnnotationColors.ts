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

type Rgb = [number, number, number];

function parseColour(c: unknown): Rgb | null {
  if (typeof c !== 'string') return null;
  const s = c.trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s);
  if (hex) {
    const h = hex[1].length === 3 ? hex[1].replace(/./g, (x) => x + x) : hex[1];
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as Rgb;
  }
  const rgb = /^rgba?\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)/i.exec(s);
  return rgb ? [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])] : null;
}

function toLab([r, g, b]: Rgb): [number, number, number] {
  const lin = (v: number) => {
    const x = v / 255;
    return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
  };
  const [R, G, B] = [lin(r), lin(g), lin(b)];
  const X = (0.4124564 * R + 0.3575761 * G + 0.1804375 * B) / 0.95047;
  const Y = 0.2126729 * R + 0.7151522 * G + 0.072175 * B;
  const Z = (0.0193339 * R + 0.119192 * G + 0.9503041 * B) / 1.08883;
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  return [116 * f(Y) - 16, 500 * (f(X) - f(Y)), 200 * (f(Y) - f(Z))];
}

/** CIE76 colour difference; `Infinity` when either side is not a colour. */
export function colourDistance(a: string, b: string): number {
  const x = parseColour(a);
  const y = parseColour(b);
  if (!x || !y) return Infinity;
  const [l1, a1, b1] = toLab(x);
  const [l2, a2, b2] = toLab(y);
  return Math.hypot(l1 - l2, a1 - a2, b1 - b2);
}

/** Closer than this to a scale end and a strip colour reads as part of the matrix. */
export const SCALE_END_MIN_DELTA_E = 20;

/** End colours of Plotly's named scales that the heatmap offers. */
const NAMED_SCALE_ENDS: Record<string, [string, string]> = {
  viridis: ['#440154', '#fde725'],
  plasma: ['#0d0887', '#f0f921'],
  inferno: ['#000004', '#fcffa4'],
  magma: ['#000004', '#fcfdbf'],
  cividis: ['#00204d', '#ffea46'],
  rdbu: ['#67001f', '#053061'],
  spectral: ['#9e0142', '#5e4fa2'],
  rdylbu: ['#a50026', '#313695'],
  bluered: ['#0000ff', '#ff0000'],
  blues: ['#f7fbff', '#08306b'],
  reds: ['#fff5f0', '#67000d'],
  greens: ['#f7fcf5', '#00441b'],
  greys: ['#ffffff', '#000000'],
};

function colorscaleEnds(scale: unknown): string[] {
  if (typeof scale === 'string') {
    const key = scale.toLowerCase().replace(/_r$/, '');
    const ends = NAMED_SCALE_ENDS[key];
    return ends ? [...ends] : [];
  }
  if (!Array.isArray(scale) || scale.length === 0) return [];
  const colours = scale
    .map((stop) => (Array.isArray(stop) ? stop[1] : null))
    .filter((c): c is string => typeof c === 'string');
  return colours.length ? [colours[0], colours[colours.length - 1]] : [];
}

/** The end colours of every value heatmap (any heatmap that is not a strip). */
export function matrixScaleEnds(data: readonly Trace[]): string[] {
  const ends: string[] = [];
  for (const t of data) {
    if (t.type !== 'heatmap') continue;
    if (typeof t.hovertemplate === 'string' && STRIP_HOVER.test(t.hovertemplate)) continue;
    ends.push(...colorscaleEnds(t.colorscale));
  }
  return ends;
}


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
 * wrong. A pinned colour that sits on one of the matrix colour scale's ends
 * (`SCALE_END_MIN_DELTA_E`) is not applied either: the strip would read as part
 * of the matrix, so that value keeps the server's colour.
 */
export function recolourAnnotationStrips(
  data: readonly Trace[],
  coloursFor: (strip: string) => Record<string, string> | null,
): Trace[] {
  const categories = annotationStripCategories(data);
  if (categories.size === 0) return [...data];
  const ends = matrixScaleEnds(data);
  const colours = new Map<string, Record<string, string>>();
  for (const strip of categories.keys()) {
    const pinned = coloursFor(strip);
    if (!pinned) continue;
    const safe = Object.fromEntries(
      Object.entries(pinned).filter(
        ([, c]) => !ends.some((end) => colourDistance(c, end) < SCALE_END_MIN_DELTA_E),
      ),
    );
    if (Object.keys(safe).length) colours.set(strip, safe);
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
