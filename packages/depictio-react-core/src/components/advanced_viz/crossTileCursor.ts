/**
 * Pure helpers for the genomic plots that share a cursor and a window with a
 * genome browser tile through the highlight bus (`highlight/bus.ts`) and the
 * view-window store (`highlight/viewWindow.ts`).
 *
 * Nothing here touches React or Plotly: a renderer hands in the bus event and
 * the contigs it draws, and gets back the Plotly shape to merge into its
 * layout, or the x range to fit.
 */
import type { HighlightEvent } from '../../highlight/bus';
import type { ViewWindowEvent } from '../../highlight/viewWindow';

/** A contig name with the spellings that differ between tools folded away
 *  ("chr8", "Chr8" and "8" are one contig). */
function contigKey(name: string): string {
  return name.trim().toLowerCase().replace(/^chr/, '');
}

/**
 * The contig of `chroms` an event's `entity` (or one of its `aliases`, the
 * other names a genome browser knows the contig by) names, or `null`. An exact
 * match on any name wins, `entity` first; otherwise the `chr` prefix and the
 * case are ignored. The bus is shared with the protein tiles, whose entities
 * are proteins: those match nothing.
 */
export function matchChromosome(
  entity: string | undefined | null,
  chroms: Iterable<string>,
  aliases?: readonly string[],
): string | null {
  const names = [entity, ...(aliases ?? [])].filter((n): n is string => Boolean(n));
  if (!names.length) return null;
  const list = [...chroms];
  for (const name of names) if (list.includes(name)) return name;
  for (const name of names) {
    const key = contigKey(name);
    if (!key) continue;
    const found = list.find((c) => contigKey(String(c)) === key);
    if (found !== undefined) return found;
  }
  return null;
}

/** The span a hover event covers on the genomic axis, ends ordered. `null`
 *  when the event has no usable position. */
export function eventSpan(event: HighlightEvent | null): { start: number; end: number } | null {
  if (!event) return null;
  const start = Number(event.start);
  const end = Number(event.end ?? event.start);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return { start: Math.min(start, end), end: Math.max(start, end) };
}

/**
 * The Plotly shape for a cursor (`x0 === x1`: a vertical line) or a span (a
 * translucent band with an outline, so even a narrow one stays visible), over
 * the full height of the plot. `color` is the hovered mark's colour or the
 * theme's.
 */
export function cursorShape(x0: number, x1: number, color: string): Record<string, unknown> {
  if (x1 <= x0) {
    return {
      type: 'line',
      xref: 'x',
      yref: 'paper',
      x0,
      x1: x0,
      y0: 0,
      y1: 1,
      line: { color, width: 1.5 },
      layer: 'above',
    };
  }
  return {
    type: 'rect',
    xref: 'x',
    yref: 'paper',
    x0,
    x1,
    y0: 0,
    y1: 1,
    fillcolor: color,
    line: { color, width: 1 },
    opacity: 0.3,
    layer: 'above',
  };
}

/**
 * A ring of `radiusPx` pixels around the data point (`x`, `y`): the mark a
 * hover from another tile puts on the point it refers to. Sized in pixels from
 * the point, so it stays round and the same size whatever the axes show.
 */
export function hoverRingShape(
  x: number,
  y: number,
  color: string,
  radiusPx = 8,
): Record<string, unknown> {
  return {
    type: 'circle',
    xref: 'x',
    yref: 'y',
    xsizemode: 'pixel',
    ysizemode: 'pixel',
    xanchor: x,
    yanchor: y,
    x0: -radiusPx,
    x1: radiusPx,
    y0: -radiusPx,
    y1: radiusPx,
    line: { color, width: 2 },
    fillcolor: 'rgba(0,0,0,0)',
    layer: 'above',
  };
}

/** `layout` with `shape` appended to its own shapes; `layout` itself (same
 *  identity) when there is no shape to add. */
export function withCursorShape<L extends Record<string, unknown>>(
  layout: L,
  shape: Record<string, unknown> | null,
): L {
  if (!shape) return layout;
  const own = Array.isArray(layout.shapes) ? (layout.shapes as unknown[]) : [];
  return { ...layout, shapes: [...own, shape] };
}

