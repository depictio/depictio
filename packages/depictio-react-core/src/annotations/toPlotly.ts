/**
 * Pure conversion of stored annotations into Plotly layout shapes, layout
 * annotations and overlay traces. Every colour goes through `resolveColor`
 * (Mantine palette → concrete value); this module never emits a colour
 * literal of its own.
 */
import type { Annotations, Data, Shape } from 'plotly.js';

import type {
  AnnotationColor,
  ArrowNote,
  AxisValue,
  MarkedPoints,
  RefLine,
  RenderableAnnotation,
  SelectionRegion,
  XRange,
  YRange,
} from './types';
import { numberBadge } from './types';
import type { AnnotationStats } from './summary';
import { annotationHoverText } from './summary';
import type { RenderedPoint, RenderedPoints } from './renderedPoints';
import { findRenderedPoint, sameAxisValue } from './renderedPoints';

export interface AnnotationTraceLike {
  x?: unknown[];
  y?: unknown[];
  customdata?: unknown[];
  /** A scatter trace drawn as a line (see `normalizeTraces`). */
  lines?: boolean;
}

export interface AnnotationsToPlotlyOptions {
  resolveColor: (name: AnnotationColor, shade?: number) => string;
  /** Label text colour; defaults to the annotation's own resolved colour. */
  fontColor?: string;
  /**
   * The figure's traces, used to resolve marked points by selection id and to
   * count the data points inside a range.
   */
  traces?: AnnotationTraceLike[];
  /** Index of the selection column inside each trace's customdata rows. */
  selectionColumnIndex?: number;
  /** Annotation drawn emphasised (thicker line, higher opacity). */
  highlightId?: string | null;
  /**
   * Where the figure drew the points of box, violin and bar traces (see
   * `renderedPointsFromGraph`). Marked points on those traces are ringed
   * there, with shapes; without it they are ringed at their data coords.
   */
  renderedPoints?: RenderedPoints | null;
  /**
   * Top-edge labels already drawn by another call (the saved annotations when
   * this call draws the preview), so the new ones stack above them.
   */
  topLabelOffset?: number;
}

export interface AnnotationsToPlotlyResult {
  shapes: Partial<Shape>[];
  annotations: Partial<Annotations>[];
  overlayTraces: Partial<Data>[];
  /**
   * Per annotation id: marked points asked for / found, or data points inside
   * a range (when the axis can be compared). Other kinds have no entry.
   */
  stats: Record<string, AnnotationStats>;
  /** Labels stacked along the plot's top edge (x ranges, vertical lines). */
  topLabelCount: number;
}

export const DEFAULT_COLOR: AnnotationColor = 'yellow';
export const DEFAULT_RANGE_OPACITY = 0.15;
export const DEFAULT_LINE_WIDTH = 1.5;
export const DEFAULT_POINT_RING_WIDTH = 2;
export const POINT_MARKER_SIZE = 14;
/** Narrowest line a marked series is re-drawn with (px). */
export const SERIES_MIN_WIDTH = 3;
/** Height of one row of stacked top-edge labels. */
export const TOP_LABEL_ROW_PX = 16;
export const OVERLAY_TRACE_PREFIX = 'annotation-';
/** Opacity factor and outline dash of the preview drawn before saving. */
export const PREVIEW_OPACITY_FACTOR = 0.6;
export const PREVIEW_DASH = 'dash';

/**
 * Add an alpha channel to a `#rgb`/`#rrggbb`/`rgb()` colour. Anything it
 * cannot parse is returned unchanged.
 */
export function withAlpha(color: string, alpha: number): string {
  const a = Math.min(1, Math.max(0, alpha));
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim());
  if (hex) {
    let h = hex[1];
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    const n = parseInt(h, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  }
  const rgb = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i.exec(color.trim());
  if (rgb) return `rgba(${rgb[1]}, ${rgb[2]}, ${rgb[3]}, ${a})`;
  return color;
}

function labelText(item: RenderableAnnotation): string {
  const { label } = item.annotation;
  return item.number == null ? label : `${numberBadge(item.number)} ${label}`;
}

