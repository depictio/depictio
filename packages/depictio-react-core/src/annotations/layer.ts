/**
 * Pure helpers behind the annotation layer and the "Annotate" mode of Plotly
 * figures: which Plotly interaction each drawing tool uses, how stored threads
 * become drawable annotations, and how raw Plotly data/events are normalised
 * before capture. No React, no DOM: everything here is unit tested.
 */
import { OVERLAY_TRACE_PREFIX } from './toPlotly';
import type {
  Annotation,
  AnnotationColor,
  AnnotationKind,
  AnnotationStyle,
  AxisValue,
  Geometry,
  RenderableAnnotation,
} from './types';
import { MAX_LABEL_CHARS } from './types';
import { decodeBdata, extractCustomdataIds, isPlotlyTypedArray } from '../plotlyData';

/** Drawing tool of the annotate mode (same union as the viewer's UI store). */
export type AnnotateTool = 'range' | 'line' | 'points' | 'note';

export interface AnnotateOptions {
  /** Axis a dragged range covers. */
  rangeAxis: 'x' | 'y';
  /** Axis a reference line is drawn across (x = vertical line at an x value). */
  lineAxis: 'x' | 'y';
  /** Plotly selection gesture for marked points. */
  selectMode: 'lasso' | 'select';
}

export const DEFAULT_ANNOTATE_OPTIONS: AnnotateOptions = {
  rangeAxis: 'x',
  lineAxis: 'x',
  selectMode: 'lasso',
};

export type CaptureEvent = 'relayout' | 'click' | 'selected';

export interface AnnotateInteraction {
  /** `layout.dragmode` while the tool is active. */
  dragmode: 'zoom' | 'lasso' | 'select' | false;
  /** Which Plotly event produces the geometry. */
  capture: CaptureEvent;
  /** Axis frozen (`fixedrange`) so a range drag only moves along the other. */
  fixedAxis: 'x' | 'y' | null;
}

/**
 * How the figure behaves for a drawing tool. Ranges are captured from a box
 * zoom (then undone), points from a lasso/box selection (then cleared), lines
 * and notes from a click (no drag gesture at all).
 */
export function annotateInteraction(
  tool: AnnotateTool,
  opts: AnnotateOptions = DEFAULT_ANNOTATE_OPTIONS,
): AnnotateInteraction {
  switch (tool) {
    case 'range':
      return {
        dragmode: 'zoom',
        capture: 'relayout',
        fixedAxis: opts.rangeAxis === 'x' ? 'y' : 'x',
      };
    case 'points':
      return { dragmode: opts.selectMode, capture: 'selected', fixedAxis: null };
    case 'line':
    case 'note':
      return { dragmode: false, capture: 'click', fixedAxis: null };
  }
}

/** One-line instruction shown under the annotate toolbar. */
export function annotateHint(tool: AnnotateTool, opts: AnnotateOptions): string {
  switch (tool) {
    case 'range':
      return opts.rangeAxis === 'x'
        ? 'Drag horizontally to highlight an x range'
        : 'Drag vertically to highlight a y range';
    case 'line':
      return opts.lineAxis === 'x'
        ? 'Click to place a vertical reference line'
        : 'Click to place a horizontal reference line';
    case 'points':
      return opts.selectMode === 'lasso' ? 'Lasso the points to mark' : 'Box-select the points to mark';
    case 'note':
      return 'Click a point to attach a note';
  }
}

/** The annotation kind a geometry belongs to. */
export function kindForGeometry(geometry: Geometry): AnnotationKind {
  switch (geometry.kind) {
    case 'x_range':
    case 'y_range':
      return 'range';
    case 'ref_line':
      return 'line';
    case 'points':
      return 'points';
    case 'arrow_note':
      return 'note';
  }
}

/** Palette name a new annotation of this kind starts with. */
export function defaultColorFor(kind: AnnotationKind): AnnotationColor {
  switch (kind) {
    case 'range':
      return 'yellow';
    case 'line':
      return 'red';
    case 'points':
      return 'orange';
    case 'note':
      return 'blue';
  }
}

