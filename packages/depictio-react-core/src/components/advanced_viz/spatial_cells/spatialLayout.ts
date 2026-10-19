/**
 * The arithmetic behind `SpatialCellsRenderer`, kept out of React so it can be
 * tested without a DOM: which columns are markers, how a marker becomes a
 * colour (transform, percentile clip), where the cells and the image sit in
 * the coordinate frame (y down for an image, y up for a plot), how big a cell
 * is on screen at the current zoom, and how a table too large to draw is
 * thinned.
 *
 * Mirrors `SpatialCellsConfig` in
 * depictio/models/components/advanced_viz/configs.py.
 */

export type SpatialYAxis = 'image' | 'cartesian';
export type SpatialTransform = 'none' | 'asinh' | 'log1p';

/** Polars dtype names a marker column may carry. */
const NUMERIC_DTYPE = /^(U?Int(8|16|32|64)|Float(32|64)|Decimal)/;

export function isNumericDtype(dtype: unknown): boolean {
  return typeof dtype === 'string' && NUMERIC_DTYPE.test(dtype);
}

export interface MarkerColumnsInput {
  /** `{column: polars dtype}` of the bound collection, in table order; null
   *  while it loads. Needed only for a pattern. */
  schema: Record<string, string> | null;
  valueColumns?: readonly string[] | null;
  pattern?: string | null;
  valueCol?: string | null;
  /** Bound columns that are never markers (id, x, y, area, sample...). */
  exclude?: readonly (string | null | undefined)[];
}

/**
 * The marker columns the colour picker offers, in order, without duplicates.
 *
 * An explicit list wins; otherwise the numeric columns the pattern matches (an
 * invalid pattern matches nothing rather than throwing: the model validates
 * it, but `stored_metadata` reaches the client unvalidated); otherwise the
 * bound `value_col` alone. `value_col` is always offered, first when it is
 * not in the list, so the marker a dashboard opens on is one the picker shows.
 */
export function resolveMarkerColumns(input: MarkerColumnsInput): string[] {
  const exclude = new Set((input.exclude ?? []).filter((c): c is string => Boolean(c)));
  let out: string[] = [];
  if (input.valueColumns && input.valueColumns.length > 0) {
    out = input.valueColumns.filter((c) => typeof c === 'string' && c.length > 0);
  } else if (input.pattern) {
    let re: RegExp | null = null;
    try {
      re = new RegExp(input.pattern);
    } catch {
      re = null;
    }
    if (re && input.schema) {
      out = Object.entries(input.schema)
        .filter(([name, dtype]) => !exclude.has(name) && isNumericDtype(dtype) && re!.test(name))
        .map(([name]) => name);
    }
  }
  const valueCol = input.valueCol || null;
  if (valueCol && !out.includes(valueCol)) out = [valueCol, ...out];
  return Array.from(new Set(out));
}

/** The marker drawn: the picked one when it is still offered, else the first. */
export function pickMarker(markers: readonly string[], picked: string | null | undefined): string | null {
  if (picked && markers.includes(picked)) return picked;
  return markers[0] ?? null;
}