function compareItems(a: RenderableAnnotation, b: RenderableAnnotation): number {
  const an = a.number ?? Number.POSITIVE_INFINITY;
  const bn = b.number ?? Number.POSITIVE_INFINITY;
  if (an !== bn) return an < bn ? -1 : 1;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** Read the selection id of row `i` in a trace's customdata. */
function selectionIdAt(customdata: unknown[], i: number, col: number): unknown {
  const row = customdata[i];
  if (Array.isArray(row)) return row[col];
  return col === 0 ? row : undefined;
}

interface ResolvedPoints {
  /** Rings drawn by the overlay trace, at data coordinates. */
  xs: AxisValue[];
  ys: AxisValue[];
  /** Rings drawn as shapes, where a positioned trace drew the point. */
  drawn: RenderedPoint[];
  /** Whole lines marked by their id (a line trace whose points all share it). */
  series: Series[];
  expected: number;
}

interface Series {
  x: unknown[];
  y: unknown[];
}

/**
 * The id every point of a line trace shares, when the trace is one series
 * (e.g. one sample of a MultiQC line graph); null otherwise.
 */
function seriesId(trace: AnnotationTraceLike, col: number): string | null {
  const cd = trace.customdata;
  if (!trace.lines || !Array.isArray(cd) || cd.length < 2) return null;
  const first = selectionIdAt(cd, 0, col);
  if (first == null) return null;
  const key = String(first);
  for (let i = 1; i < cd.length; i++) {
    const id = selectionIdAt(cd, i, col);
    if (id == null || String(id) !== key) return null;
  }
  return key;
}

/**
 * The drawn point of row `i` of trace `t`, when that trace is positioned and
 * the point still shows the row (same position or same value: a stacked bar
 * reports its top, a jittered box point its offset position).
 */
function renderedRow(
  rendered: RenderedPoints | null | undefined,
  t: number,
  i: number,
  x: AxisValue,
  y: AxisValue,
): RenderedPoint | null {
  const trace = rendered?.get(t);
  const p = trace?.byIndex.get(i);
  if (!trace || !p) return null;
  const [pos, value] = trace.posLetter === 'x' ? [x, y] : [y, x];
  return sameAxisValue(p.pos, pos) || sameAxisValue(p.value, value) ? p : null;
}

function resolvePoints(geom: MarkedPoints, opts: AnnotationsToPlotlyOptions): ResolvedPoints {
  const ids = geom.ids ?? [];
  const coords = geom.coords ?? [];
  const rendered = opts.renderedPoints;
  if (ids.length && geom.column) {
    const wanted = new Set(ids.map((v) => String(v)));
    const xs: AxisValue[] = [];
    const ys: AxisValue[] = [];
    const drawn: RenderedPoint[] = [];
    const series: Series[] = [];
    const col = opts.selectionColumnIndex;
    if (col != null && col >= 0 && opts.traces) {
      const seen = new Set<string>();
      opts.traces.forEach((trace, t) => {
        const cd = trace.customdata;
        if (!Array.isArray(cd) || !Array.isArray(trace.x) || !Array.isArray(trace.y)) return;
        // A marked line is drawn whole, not as a ring on each of its points.
        const whole = seriesId(trace, col);
        if (whole != null) {
          if (wanted.has(whole) && !seen.has(whole)) {
            seen.add(whole);
            series.push({ x: trace.x, y: trace.y });
          }
          return;
        }
        for (let i = 0; i < cd.length; i++) {
          const id = selectionIdAt(cd, i, col);
          if (id == null) continue;
          const key = String(id);
          if (!wanted.has(key) || seen.has(key)) continue;
          const x = trace.x[i];
          const y = trace.y[i];
          if (!isAxisValue(x) || !isAxisValue(y)) continue;
          seen.add(key);
          const p = renderedRow(rendered, t, i, x, y);
          if (p) {
            drawn.push(p);
          } else {
            xs.push(x);
            ys.push(y);
          }
        }
      });
    }
    if (xs.length || drawn.length || series.length || !coords.length) {
      return { xs, ys, drawn, series, expected: wanted.size };
    }
  }
  const xs: AxisValue[] = [];
  const ys: AxisValue[] = [];
  const drawn: RenderedPoint[] = [];
  const used = new Set<RenderedPoint>();
  for (const c of coords) {
    const p = findRenderedPoint(rendered, c, used);
    if (p === undefined) {
      xs.push(c.x);
      ys.push(c.y);
    } else if (p) {
      used.add(p);
      drawn.push(p);
    }
  }
  return { xs, ys, drawn, series: [], expected: coords.length };
}

/** The series joined into one trace's x/y, with a gap between them. */
function joinSeries(series: Series[]): { x: unknown[]; y: unknown[] } {
  const x: unknown[] = [];
  const y: unknown[] = [];
  series.forEach((s, i) => {
    if (i > 0) {
      x.push(null);
      y.push(null);
    }
    x.push(...s.x);
    y.push(...s.y);
  });
  return { x, y };
}

/** A point near the middle of a series to hang its label on, or null. */
function seriesLabelPoint(s: Series): { x: AxisValue; y: AxisValue } | null {
  const n = Math.min(s.x.length, s.y.length);
  const mid = Math.floor(n / 2);
  for (let k = 0; k < n; k++) {
    // mid, mid+1, mid-1, mid+2... : the nearest drawable point to the middle.
    const i = mid + (k % 2 === 0 ? k / 2 : -(k + 1) / 2);
    if (i < 0 || i >= n) continue;
    const x = s.x[i];
    const y = s.y[i];
    if (isAxisValue(x) && isAxisValue(y)) return { x, y };
  }
  return null;
}

/**
 * The shape shading a marked-points region: a rect for a box, a closed path
 * for a lasso (numeric axes only: an SVG path cannot hold categories or
 * dates). Null when the region cannot be drawn.
 */
export function regionShape(region: SelectionRegion): Partial<Shape> | null {
  if (region.shape === 'box') {
    return { type: 'rect', x0: region.x0, x1: region.x1, y0: region.y0, y1: region.y1 };
  }
  const { x, y } = region;
  if (x.length < 3 || x.length !== y.length) return null;
  const finite = (v: AxisValue): v is number => typeof v === 'number' && Number.isFinite(v);
  if (!x.every(finite) || !y.every(finite)) return null;
  const path = x.map((xi, i) => `${i === 0 ? 'M' : 'L'}${xi},${y[i]}`).join(' ') + ' Z';
  return { type: 'path', path };
}

function isAxisValue(v: unknown): v is AxisValue {
  return (typeof v === 'number' && Number.isFinite(v)) || typeof v === 'string';
}

/** A comparable position: numbers as is, date strings as epoch ms, else null. */
function comparable(v: unknown, dates: boolean): number | null {
  if (dates) {
    if (typeof v !== 'string') return null;
    const t = Date.parse(v);
    return Number.isFinite(t) ? t : null;
  }
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/**
 * How many data points of `traces` have their `axis` value inside [a, b].
 * Numeric and date axes only: undefined when the bounds or the values cannot
 * be compared (categories, no traces).
 */
export function countInRange(
  traces: AnnotationTraceLike[] | undefined,
  axis: 'x' | 'y',
  a: AxisValue,
  b: AxisValue,
): number | undefined {
  if (!traces?.length) return undefined;
  const dates = typeof a === 'string' || typeof b === 'string';
  const lo0 = comparable(a, dates);
  const hi0 = comparable(b, dates);
  if (lo0 == null || hi0 == null) return undefined;
  const lo = Math.min(lo0, hi0);
  const hi = Math.max(lo0, hi0);
  let count = 0;
  let compared = false;
  for (const trace of traces) {
    const values = trace[axis];
    if (!Array.isArray(values)) continue;
    for (const v of values) {
      const c = comparable(v, dates);
      if (c == null) continue;
      compared = true;
      if (c >= lo && c <= hi) count++;
    }
  }
  return compared ? count : undefined;
}

export function annotationsToPlotly(
  items: RenderableAnnotation[],
  opts: AnnotationsToPlotlyOptions,
): AnnotationsToPlotlyResult {
  const shapes: Partial<Shape>[] = [];
  const annotations: Partial<Annotations>[] = [];
  const overlayTraces: Partial<Data>[] = [];
  const stats: Record<string, AnnotationStats> = {};
  // Labels on the top edge all sit at y = 1: each one goes a row higher than
  // the previous, so neighbouring ranges and lines never print over each other.
  let topLabelCount = 0;
  const nextTopShift = () => {
    const row = (opts.topLabelOffset ?? 0) + topLabelCount;
    topLabelCount += 1;
    return row * TOP_LABEL_ROW_PX;
  };

  for (const item of [...items].sort(compareItems)) {
    const { annotation } = item;
    const geom = annotation.geometry;
    const preview = item.preview === true;
    // A preview is drawn faded: every opacity below goes through `fade`.
    const fade = (v: number) => (preview ? v * PREVIEW_OPACITY_FACTOR : v);
    const style = annotation.style ?? {};
    const colorName = annotation.color ?? DEFAULT_COLOR;
    const color = opts.resolveColor(colorName);
    const fontColor = opts.fontColor ?? color;
    const hi = !preview && opts.highlightId != null && opts.highlightId === item.id;
    const text = labelText(item);
    const name = `${OVERLAY_TRACE_PREFIX}${item.id}`;
    // Saved labels carry their thread id (`name`) and the facts measured on
    // the data (`hovertext`, filled in once the geometry is resolved); a
    // click on them opens the thread. The preview is never clickable.
    const labelIndexes: number[] = [];
    const pushLabel = (a: Partial<Annotations>) => {
      labelIndexes.push(annotations.length);
      // `name` is a valid Plotly annotation attribute missing from the types.
      annotations.push(preview ? a : ({ ...a, name, captureevents: true } as Partial<Annotations>));
    };
    const label = (extra: Partial<Annotations>): Partial<Annotations> => ({
      text,
      showarrow: false,
      font: { color: fontColor, size: hi ? 12 : 11 },
      ...(preview ? { opacity: PREVIEW_OPACITY_FACTOR } : {}),
      ...extra,
    });

    switch (geom.kind) {
      case 'x_range':
      case 'y_range': {
        const base = style.opacity ?? DEFAULT_RANGE_OPACITY;
        const opacity = fade(hi ? Math.min(1, base + 0.15) : base);
        const common: Partial<Shape> = {
          type: 'rect',
          layer: 'below',
          fillcolor: color,
          opacity,
          line: preview ? { width: 1.5, color, dash: PREVIEW_DASH } : { width: hi ? 2 : 0, color },
          name,
        };
        if (geom.kind === 'x_range') {
          const g = geom as XRange;
          const inRange = countInRange(opts.traces, 'x', g.x0, g.x1);
          if (inRange != null) stats[item.id] = { inRange };
          shapes.push({ ...common, xref: 'x', yref: 'paper', x0: g.x0, x1: g.x1, y0: 0, y1: 1 });
          pushLabel(
            label({
              xref: 'x',
              yref: 'paper',
              x: g.x0,
              y: 1,
              xanchor: 'left',
              yanchor: 'bottom',
              yshift: nextTopShift(),
            }),
          );
        } else {
          const g = geom as YRange;
          const inRange = countInRange(opts.traces, 'y', g.y0, g.y1);
          if (inRange != null) stats[item.id] = { inRange };
          shapes.push({ ...common, xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: g.y0, y1: g.y1 });
          pushLabel(
            label({
              xref: 'paper',
              yref: 'y',
              x: 1,
              y: Math.max(g.y0, g.y1),
              xanchor: 'right',
              yanchor: 'bottom',
            }),
          );
        }
        break;
      }
      case 'ref_line': {
        const g = geom as RefLine;
        const width = (style.width ?? DEFAULT_LINE_WIDTH) * (hi ? 2 : 1);
        const line = { color, width, dash: preview ? PREVIEW_DASH : (style.dash ?? 'dash') };
        if (g.axis === 'x') {
          shapes.push({
            type: 'line',
            layer: 'above',
            xref: 'x',
            yref: 'paper',
            x0: g.value,
            x1: g.value,
            y0: 0,
            y1: 1,
            line,
            opacity: fade(style.opacity ?? 1),
            name,
          });
          pushLabel(
            label({
              xref: 'x',
              yref: 'paper',
              x: g.value,
              y: 1,
              xanchor: 'left',
              yanchor: 'bottom',
              yshift: nextTopShift(),
            }),
          );
        } else {
          shapes.push({
            type: 'line',
            layer: 'above',
            xref: 'paper',
            yref: 'y',
            x0: 0,
            x1: 1,
            y0: g.value,
            y1: g.value,
            line,
            opacity: fade(style.opacity ?? 1),
            name,
          });
          pushLabel(
            label({ xref: 'paper', yref: 'y', x: 1, y: g.value, xanchor: 'right', yanchor: 'bottom' }),
          );
        }
        break;
      }
      case 'points': {
        const g = geom as MarkedPoints;
        const { xs, ys, drawn, series, expected } = resolvePoints(g, opts);
        stats[item.id] = { expected, found: xs.length + drawn.length + series.length };
        const fill = style.fill_opacity ?? DEFAULT_RANGE_OPACITY;
        const region = g.region && fill > 0 ? regionShape(g.region) : null;
        if (region) {
          shapes.push({
            ...region,
            xref: 'x',
            yref: 'y',
            layer: 'below',
            fillcolor: color,
            opacity: fade(hi ? Math.min(1, fill + 0.15) : fill),
            line: { width: hi ? 1.5 : 1, color, dash: preview ? PREVIEW_DASH : 'dot' },
            name,
          });
        }
        const ringOpacity = fade(style.opacity ?? 1);
        const ringSize = hi ? POINT_MARKER_SIZE + 4 : POINT_MARKER_SIZE;
        const ringLine = { width: (style.width ?? DEFAULT_POINT_RING_WIDTH) * (hi ? 1.5 : 1), color };
        const hover = preview
          ? { hoverinfo: 'skip' }
          : {
              hoverinfo: 'text',
              hovertext: `${annotation.label}<br>${annotationHoverText(annotation, stats[item.id])}`,
            };
        if (series.length) {
          // Marked lines: re-drawn over the data, thicker, in the annotation colour.
          const width = Math.max(SERIES_MIN_WIDTH, ringLine.width * 2);
          overlayTraces.push({
            type: 'scatter',
            mode: 'lines',
            ...joinSeries(series),
            connectgaps: false,
            name,
            ...hover,
            showlegend: false,
            opacity: ringOpacity,
            line: { color, width, dash: preview ? PREVIEW_DASH : 'solid' },
          } as Partial<Data>);
        }
        if (xs.length) {
          overlayTraces.push({
            type: 'scatter',
            mode: 'markers',
            x: xs,
            y: ys,
            name,
            // Saved rings are hoverable (their facts in the tooltip) and
            // clickable; `appendAnnotationTraces` turns this off in annotate mode.
            ...hover,
            showlegend: false,
            opacity: ringOpacity,
            marker: { symbol: 'circle-open', size: ringSize, color, line: ringLine },
          } as Partial<Data>);
        }
        // Points a box, violin or bar trace drew away from their data coords
        // (on a category axis, at a numeric position a trace cannot take):
        // pixel-sized circles anchored at the drawn position. Shapes carry no
        // hover or click; the label does.
        const r = ringSize / 2;
        for (const p of drawn) {
          shapes.push({
            type: 'circle',
            xref: 'x',
            yref: 'y',
            xsizemode: 'pixel',
            ysizemode: 'pixel',
            xanchor: p.x,
            yanchor: p.y,
            x0: -r,
            x1: r,
            y0: -r,
            y1: r,
            layer: 'above',
            opacity: ringOpacity,
            line: ringLine,
            name,
          } as Partial<Shape>);
        }
        const first = xs.length
          ? { x: xs[0], y: ys[0] }
          : (drawn[0] ?? (series.length ? seriesLabelPoint(series[0]) : null));
        if (!first) break;
        pushLabel(
          label({
            xref: 'x',
            yref: 'y',
            x: first.x,
            y: first.y,
            xanchor: 'left',
            yanchor: 'bottom',
            xshift: POINT_MARKER_SIZE / 2 + 2,
            yshift: POINT_MARKER_SIZE / 2,
          }),
        );
        break;
      }
      case 'arrow_note': {
        const g = geom as ArrowNote;
        pushLabel({
          text,
          xref: 'x',
          yref: 'y',
          x: g.x,
          y: g.y,
          ax: g.ax ?? -40,
          ay: g.ay ?? -40,
          showarrow: true,
          arrowhead: 2,
          arrowwidth: hi ? 2.5 : 1.5,
          arrowcolor: color,
          bordercolor: color,
          borderwidth: hi ? 2 : 1,
          borderpad: 3,
          bgcolor: withAlpha(color, hi ? 0.3 : 0.2),
          opacity: fade(style.opacity ?? 1),
          font: { color: fontColor, size: hi ? 12 : 11 },
        });
        break;
      }
      case 'geo_note':
        // Map only: drawn by `geoAnnotationsToPlotly`.
        break;
    }
    if (!preview) {
      const hovertext = annotationHoverText(annotation, stats[item.id]);
      for (const i of labelIndexes) annotations[i] = { ...annotations[i], hovertext };
    }
  }

  return { shapes, annotations, overlayTraces, stats, topLabelCount };
}