export const KIND_LABELS: Record<AnnotationKind, string> = {
  range: 'Range highlight',
  line: 'Reference line',
  points: 'Marked points',
  note: 'Note',
};

/** Null when the label is acceptable, else the message to show. */
export function validateLabel(label: string): string | null {
  const t = label.trim();
  if (!t) return 'A label is required';
  if (t.length > MAX_LABEL_CHARS) return `At most ${MAX_LABEL_CHARS} characters`;
  return null;
}

/** Name of the "new items" highlight overlay FigureRenderer draws. */
export const NEW_ITEMS_TRACE_NAME = '__depictio_new_items';

/** Whether a trace is a client-side overlay rather than part of the figure. */
export function isOverlayTraceName(name: unknown): boolean {
  return (
    typeof name === 'string' &&
    (name.startsWith(OVERLAY_TRACE_PREFIX) || name === NEW_ITEMS_TRACE_NAME)
  );
}

interface EventPointLike {
  x?: unknown;
  y?: unknown;
  curveNumber?: number;
  customdata?: unknown;
  data?: { name?: unknown };
  fullData?: { name?: unknown };
}

/**
 * A per-point customdata row as a plain array. Plotly hands it over as an
 * array, a typed array, or an object with numeric keys when the trace used the
 * typed-array transport; scalars are returned unchanged.
 */
export function customdataRow(cd: unknown): unknown {
  if (cd == null || Array.isArray(cd)) return cd;
  if (ArrayBuffer.isView(cd)) return Array.from(cd as unknown as ArrayLike<unknown>);
  if (typeof cd === 'object') {
    const obj = cd as Record<string, unknown>;
    const keys = Object.keys(obj).filter((k) => /^\d+$/.test(k));
    if (!keys.length) return cd;
    const out: unknown[] = [];
    keys.forEach((k) => {
      out[Number(k)] = obj[k];
    });
    return out;
  }
  return cd;
}

/**
 * A Plotly click/selection event without the points of overlay traces
 * (annotation markers, new-item halos), with customdata rows normalised.
 * Overlays are appended after the real traces, so their points must never
 * reach a filter or a new annotation.
 */
export function stripOverlayPoints<P extends EventPointLike>(
  event: { points?: P[] } | null | undefined,
): { points: P[] } {
  const points = (event?.points ?? []).filter(
    (p) => !isOverlayTraceName(p?.data?.name ?? p?.fullData?.name),
  );
  return {
    points: points.map((p) =>
      p.customdata === undefined ? p : { ...p, customdata: customdataRow(p.customdata) },
    ),
  };
}

function asPlainArray(field: unknown): unknown[] | undefined {
  if (Array.isArray(field)) return field;
  if (isPlotlyTypedArray(field)) return decodeBdata(field);
  if (ArrayBuffer.isView(field)) return Array.from(field as unknown as ArrayLike<unknown>);
  return undefined;
}

function customdataIds(customdata: unknown, col: number): unknown[] | undefined {
  if (Array.isArray(customdata)) {
    return customdata.map((row) => {
      const r = customdataRow(row);
      if (Array.isArray(r)) return r[col];
      return col === 0 ? r : undefined;
    });
  }
  if (isPlotlyTypedArray(customdata)) return extractCustomdataIds(customdata, col);
  return undefined;
}

export interface NormalizedTrace {
  x?: unknown[];
  y?: unknown[];
  /** One selection id per point (column already picked). */
  customdata?: unknown[];
}

/**
 * The figure's traces in the shape `annotationsToPlotly` reads: plain x/y
 * arrays and one selection id per point, decoded from Plotly's typed-array
 * transport when needed. Pass `selectionColumnIndex: 0` to the conversion
 * afterwards, since the column is already picked here. Overlay traces are
 * skipped.
 */