/**
 * The shape another tile's hover asks for on a plot whose x axis is `x =
 * offset(chrom) + position`. `offsets` maps each drawn contig to its x offset
 * (0 for a plot of one contig on its own axis). `null` when the event names a
 * contig the plot does not draw.
 */
export function hoverShape(
  event: HighlightEvent | null,
  offsets: ReadonlyMap<string, number>,
  fallbackColor: string,
): Record<string, unknown> | null {
  const span = eventSpan(event);
  if (!event || !span) return null;
  const chrom = matchChromosome(event.entity, offsets.keys(), event.entityAliases);
  if (chrom === null) return null;
  const offset = offsets.get(chrom) ?? 0;
  return cursorShape(offset + span.start, offset + span.end, event.color || fallbackColor);
}

/**
 * The overview band a genome browser's view window draws on a plot whose x axis
 * is `x = offset(chrom) + position` (see `hoverShape` for `offsets`): a
 * translucent rect over the window, drawn behind the marks so the points stay
 * readable, with a thin outline so a window narrow against the whole genome
 * still shows. The plot itself is not zoomed. `null` when the window is not on
 * a contig the plot draws, or has no extent.
 */
export function windowBandShape(
  win: ViewWindowEvent | null,
  offsets: ReadonlyMap<string, number>,
  color: string,
): Record<string, unknown> | null {
  if (!win) return null;
  const chrom = matchChromosome(win.entity, offsets.keys(), win.entityAliases);
  if (chrom === null) return null;
  const start = Number(win.start);
  const end = Number(win.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  const offset = offsets.get(chrom) ?? 0;
  return {
    type: 'rect',
    xref: 'x',
    yref: 'paper',
    x0: offset + start,
    x1: offset + end,
    y0: 0,
    y1: 1,
    fillcolor: color,
    line: { color, width: 1 },
    opacity: 0.18,
    layer: 'below',
  };
}

/**
 * The x range a view window asks for, or `null` when it is not on a contig
 * the plot shows or has no extent. Positions are the plot's own x values.
 */
export function windowRange(
  win: ViewWindowEvent | null,
  shown: Iterable<string>,
): [number, number] | null {
  if (!win) return null;
  if (matchChromosome(win.entity, shown, win.entityAliases) === null) return null;
  if (!Number.isFinite(win.start) || !Number.isFinite(win.end) || win.end <= win.start) {
    return null;
  }
  return [win.start, win.end];
}

/** Where a followed range came from. */
export type RangeSource = 'filter' | 'window';

/**
 * Which of two ranges a plot fits when both exist: the one that changed last
 * (`last`). A region filter that was already there does not pin the axis
 * against a browser the reader then pans, and a window does not undo a region
 * the reader then brushes. With only one, that one.
 */
export function pickRange(
  last: RangeSource,
  filterRange: [number, number] | null,
  window: [number, number] | null,
): [number, number] | null {
  if (!filterRange) return window;
  if (!window) return filterRange;
  return last === 'window' ? window : filterRange;
}

/**
 * The colour Plotly draws a hovered point in: the trace's per-point
 * `marker.color` array at the point, else a single marker colour, else the
 * line colour. `undefined` for anything that is not a colour string (a
 * numeric colour array resolved through a colorscale).
 */
export function hoveredColor(point: unknown): string | undefined {
  const p = point as {
    pointNumber?: number;
    pointIndex?: number;
    fullData?: { marker?: { color?: unknown }; line?: { color?: unknown } };
    data?: { marker?: { color?: unknown }; line?: { color?: unknown } };
  } | null;
  if (!p) return undefined;
  const index = p.pointNumber ?? p.pointIndex;
  const resolve = (c: unknown): string | undefined => {
    const v = Array.isArray(c) ? (index !== undefined ? c[index] : undefined) : c;
    return typeof v === 'string' && v ? v : undefined;
  };
  for (const trace of [p.data, p.fullData]) {
    const found = resolve(trace?.marker?.color) ?? resolve(trace?.line?.color);
    if (found) return found;
  }
  return undefined;
}
