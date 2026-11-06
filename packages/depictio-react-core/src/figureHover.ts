/**
 * Hover labels that wear their series' colour.
 *
 * Plotly draws one neutral hover box for every trace, so on a stacked bar or a
 * grouped box plot every segment answers in the same white label and nothing
 * ties a tooltip to the series it names. A trace drawn in one colour (or one
 * colour per point) gets a label in that colour, with dark or white ink,
 * whichever reads better on it. The rest, coloured by a scale or by a colour
 * name this file does not parse, keep the neutral look.
 *
 * It runs on the figure as it is drawn, after the tab-hue tint (figureTint),
 * so a series the tint repainted answers in the hue it is drawn in. A label a
 * figure chose on its own (one that is not its series colour) is kept.
 *
 * Pure: the traces it is given are not modified.
 */

type Json = Record<string, unknown>;

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;
const RGB = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*[\d.]+\s*)?\)$/i;

/** The card's own dark ink and white, for text on a coloured label. */
const INK_DARK = '#212529';
const INK_LIGHT = '#ffffff';
/** Its outline: white, so a label over a bar of its own colour still stands out. */
const EDGE = '#ffffff';

const SCATTER_TYPES: ReadonlySet<string> = new Set([
  'scatter',
  'scattergl',
  'scatterpolar',
  'scatterpolargl',
]);

const asRecord = (v: unknown): Json | null =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : null;

function rgbOf(colour: unknown): [number, number, number] | null {
  if (typeof colour !== 'string') return null;
  const text = colour.trim();
  if (HEX.test(text)) {
    let digits = text.slice(1);
    if (digits.length === 3) digits = [...digits].map((c) => c + c).join('');
    return [0, 2, 4].map((i) => parseInt(digits.slice(i, i + 2), 16)) as [number, number, number];
  }
  const m = RGB.exec(text);
  if (!m) return null;
  const rgb = [Number(m[1]), Number(m[2]), Number(m[3])] as [number, number, number];
  return Math.max(...rgb) <= 255 ? rgb : null;
}

/** Dark or white ink for text on `rgb` (WCAG relative luminance). */
function inkOn(rgb: [number, number, number]): string {
  const channel = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const [r, g, b] = rgb;
  const luminance = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  // Where white ink and the dark ink (luminance 0.018) have the same contrast.
  return luminance > 0.217 ? INK_DARK : INK_LIGHT;
}

/**
 * What a trace is drawn in: one colour, or one per point, else null. Bars,
 * histograms, boxes and scatter markers carry it on `marker.color`; a
 * line-only scatter on `line.color`.
 */
export function seriesColour(trace: unknown): string | string[] | null {
  const t = asRecord(trace);
  if (!t) return null;
  const marker = asRecord(t.marker);
  const line = asRecord(t.line);
  const candidates: unknown[] = [marker?.color];
  const kind = String(t.type ?? 'scatter');
  if (SCATTER_TYPES.has(kind) && !String(t.mode ?? 'markers').includes('markers')) {
    candidates.unshift(line?.color);
  }
  for (const c of candidates) {
    if (rgbOf(c)) return c as string;
    if (Array.isArray(c) && c.length > 0 && c.every((v) => rgbOf(v))) return c as string[];
  }
  return null;
}

const same = (a: unknown, b: unknown) =>
  typeof a === 'string' && typeof b === 'string' && a.trim().toLowerCase() === b.trim().toLowerCase();

/**
 * A column Plotly Express was told to title "" is named nothing in its hover
 * template, which then reads "=manta". That line says nothing (the value is
 * on the axis), so it goes.
 */
function withoutUnnamedLines(template: unknown): string | null {
  if (typeof template !== 'string' || !template.includes('=%{')) return null;
  const parts = template.split('<br>');
  const kept = parts.filter((p) => !p.startsWith('=%{'));
  return kept.length > 0 && kept.length !== parts.length ? kept.join('<br>') : null;
}

/**
 * `after` with each coloured trace's hover label in its colour. `before` is the
 * figure as the server drew it, so a label that already carries a trace's
 * pre-tint colour (the server's own) is repainted to the colour now drawn.
 */
export function followSeriesHover(before: unknown[], after: unknown[]): unknown[] {
  let changed = false;
  const out = after.map((trace, i) => {
    const t = asRecord(trace);
    if (!t) return trace;
    let next: Json = t;
    const template = withoutUnnamedLines(t.hovertemplate);
    if (template !== null) next = { ...next, hovertemplate: template };
    const colour = seriesColour(t);
    if (colour !== null) {
      const own = asRecord(t.hoverlabel);
      const drawnBefore = seriesColour(before[i]);
      const server = own?.bgcolor;
      const mine =
        server === undefined ||
        server === null ||
        (typeof drawnBefore === 'string' && same(server, drawnBefore)) ||
        (Array.isArray(drawnBefore) && Array.isArray(server) && drawnBefore.every((c, k) => same(c, server[k])));
      if (mine) {
        const colours = Array.isArray(colour) ? colour : [colour];
        const inks = colours.map((c) => inkOn(rgbOf(c)!));
        next = {
          ...next,
          hoverlabel: {
            ...own,
            bgcolor: colour,
            bordercolor: EDGE,
            font: { ...asRecord(own?.font), color: Array.isArray(colour) ? inks : inks[0] },
          },
        };
      }
    }
    if (next !== t) changed = true;
    return next;
  });
  return changed ? out : after;
}
