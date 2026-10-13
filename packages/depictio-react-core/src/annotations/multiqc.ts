/**
 * MultiQC glue for the annotation layer: which view of a MultiQC component an
 * annotation belongs to, and which sample each drawn point shows. MultiQC
 * figures carry no selection column; every trace is per sample (a line graph
 * draws one line per sample, a bar graph one bar per sample and category), so
 * the sample name is written into each point's customdata and marked points
 * are stored as sample ids. Pure, unit tested.
 */
import { decodeBdata, isPlotlyTypedArray } from '../plotlyData';
import { isOverlayTraceName } from './layer';
import { MAX_VARIANT_CHARS } from './types';

/** Column name marked MultiQC samples are stored under (`MarkedPoints.column`). */
export const MULTIQC_SAMPLE_COLUMN = 'sample';

/** Key of the sample column in the General Statistics table rows. */
export const GENERAL_STATS_SAMPLE_KEY = 'Sample Name';

export interface MultiqcVariantInput {
  module?: string | null;
  plot?: string | null;
  /** Dataset label (e.g. "Read 1", "Counts"); unset = the plot's first dataset. */
  dataset?: string | number | null;
  /** Percentages instead of counts. */
  pct?: boolean;
  /** Log scale on the value axis. */
  log?: boolean;
}

/** Short stable hash (FNV-1a, 32 bits, hex) for over-long variant keys. */
function hash(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, '0');
}

/**
 * The view a MultiQC figure shows, as the `variant` of the annotations drawn
 * on it: module, plot and dataset, plus the `pct` / `log` switches when on.
 * An annotation drawn on "Read 1" is then left out of "Read 2". Keys longer
 * than MAX_VARIANT_CHARS keep their start and end in a hash.
 */
export function multiqcVariantKey({ module, plot, dataset, pct, log }: MultiqcVariantInput): string {
  const parts = [module ?? '', plot ?? '', dataset == null ? '' : String(dataset)];
  let key = `multiqc:${parts.join('/')}`;
  if (pct) key += '|pct';
  if (log) key += '|log';
  if (key.length <= MAX_VARIANT_CHARS) return key;
  const digest = hash(key);
  return `${key.slice(0, MAX_VARIANT_CHARS - digest.length - 1)}#${digest}`;
}

function arrayOf(field: unknown): unknown[] | null {
  if (Array.isArray(field)) return field;
  if (isPlotlyTypedArray(field)) return decodeBdata(field);
  if (ArrayBuffer.isView(field)) return Array.from(field as unknown as ArrayLike<unknown>);
  return null;
}

const isId = (v: unknown): v is string | number =>
  (typeof v === 'string' && v !== '') || (typeof v === 'number' && Number.isFinite(v));

/** Trace types drawn one per sample: every point of the trace is that sample. */
const PER_SAMPLE_TYPES = new Set(['scatter', 'scattergl', 'box', 'violin']);

/**
 * The sample each point of a MultiQC trace shows, or null when the trace does
 * not map to samples (heatmaps, hidden traces, no points). Bars: the value on
 * the category axis (`y` for horizontal bars). Lines, scatter and box traces:
 * the trace name.
 */
export function sampleIdsForTrace(trace: Record<string, unknown> | null | undefined): unknown[] | null {
  if (!trace || typeof trace !== 'object') return null;
  // A trace hidden by a sample filter is not drawn: its sample is not "found".
  if (trace.visible === false) return null;
  const type = typeof trace.type === 'string' ? trace.type : 'scatter';
  if (type === 'bar') {
    const categories = arrayOf(trace.orientation === 'h' ? trace.y : trace.x);
    return categories?.length ? categories.map((v) => (isId(v) ? v : null)) : null;
  }
  if (!PER_SAMPLE_TYPES.has(type) || !isId(trace.name)) return null;
  const n = Math.max(arrayOf(trace.x)?.length ?? 0, arrayOf(trace.y)?.length ?? 0);
  return n > 0 ? new Array(n).fill(trace.name) : null;
}

/**
 * The figure's traces with each point's sample in its customdata, so marked
 * points are captured and matched as sample ids. Traces that already carry
 * customdata, or do not map to samples, are left as they are. Returns `data`
 * itself when nothing changed.
 */
export function withSampleCustomdata(data: readonly unknown[]): unknown[] {
  let changed = false;
  const out = data.map((raw) => {
    const t = raw as Record<string, unknown> | null;
    if (!t || typeof t !== 'object' || t.customdata != null || isOverlayTraceName(t.name)) return raw;
    const ids = sampleIdsForTrace(t);
    if (!ids) return raw;
    changed = true;
    return { ...t, customdata: ids };
  });
  return changed ? out : (data as unknown[]);
}

const CARTESIAN_TYPES = new Set(['scatter', 'scattergl', 'bar', 'box', 'violin', 'heatmap', 'histogram']);

/**
 * Whether a MultiQC figure can take annotations: every trace a cartesian one
 * on the main x/y axes. Multi-panel figures (e.g. the violin plots of a
 * table, one axis per metric) cannot: a shape has a single pair of axes.
 */
export function multiqcFigureAnnotatable(data: readonly unknown[] | null | undefined): boolean {
  if (!data?.length) return false;
  return data.every((raw) => {
    const t = raw as Record<string, unknown> | null;
    if (!t || typeof t !== 'object') return false;
    const type = typeof t.type === 'string' ? t.type : 'scatter';
    if (!CARTESIAN_TYPES.has(type)) return false;
    return (t.xaxis == null || t.xaxis === 'x') && (t.yaxis == null || t.yaxis === 'y');
  });
}