export function normalizeTraces(data: unknown, selectionColumnIndex: number): NormalizedTrace[] {
  if (!Array.isArray(data)) return [];
  const out: NormalizedTrace[] = [];
  for (const t of data as Array<Record<string, unknown> | null>) {
    if (!t || isOverlayTraceName(t.name)) continue;
    out.push({
      x: asPlainArray(t.x),
      y: asPlainArray(t.y),
      customdata: customdataIds(t.customdata, selectionColumnIndex),
    });
  }
  return out;
}

/** Visu types drawn outside a cartesian x/y plane: no annotation there. */
const NON_CARTESIAN_VISU = new Set([
  'scatter_3d',
  'line_3d',
  'pie',
  'sunburst',
  'treemap',
  'icicle',
  'funnel_area',
  'parallel_coordinates',
  'parallel_categories',
  'scatter_polar',
  'line_polar',
  'bar_polar',
  'scatter_geo',
  'line_geo',
  'choropleth',
  'scatter_map',
  'line_map',
  'density_map',
  'choropleth_map',
  'scatter_mapbox',
  'line_mapbox',
  'density_mapbox',
  'choropleth_mapbox',
  'scatter_ternary',
  'line_ternary',
]);

/** Whether a component can carry chart annotations (a cartesian Plotly figure). */
export function supportsAnnotation(meta: {
  component_type?: string | null;
  visu_type?: unknown;
}): boolean {
  if (meta.component_type !== 'figure') return false;
  const visu = typeof meta.visu_type === 'string' ? meta.visu_type : '';
  return !NON_CARTESIAN_VISU.has(visu);
}

/** Minimal thread shape the layer reads (a subset of `CommentThread`). */
export interface ThreadLike {
  id: string;
  number?: number | null;
  status: string;
  annotation?: Annotation | null;
  anchor: { component_index?: string | null };
}

/** Statuses whose annotations are drawn on the chart. */
export const DRAWN_STATUSES = new Set(['open', 'resolved', 'proposed']);

/** An agent proposal is drawn faded and dashed until a human accepts it. */
export function proposedStyle(annotation: Annotation): AnnotationStyle {
  const style = annotation.style ?? {};
  const base =
    style.opacity ?? (annotation.kind === 'range' ? 0.15 : 1);
  return { ...style, opacity: Math.max(0.05, base * 0.5), dash: 'dot' };
}

/**
 * Threads carrying an annotation, grouped by component index and ready to
 * draw. Rejected threads and tab-level threads are left out; proposals get
 * the faded style.
 */
export function threadsToRenderable(
  threads: readonly ThreadLike[],
): Record<string, RenderableAnnotation[]> {
  const out: Record<string, RenderableAnnotation[]> = {};
  for (const t of threads) {
    const idx = t.anchor.component_index;
    if (!t.annotation || !idx || !DRAWN_STATUSES.has(t.status)) continue;
    const annotation =
      t.status === 'proposed' ? { ...t.annotation, style: proposedStyle(t.annotation) } : t.annotation;
    (out[idx] ??= []).push({ id: t.id, number: t.number ?? null, annotation, status: t.status });
  }
  return out;
}

/** Minimal published-annotation shape (a subset of `PublishedAnnotation`). */
export interface PublishedLike {
  thread_id: string;
  component_index: string | null;
  number: number | null;
  kind: AnnotationKind;
  geometry: Geometry;
  label: string;
  color: AnnotationColor;
  style: AnnotationStyle;
}

/** Published annotations (what viewers may see), grouped by component index. */
export function publishedToRenderable(
  items: readonly PublishedLike[],
): Record<string, RenderableAnnotation[]> {
  const out: Record<string, RenderableAnnotation[]> = {};
  for (const p of items) {
    if (!p.component_index) continue;
    (out[p.component_index] ??= []).push({
      id: p.thread_id,
      number: p.number,
      annotation: {
        kind: p.kind,
        geometry: p.geometry,
        label: p.label,
        color: p.color,
        style: p.style,
        published: true,
      },
    });
  }
  return out;
}

