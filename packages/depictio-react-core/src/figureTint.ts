/**
 * Draws a single-series Plotly figure in the tab's hue.
 *
 * Server figures come out in the template's first colour (Plotly Express
 * writes it onto every trace it did not colour by a column), so a histogram or
 * a sorted bar on a teal tab would stay blue. This swaps that default for the
 * tab hue, and only that:
 *
 *  - a trace coloured by data (an array, a colour scale, a coloraxis, a
 *    category's legend group) is left alone, and so is a figure that holds
 *    one, so category, verdict and `color_scale` colours never change;
 *  - a trace whose colour is not the template default (`category_colors`,
 *    `color_discrete_map`, a hand-picked hex) is left alone;
 *  - a figure with several traces is tinted only when every one of them
 *    carries the default (one series, drawn in pieces).
 *
 * Pure: the figure it is given is not modified.
 */

type Json = Record<string, unknown>;

/** Plotly's own first colour, which the figure carries when no template names another. */
const PLOTLY_DEFAULT = '#636efa';

/** Trace types whose marks take one colour from the colorway. */
const TINTABLE_TYPES: ReadonlySet<string> = new Set([
  'bar',
  'histogram',
  'scatter',
  'scattergl',
  'box',
  'violin',
  'funnel',
]);

const asRecord = (v: unknown): Json | null =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : null;

const norm = (c: unknown): string | null =>
  typeof c === 'string' ? c.trim().toLowerCase().replace(/\s+/g, '') : null;

/** The colour the template would give a trace that named none. */
function defaultColours(layout: Json | undefined): Set<string> {
  const out = new Set<string>([PLOTLY_DEFAULT]);
  const own = layout?.colorway;
  const tpl = asRecord(asRecord(layout?.template)?.layout)?.colorway;
  for (const way of [own, tpl]) {
    if (Array.isArray(way) && way.length) {
      const first = norm(way[0]);
      if (first) out.add(first);
    }
  }
  return out;
}

/** What a trace's colour fields say: untouched (no colour), the default, or data/hand-picked. */
type Verdict = 'none' | 'default' | 'data';

function colourVerdict(value: unknown, defaults: Set<string>): Verdict {
  if (value === undefined || value === null || value === '') return 'none';
  const c = norm(value);
  return c !== null && defaults.has(c) ? 'default' : 'data';
}

interface TraceReading {
  /** Whole trace can be tinted. */
  ok: boolean;
  /** It carries at least one explicit default colour. */
  explicitDefault: boolean;
}

function readTrace(trace: unknown, defaults: Set<string>): TraceReading {
  const t = asRecord(trace);
  const bad: TraceReading = { ok: false, explicitDefault: false };
  if (!t || !TINTABLE_TYPES.has(String(t.type ?? 'scatter'))) return bad;
  // A category's own legend entry: its colour is its identity.
  if (typeof t.legendgroup === 'string' && t.legendgroup !== '') return bad;
  const marker = asRecord(t.marker);
  const line = asRecord(t.line);
  if (marker && (marker.coloraxis || marker.colorscale || marker.cmin !== undefined)) return bad;
  if (t.coloraxis) return bad;
  const m = colourVerdict(marker?.color, defaults);
  const l = colourVerdict(line?.color, defaults);
  // A fill such as rgba(255,255,255,0) is a template detail, not a series colour:
  // only a fill that is the default is swapped, and none blocks the tint.
  const f = colourVerdict(t.fillcolor, defaults);
  if (m === 'data' || l === 'data') return bad;
  return { ok: true, explicitDefault: m === 'default' || l === 'default' || f === 'default' };
}

function tintTrace(trace: Json, defaults: Set<string>, hue: string): Json {
  const out: Json = { ...trace };
  const marker = asRecord(trace.marker);
  const line = asRecord(trace.line);
  if (marker && colourVerdict(marker.color, defaults) === 'default') {
    out.marker = { ...marker, color: hue };
  }
  if (line && colourVerdict(line.color, defaults) === 'default') {
    out.line = { ...line, color: hue };
  }
  if (colourVerdict(trace.fillcolor, defaults) === 'default') out.fillcolor = hue;
  return out;
}

export interface TintedFigure {
  data: unknown[];
  layout: Json;
  /** False when the figure was returned as it came. */
  tinted: boolean;
}

/**
 * `data` and `layout` in the tab hue where nothing colours them already, else
 * unchanged. `hue` is a concrete CSS colour; without one nothing happens.
 */
export function tintSingleSeries(
  data: unknown[] | undefined,
  layout: Json | undefined,
  hue: string | null | undefined,
): TintedFigure {
  const traces = data ?? [];
  const lay = layout ?? {};
  const unchanged: TintedFigure = { data: traces, layout: lay, tinted: false };
  if (!hue || traces.length === 0) return unchanged;
  if (lay.coloraxis) return unchanged;
  const defaults = defaultColours(lay);
  const readings = traces.map((t) => readTrace(t, defaults));
  if (readings.some((r) => !r.ok)) return unchanged;
  // Several traces tint together only when each says "default" outright:
  // a bare trace would take the next colorway entry, a series of its own.
  if (traces.length > 1 && !readings.every((r) => r.explicitDefault)) return unchanged;
  return {
    data: traces.map((t) => tintTrace(t as Json, defaults, hue)),
    // Traces that named no colour take the first colorway entry.
    layout: { ...lay, colorway: [hue] },
    tinted: true,
  };
}