export function toNumber(v: unknown): number | null {
  if (v === null || v === undefined || v === '' || typeof v === 'boolean') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** One value through the colour transform. `asinh(x / cofactor)` is the
 *  cytometry convention: linear near zero, logarithmic in the bright tail. */
export function transformValue(v: number, transform: SpatialTransform, cofactor = 150): number {
  if (transform === 'asinh') return Math.asinh(v / (cofactor > 0 ? cofactor : 1));
  if (transform === 'log1p') return v > -1 ? Math.log1p(v) : Number.NaN;
  return v;
}

/** The `p`-th percentile (0 to 100) of an ascending array, linear between ranks. */
export function percentile(sorted: readonly number[], p: number): number {
  if (sorted.length === 0) return Number.NaN;
  const clamped = Math.min(100, Math.max(0, p));
  const rank = (clamped / 100) * (sorted.length - 1);
  const lo = Math.floor(rank);
  const hi = Math.ceil(rank);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (rank - lo);
}

/**
 * The colour range after clipping to `[lowPct, highPct]` percentiles of the
 * finite values, which is what stops one saturated cell (a bright debris
 * object, an edge artefact) from flattening the rest of the tissue into the
 * bottom colour. A range that collapses to one value is widened by one unit
 * either side, so the scale still has a span to map. Null without values.
 */
export function clipRange(
  values: readonly (number | null)[],
  lowPct: number,
  highPct: number,
): { min: number; max: number } | null {
  const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (finite.length === 0) return null;
  finite.sort((a, b) => a - b);
  let min = percentile(finite, lowPct);
  let max = percentile(finite, highPct);
  if (!(max > min)) {
    min -= 1;
    max += 1;
  }
  return { min, max };
}

/** A rectangle of the coordinate frame, in data units, `x0 <= x1`, `y0 <= y1`. */
export interface Frame {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

/** The bounding box of the cells, or null when no cell has both coordinates. */
export function cellExtent(xs: readonly (number | null)[], ys: readonly (number | null)[]): Frame | null {
  let x0 = Infinity;
  let x1 = -Infinity;
  let y0 = Infinity;
  let y1 = -Infinity;
  const n = Math.min(xs.length, ys.length);
  for (let i = 0; i < n; i += 1) {
    const x = xs[i];
    const y = ys[i];
    if (x === null || y === null || !Number.isFinite(x) || !Number.isFinite(y)) continue;
    if (x < x0) x0 = x;
    if (x > x1) x1 = x;
    if (y < y0) y0 = y;
    if (y > y1) y1 = y;
  }
  return Number.isFinite(x0) ? { x0, x1, y0, y1 } : null;
}

/** The frame an image covers: pixel (0, 0) at the origin, `scale` coordinate
 *  units per pixel. */
export function imageFrame(width: number, height: number, scale = 1): Frame {
  return { x0: 0, x1: width * scale, y0: 0, y1: height * scale };
}

export function unionFrame(a: Frame | null, b: Frame | null): Frame | null {
  if (!a) return b;
  if (!b) return a;
  return {
    x0: Math.min(a.x0, b.x0),
    x1: Math.max(a.x1, b.x1),
    y0: Math.min(a.y0, b.y0),
    y1: Math.max(a.y1, b.y1),
  };
}

/** `frame` grown by `fraction` of its larger side on every edge, so the
 *  outermost cells are not cut in half by the axis. A degenerate frame (one
 *  cell) gets one unit. */
export function padFrame(frame: Frame, fraction = 0.02): Frame {
  const span = Math.max(frame.x1 - frame.x0, frame.y1 - frame.y0);
  const pad = span > 0 ? span * fraction : 1;
  return { x0: frame.x0 - pad, x1: frame.x1 + pad, y0: frame.y0 - pad, y1: frame.y1 + pad };
}

/**
 * Plotly axis ranges for a frame. In `image` mode y runs downwards, which
 * Plotly draws when the y range is given high-to-low; that, and not
 * `autorange: 'reversed'`, is what keeps a fixed frame (an autorange would
 * drop the image margin the moment a filter removed the edge cells).
 */
export function axisRanges(
  frame: Frame,
  yAxis: SpatialYAxis,
): { x: [number, number]; y: [number, number] } {
  return {
    x: [frame.x0, frame.x1],
    y: yAxis === 'image' ? [frame.y1, frame.y0] : [frame.y0, frame.y1],
  };
}

export interface UnderlaySpec {
  source: string;
  width: number;
  height: number;
  scale?: number;
  yAxis: SpatialYAxis;
  opacity?: number;
  /** Axis ids the image is placed on (`x`, `y`; `x2`, `y2` for a facet). */
  xref?: string;
  yref?: string;
}

/**
 * The `layout.images` entry that lays an image of `width x height` pixels on
 * the coordinate frame. Plotly places an image by its anchor corner in pixel
 * space and draws it right and down from there, so the top-left corner is
 * anchored: at y = 0 on a downward (image) axis, where pixel row 0 is, and at
 * y = height on an upward one, where the image's top row then sits.
 */
export function underlayImage(spec: UnderlaySpec): Record<string, unknown> {
  const scale = spec.scale && spec.scale > 0 ? spec.scale : 1;
  const w = spec.width * scale;
  const h = spec.height * scale;
  return {
    source: spec.source,
    xref: spec.xref ?? 'x',
    yref: spec.yref ?? 'y',
    x: 0,
    y: spec.yAxis === 'image' ? 0 : h,
    sizex: w,
    sizey: h,
    xanchor: 'left',
    yanchor: 'top',
    sizing: 'stretch',
    layer: 'below',
    opacity: spec.opacity ?? 0.7,
  };
}

/**
 * Screen pixels per coordinate unit for a frame drawn into a plot area of
 * `widthPx x heightPx` at equal aspect: the tighter of the two, because a
 * `scaleanchor` axis shrinks its domain to keep the ratio.
 */
export function pixelsPerUnit(frame: Frame, widthPx: number, heightPx: number): number {
  const xs = frame.x1 - frame.x0;
  const ys = frame.y1 - frame.y0;
  const candidates: number[] = [];
  if (xs > 0 && widthPx > 0) candidates.push(widthPx / xs);
  if (ys > 0 && heightPx > 0) candidates.push(heightPx / ys);
  return candidates.length ? Math.min(...candidates) : 0;
}

/**
 * Marker diameters in px for cells of the given areas: the diameter of the
 * disc of that area, `2 * sqrt(area / pi)`, at `pxPerUnit`, clamped to
 * `[floor, ceil]`. A cell with no area takes the floor, so it stays visible.
 * This is what makes a zoomed-in tile read as cells rather than as a scatter:
 * the markers grow with the zoom, as the cells would.
 */
export function cellDiameters(
  areas: readonly (number | null)[],
  pxPerUnit: number,
  floor: number,
  ceil: number,
): number[] {
  const lo = Math.max(0.5, floor);
  const hi = Math.max(lo, ceil);
  return areas.map((a) => {
    if (a === null || !(a > 0) || !(pxPerUnit > 0)) return lo;
    const d = 2 * Math.sqrt(a / Math.PI) * pxPerUnit;
    return Math.min(hi, Math.max(lo, d));
  });
}

/**
 * At most `cap` row positions out of `n`, evenly spaced and always including
 * the first. A stride rather than a random draw: the same table thins to the
 * same cells on every render, so a lasso still finds what it drew. Returns
 * null when nothing has to go.
 */
export function thinIndices(n: number, cap: number): number[] | null {
  if (n <= 0 || cap <= 0 || n <= cap) return null;
  const out: number[] = [];
  for (let i = 0; i < cap; i += 1) out.push(Math.floor((i * n) / cap));
  return out;
}

/** Row positions per sample, samples in natural order (`S2` before `S10`). A
 *  row without a sample value is filed under the empty string. */
export function groupRowsBySample(samples: readonly unknown[] | null, n: number): Map<string, number[]> {
  const groups = new Map<string, number[]>();
  for (let i = 0; i < n; i += 1) {
    const key = samples ? String(samples[i] ?? '') : '';
    const bucket = groups.get(key);
    if (bucket) bucket.push(i);
    else groups.set(key, [i]);
  }
  const names = Array.from(groups.keys()).sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }),
  );
  return new Map(names.map((name) => [name, groups.get(name) as number[]]));
}