export interface AxisState {
  autorange: boolean;
  range: AxisValue[] | null;
}

/**
 * Ranges of every cartesian axis of a figure, keyed by layout name
 * (`xaxis`, `yaxis`, `xaxis2`...): faceted figures have one pair per panel.
 */
export type AxisSnapshot = Record<string, AxisState | null>;

interface FullAxisLike {
  autorange?: unknown;
  range?: unknown;
}

const AXIS_NAME = /^[xy]axis\d*$/;

function snapAxis(ax: FullAxisLike | undefined): AxisState | null {
  if (!ax || typeof ax !== 'object') return null;
  const range = Array.isArray(ax.range) && ax.range.length >= 2 ? [...ax.range] as AxisValue[] : null;
  return { autorange: ax.autorange === true || range == null, range };
}

/** Every cartesian axis' current range, read from a graph div's `_fullLayout`. */
export function snapshotAxes(fullLayout: Record<string, unknown> | null | undefined): AxisSnapshot {
  const out: AxisSnapshot = {};
  if (!fullLayout) return out;
  for (const key of Object.keys(fullLayout)) {
    if (!AXIS_NAME.test(key)) continue;
    const snap = snapAxis(fullLayout[key] as FullAxisLike | undefined);
    if (snap) out[key] = snap;
  }
  return out;
}

/** `Plotly.relayout` update putting every axis back where the snapshot was. */
export function restoreAxesUpdate(snapshot: AxisSnapshot): Record<string, unknown> {
  const update: Record<string, unknown> = {};
  for (const [name, s] of Object.entries(snapshot)) {
    if (!s) continue;
    if (s.autorange || !s.range) update[`${name}.autorange`] = true;
    else update[`${name}.range`] = [...s.range];
  }
  return update;
}

/**
 * Whether a `plotly_relayout` event set an explicit range on some axis (a box
 * zoom, a scroll zoom, an axis drag, on any panel), as opposed to an autorange
 * reset or a non-axis change.
 */
export function relayoutSetsRange(ev: Record<string, unknown> | null | undefined): boolean {
  if (!ev) return false;
  return Object.keys(ev).some((k) => /^[xy]axis\d*\.range(\[[01]\])?$/.test(k));
}

interface PixelAxisLike {
  _offset?: number;
  _length?: number;
  p2d?: (px: number) => unknown;
}

/**
 * Data coordinates under a click, from the graph div's bounding box and its
 * `_fullLayout` axes. Null outside the plot area or when the axes cannot
 * convert (non-cartesian figures).
 */
export function pixelToData(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number },
  fullLayout: { xaxis?: PixelAxisLike; yaxis?: PixelAxisLike } | null | undefined,
): { x: unknown; y: unknown } | null {
  const xa = fullLayout?.xaxis;
  const ya = fullLayout?.yaxis;
  if (!xa?.p2d || !ya?.p2d) return null;
  if (typeof xa._offset !== 'number' || typeof ya._offset !== 'number') return null;
  const px = clientX - rect.left - xa._offset;
  const py = clientY - rect.top - ya._offset;
  if (px < 0 || py < 0) return null;
  if (typeof xa._length === 'number' && px > xa._length) return null;
  if (typeof ya._length === 'number' && py > ya._length) return null;
  return { x: xa.p2d(px), y: ya.p2d(py) };
}

export interface PointMiss {
  id: string;
  number: number | null;
  found: number;
  expected: number;
}

/** Marked-points annotations with points missing from the current figure. */
export function pointMisses(
  stats: Record<string, { expected: number; found: number }>,
  items: readonly RenderableAnnotation[],
): PointMiss[] {
  const byId = new Map(items.map((i) => [i.id, i]));
  return Object.entries(stats)
    .filter(([, s]) => s.expected > 0 && s.found < s.expected)
    .map(([id, s]) => ({ id, number: byId.get(id)?.number ?? null, ...s }))
    .sort((a, b) => (a.number ?? Infinity) - (b.number ?? Infinity));
}
