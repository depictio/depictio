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
  XRange,
  YRange,
} from './types';
import { numberBadge } from './types';

export interface AnnotationTraceLike {
  x?: unknown[];
  y?: unknown[];
  customdata?: unknown[];
}

export interface AnnotationsToPlotlyOptions {
  resolveColor: (name: AnnotationColor, shade?: number) => string;
  /** Label text colour; defaults to the annotation's own resolved colour. */
  fontColor?: string;
  /** The figure's traces, used to resolve marked points by selection id. */
  traces?: AnnotationTraceLike[];
  /** Index of the selection column inside each trace's customdata rows. */
  selectionColumnIndex?: number;
  /** Annotation drawn emphasised (thicker line, higher opacity). */
  highlightId?: string | null;
}

export interface PointStats {
  expected: number;
  found: number;
}

export interface AnnotationsToPlotlyResult {
  shapes: Partial<Shape>[];
  annotations: Partial<Annotations>[];
  overlayTraces: Partial<Data>[];
  /** Per marked-points annotation id: how many points were asked for / found. */
  stats: Record<string, PointStats>;
}

export const DEFAULT_COLOR: AnnotationColor = 'yellow';
export const DEFAULT_RANGE_OPACITY = 0.15;
export const DEFAULT_LINE_WIDTH = 1.5;
export const POINT_MARKER_SIZE = 14;
export const OVERLAY_TRACE_PREFIX = 'annotation-';

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
  xs: AxisValue[];
  ys: AxisValue[];
  expected: number;
}

function resolvePoints(geom: MarkedPoints, opts: AnnotationsToPlotlyOptions): ResolvedPoints {
  const ids = geom.ids ?? [];
  const coords = geom.coords ?? [];
  if (ids.length && geom.column) {
    const wanted = new Set(ids.map((v) => String(v)));
    const xs: AxisValue[] = [];
    const ys: AxisValue[] = [];
    const col = opts.selectionColumnIndex;
    if (col != null && col >= 0 && opts.traces) {
      const seen = new Set<string>();
      for (const trace of opts.traces) {
        const cd = trace.customdata;
        if (!Array.isArray(cd) || !Array.isArray(trace.x) || !Array.isArray(trace.y)) continue;
        for (let i = 0; i < cd.length; i++) {
          const id = selectionIdAt(cd, i, col);
          if (id == null) continue;
          const key = String(id);
          if (!wanted.has(key) || seen.has(key)) continue;
          const x = trace.x[i];
          const y = trace.y[i];
          if (!isAxisValue(x) || !isAxisValue(y)) continue;
          seen.add(key);
          xs.push(x);
          ys.push(y);
        }
      }
    }
    if (xs.length || !coords.length) return { xs, ys, expected: wanted.size };
  }
  return {
    xs: coords.map((c) => c.x),
    ys: coords.map((c) => c.y),
    expected: coords.length,
  };
}

function isAxisValue(v: unknown): v is AxisValue {
  return (typeof v === 'number' && Number.isFinite(v)) || typeof v === 'string';
}

export function annotationsToPlotly(
  items: RenderableAnnotation[],
  opts: AnnotationsToPlotlyOptions,
): AnnotationsToPlotlyResult {
  const shapes: Partial<Shape>[] = [];
  const annotations: Partial<Annotations>[] = [];
  const overlayTraces: Partial<Data>[] = [];
  const stats: Record<string, PointStats> = {};

  for (const item of [...items].sort(compareItems)) {
    const { annotation } = item;
    const geom = annotation.geometry;
    const style = annotation.style ?? {};
    const colorName = annotation.color ?? DEFAULT_COLOR;
    const color = opts.resolveColor(colorName);
    const fontColor = opts.fontColor ?? color;
    const hi = opts.highlightId != null && opts.highlightId === item.id;
    const text = labelText(item);
    const name = `${OVERLAY_TRACE_PREFIX}${item.id}`;
    const label = (extra: Partial<Annotations>): Partial<Annotations> => ({
      text,
      showarrow: false,
      font: { color: fontColor, size: hi ? 12 : 11 },
      ...extra,
    });

    switch (geom.kind) {
      case 'x_range':
      case 'y_range': {
        const base = style.opacity ?? DEFAULT_RANGE_OPACITY;
        const opacity = hi ? Math.min(1, base + 0.15) : base;
        const common: Partial<Shape> = {
          type: 'rect',
          layer: 'below',
          fillcolor: color,
          opacity,
          line: { width: hi ? 2 : 0, color },
          name,
        };
        if (geom.kind === 'x_range') {
          const g = geom as XRange;
          shapes.push({ ...common, xref: 'x', yref: 'paper', x0: g.x0, x1: g.x1, y0: 0, y1: 1 });
          annotations.push(
            label({ xref: 'x', yref: 'paper', x: g.x0, y: 1, xanchor: 'left', yanchor: 'bottom' }),
          );
        } else {
          const g = geom as YRange;
          shapes.push({ ...common, xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: g.y0, y1: g.y1 });
          annotations.push(
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
        const line = { color, width, dash: style.dash ?? 'dash' };
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
            opacity: style.opacity ?? 1,
            name,
          });
          annotations.push(
            label({ xref: 'x', yref: 'paper', x: g.value, y: 1, xanchor: 'left', yanchor: 'bottom' }),
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
            opacity: style.opacity ?? 1,
            name,
          });
          annotations.push(
            label({ xref: 'paper', yref: 'y', x: 1, y: g.value, xanchor: 'right', yanchor: 'bottom' }),
          );
        }
        break;
      }
      case 'points': {
        const g = geom as MarkedPoints;
        const { xs, ys, expected } = resolvePoints(g, opts);
        stats[item.id] = { expected, found: xs.length };
        if (!xs.length) break;
        overlayTraces.push({
          type: 'scatter',
          mode: 'markers',
          x: xs,
          y: ys,
          name,
          hoverinfo: 'skip',
          showlegend: false,
          opacity: style.opacity ?? 1,
          marker: {
            symbol: 'circle-open',
            size: hi ? POINT_MARKER_SIZE + 4 : POINT_MARKER_SIZE,
            color,
            line: { width: (style.width ?? 2) * (hi ? 1.5 : 1), color },
          },
        } as Partial<Data>);
        annotations.push(
          label({
            xref: 'x',
            yref: 'y',
            x: xs[0],
            y: ys[0],
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
        annotations.push({
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
          opacity: style.opacity ?? 1,
          font: { color: fontColor, size: hi ? 12 : 11 },
        });
        break;
      }
    }
  }

  return { shapes, annotations, overlayTraces, stats };
}