/** The sample `select` mode opens on: the configured one when present, else
 *  the first. */
export function pickSample(samples: readonly string[], wanted: string | null | undefined): string | null {
  if (wanted && samples.includes(wanted)) return wanted;
  return samples[0] ?? null;
}

/** `n` side-by-side x domains in paper units with `gap` between them. */
export function facetDomains(n: number, gap = 0.04): [number, number][] {
  if (n <= 1) return [[0, 1]];
  const width = (1 - gap * (n - 1)) / n;
  return Array.from({ length: n }, (_, i) => {
    const start = i * (width + gap);
    return [start, Math.min(1, start + width)] as [number, number];
  });
}

/**
 * The plot height in px at which `frames`, laid side by side across
 * `innerWidthPx` (facet domains as `facetDomains` cuts them), fill their width
 * at equal aspect: the tallest facet's width times its height-to-width ratio.
 * This is the tile's content demand: below it the image is letterboxed by
 * empty bands either side, above it by bands top and bottom. 0 when unknown.
 */
export function heightForFrames(frames: readonly Frame[], innerWidthPx: number, gap = 0.04): number {
  if (frames.length === 0 || !(innerWidthPx > 0)) return 0;
  const domains = facetDomains(frames.length, gap);
  let tallest = 0;
  frames.forEach((f, i) => {
    const xs = f.x1 - f.x0;
    const ys = f.y1 - f.y0;
    if (!(xs > 0) || !(ys > 0)) return;
    const width = innerWidthPx * (domains[i][1] - domains[i][0]);
    tallest = Math.max(tallest, (width * ys) / xs);
  });
  return tallest;
}

/** `{sample}` in a URL template replaced by the (URL-encoded) sample. */
export function fillUrlTemplate(template: string, sample: string | null): string {
  return template.split('{sample}').join(encodeURIComponent(sample ?? ''));
}

/**
 * The serve URL of an Image DC row, mirroring `buildImageUrl` in
 * ImageRenderer.tsx: the DC's `s3_base_folder` joined to the row's relative
 * path (minus a leading copy of the folder's last segment), served by the
 * public `/files/serve/image` endpoint, which Plotly's `<image>` element can
 * load without an auth header.
 */
export function imageServeUrl(s3BaseFolder: string, relativePath: string): string {
  // Already a URL (an http preview, a data URI), or nothing to join it to.
  if (/^(https?:|data:)/.test(relativePath) || !s3BaseFolder) return relativePath;
  const base = s3BaseFolder.replace(/\/+$/, '');
  const lastSegment = base.split('/').pop() || '';
  let rel = relativePath.replace(/^\/+/, '');
  if (lastSegment && rel.startsWith(`${lastSegment}/`)) rel = rel.slice(lastSegment.length + 1);
  return `/depictio/api/v1/files/serve/image?s3_path=${encodeURIComponent(`${base}/${rel}`)}`;
}

/** A number for a hover line: integers as they are, others to 4 significant
 *  digits. */
export function formatHoverNumber(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return 'NA';
  if (Number.isInteger(v)) return String(v);
  return Number(v.toPrecision(4)).toString();
}
