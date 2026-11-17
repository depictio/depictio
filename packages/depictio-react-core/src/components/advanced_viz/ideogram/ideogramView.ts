/**
 * Pure logic behind the canvas ideogram: level of detail, binning, the detail
 * view's window (zoom and pan), its geometry, and hit-testing.
 *
 * The interaction model follows a karyotype browser (overview of every
 * chromosome, click one to open it horizontally, zoom and pan along it): marks
 * while few features are in view, density bins above a threshold, the bins
 * coloured by their dominant category or by a value scale. None of it touches
 * the DOM, so vitest covers every number (`ideogramView.test.ts`); the canvas
 * painter (`ideogramPaint.ts`) only turns these results into pixels.
 *
 * Positions are base pairs throughout; a `Window` is the `[start, end)` span
 * of one chromosome the detail view shows.
 */

import { formatBp, normaliseChrom, type BarGeom, type IdeogramFeature, type PanelGeom, type Rect } from './ideogramLayout';

// ---------------------------------------------------------------------------
// Level of detail
// ---------------------------------------------------------------------------

/** What the reader asked for: `auto` decides by how many features are in view. */
export type RenderMode = 'auto' | 'marks' | 'density';
/** What is actually drawn. */
export type DrawnAs = 'marks' | 'density';

export interface LodOptions {
  /** `auto` draws bins above this many features in view (`lod_threshold`). */
  lodThreshold: number;
  /** `marks` falls back to bins above this many (`max_features`), and says so. */
  maxFeatures: number;
}

/**
 * Marks or bins for `visible` features in view.
 *
 * `marks` keeps its long-standing meaning (marks unless the `max_features`
 * guard trips, which is reported as `guarded`); `auto` is the level-of-detail
 * switch: marks while few features are in view, bins above `lodThreshold`, so
 * a dense overview is a heat strip and zooming in brings the marks back.
 */
export function lodDecision(
  mode: RenderMode,
  visible: number,
  options: LodOptions,
): { drawn: DrawnAs; guarded: boolean } {
  if (mode === 'density') return { drawn: 'density', guarded: false };
  const guard = Math.max(1, options.maxFeatures);
  if (mode === 'marks') {
    return visible > guard ? { drawn: 'density', guarded: true } : { drawn: 'marks', guarded: false };
  }
  const threshold = Math.min(guard, Math.max(1, options.lodThreshold));
  return { drawn: visible > threshold ? 'density' : 'marks', guarded: false };
}

/** The smallest 1-2-5 step (1, 2, 5, 10, 20 ...) at least `raw`, never below 1. */
export function niceStep(raw: number): number {
  if (!(raw > 1)) return 1;
  const mag = 10 ** Math.floor(Math.log10(raw));
  for (const m of [1, 2, 5, 10]) if (m * mag >= raw - 1e-9) return m * mag;
  return 10 * mag;
}

/**
 * Bin width giving about `targetBinsPerChrom` bins on the median chromosome,
 * rounded to one significant digit and never under 1 kb. A median, not the
 * longest, so a genome of many similar chromosomes gets bins sized for them
 * rather than for one outlier.
 */
export function autoBinSizeMedian(lengths: readonly number[], targetBinsPerChrom = 50): number {
  const sizes = lengths.filter((s) => s > 0).sort((a, b) => a - b);
  if (sizes.length === 0) return 1_000_000;
  const median = sizes[Math.floor(sizes.length / 2)];
  const raw = median / Math.max(1, targetBinsPerChrom);
  if (!(raw > 0)) return 1000;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const nice = Math.max(mag, Math.round(raw / mag) * mag);
  return Math.max(1000, nice);
}

/** Bin width for `spanBp` drawn over `widthPx`: about `pxPerBin` pixels a bin. */
export function screenBinSize(spanBp: number, widthPx: number, pxPerBin = 4): number {
  if (!(widthPx > 0) || !(spanBp > 0)) return 1;
  return niceStep((spanBp / widthPx) * Math.max(1, pxPerBin));
}

// ---------------------------------------------------------------------------
// Per-chromosome index
// ---------------------------------------------------------------------------

/** The features of one chromosome sorted by start, for range queries. */
export interface ChromIndex {
  key: string;
  /** Index into the features array, sorted by start. */
  order: Int32Array;
  starts: Float64Array;
  ends: Float64Array;
  /** Longest feature, so a query also finds one that starts before the window. */
  maxLen: number;
}

/**
 * One sorted index per chromosome key (`chr` prefix and case folded). `keep`
 * drops features up front (a hidden category), so everything downstream (the
 * counts, the bins, the hit-test) agrees on what is shown.
 */
export function buildChromIndex(
  features: readonly IdeogramFeature[],
  keep?: (f: IdeogramFeature, i: number) => boolean,
): Map<string, ChromIndex> {
  const groups = new Map<string, number[]>();
  for (let i = 0; i < features.length; i += 1) {
    const f = features[i];
    if (keep && !keep(f, i)) continue;
    const key = normaliseChrom(f.chrom);
    const list = groups.get(key);
    if (list) list.push(i);
    else groups.set(key, [i]);
  }
  const out = new Map<string, ChromIndex>();
  for (const [key, list] of groups) {
    list.sort((a, b) => features[a].start - features[b].start || features[a].end - features[b].end);
    const order = Int32Array.from(list);
    const starts = new Float64Array(order.length);
    const ends = new Float64Array(order.length);
    let maxLen = 0;
    for (let k = 0; k < order.length; k += 1) {
      const f = features[order[k]];
      starts[k] = f.start;
      ends[k] = f.end;
      maxLen = Math.max(maxLen, f.end - f.start);
    }
    out.set(key, { key, order, starts, ends, maxLen });
  }
  return out;
}

/** First position in sorted `arr` whose value is >= `x`. */
export function lowerBound(arr: Float64Array, x: number): number {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (arr[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * Positions in `idx.order` of the features overlapping `[start, end]`, in
 * start order. A point feature (start == end) at either edge counts.
 */
export function overlapping(idx: ChromIndex, start: number, end: number): number[] {
  const out: number[] = [];
  const lo = lowerBound(idx.starts, start - idx.maxLen);
  for (let k = lo; k < idx.starts.length; k += 1) {
    if (idx.starts[k] > end) break;
    if (idx.ends[k] >= start) out.push(k);
  }
  return out;
}

/** How many features overlap `[start, end]` (what the level of detail counts). */
export function countOverlapping(idx: ChromIndex | undefined, start: number, end: number): number {
  if (!idx) return 0;
  let n = 0;
  const lo = lowerBound(idx.starts, start - idx.maxLen);
  for (let k = lo; k < idx.starts.length; k += 1) {
    if (idx.starts[k] > end) break;
    if (idx.ends[k] >= start) n += 1;
  }
  return n;
}

// ---------------------------------------------------------------------------
// Binning
// ---------------------------------------------------------------------------

export interface BinOptions {
  /** Span to bin, in bp; bins are aligned on multiples of `binSize`. */
  start: number;
  end: number;
  binSize: number;
  /** Category index of a feature (0..nCats-1), or -1 for none. */
  catOf?: ((f: IdeogramFeature) => number) | null;
  nCats?: number;
  /** Bin the value (mean per bin) rather than counting rows; rows without one are skipped. */
  useValue?: boolean;
  /**
   * Rows at least a bin wide are their own band rather than a share of the bin
   * at their midpoint: a table already binned (10 kb windows, one row per
   * sequence) keeps its own extents and is only merged where it is finer than
   * the screen.
   */
  keepWide?: boolean;
}

export interface BinSet {
  binSize: number;
  /** Bp of bin 0 (a multiple of `binSize`). */
  origin: number;
  count: Uint32Array;
  sum: Float64Array;
  n: Uint32Array;
  /** `count` per bin and category, `nCats` per bin, or null without categories. */
  cats: Uint32Array | null;
  nCats: number;
  /** Feature indices drawn as their own band (see `keepWide`). */
  wide: number[];
  maxCount: number;
  /** Lowest and highest bin mean (or wide-row value), when a value is binned. */
  minValue: number;
  maxValue: number;
}

/**
 * Count (or average) the features of one chromosome per bin over a span.
 *
 * A feature falls in the bin holding its midpoint, as in the long-standing
 * density bands, and per bin the categories are tallied too so the bin can
 * be drawn in its dominant one with its breakdown in the hover.
 */
export function binFeatures(
  features: readonly IdeogramFeature[],
  idx: ChromIndex | undefined,
  options: BinOptions,
): BinSet {
  const binSize = Math.max(1, Math.floor(options.binSize));
  const origin = Math.floor(Math.max(0, options.start) / binSize) * binSize;
  const nBins = Math.max(1, Math.ceil((Math.max(options.end, origin + 1) - origin) / binSize));
  const nCats = options.catOf ? Math.max(0, options.nCats ?? 0) : 0;
  const count = new Uint32Array(nBins);
  const sum = new Float64Array(nBins);
  const n = new Uint32Array(nBins);
  const cats = nCats > 0 ? new Uint32Array(nBins * nCats) : null;
  const wide: number[] = [];
  let minValue = Number.POSITIVE_INFINITY;
  let maxValue = Number.NEGATIVE_INFINITY;
  if (idx) {
    for (const k of overlapping(idx, options.start, options.end)) {
      const fi = idx.order[k];
      const f = features[fi];
      if (options.useValue && f.value === null) continue;
      if (options.keepWide && f.end - f.start >= binSize) {
        wide.push(fi);
        if (f.value !== null) {
          minValue = Math.min(minValue, f.value);
          maxValue = Math.max(maxValue, f.value);
        }
        continue;
      }
      const b = Math.floor(((f.start + f.end) / 2 - origin) / binSize);
      if (b < 0 || b >= nBins) continue;
      count[b] += 1;
      if (f.value !== null) {
        sum[b] += f.value;
        n[b] += 1;
      }
      if (cats && options.catOf) {
        const c = options.catOf(f);
        if (c >= 0 && c < nCats) cats[b * nCats + c] += 1;
      }
    }
  }
  let maxCount = 0;
  for (let b = 0; b < nBins; b += 1) {
    if (count[b] > maxCount) maxCount = count[b];
    if (options.useValue && n[b] > 0) {
      const mean = sum[b] / n[b];
      minValue = Math.min(minValue, mean);
      maxValue = Math.max(maxValue, mean);
    }
  }
  if (!Number.isFinite(minValue)) {
    minValue = 0;
    maxValue = 0;
  }
  return { binSize, origin, count, sum, n, cats, nCats, wide, maxCount, minValue, maxValue };
}

/** `[start, end)` of bin `b`. */
export function binSpan(bins: BinSet, b: number): [number, number] {
  const start = bins.origin + b * bins.binSize;
  return [start, start + bins.binSize];
}

/** Mean value of bin `b` (with `useValue`), else its count. */
export function binValue(bins: BinSet, b: number, useValue: boolean): number {
  if (useValue) return bins.n[b] > 0 ? bins.sum[b] / bins.n[b] : Number.NaN;
  return bins.count[b];
}

/** The categories of bin `b`, most frequent first (ties by index), at most `limit`. */
export function binBreakdown(bins: BinSet, b: number, limit = 5): { cat: number; count: number }[] {
  if (!bins.cats || bins.nCats === 0) return [];
  const out: { cat: number; count: number }[] = [];
  for (let c = 0; c < bins.nCats; c += 1) {
    const v = bins.cats[b * bins.nCats + c];
    if (v > 0) out.push({ cat: c, count: v });
  }
  out.sort((a, z) => z.count - a.count || a.cat - z.cat);
  return out.slice(0, Math.max(1, limit));
}

/** The dominant category of bin `b`, or -1 (no category tallied). */
export function dominantCategory(bins: BinSet, b: number): number {
  if (!bins.cats) return -1;
  let best = -1;
  let bestCount = 0;
  for (let c = 0; c < bins.nCats; c += 1) {
    const v = bins.cats[b * bins.nCats + c];
    if (v > bestCount) {
      bestCount = v;
      best = c;
    }
  }
  return best;
}

/**
 * Opacity of a bin drawn in its dominant category: a floor so a lone feature
 * still shows, rising with the count, times the reader's feature opacity.
 */
export function binAlpha(count: number, maxCount: number, opacity: number): number {
  if (!(maxCount > 0) || count <= 0) return 0;
  return (0.15 + 0.85 * Math.min(1, count / maxCount)) * Math.min(1, Math.max(0, opacity));
}

// ---------------------------------------------------------------------------
// The detail window: zoom and pan
// ---------------------------------------------------------------------------

export interface Window {
  start: number;
  end: number;
}

/** Narrowest span the detail view zooms to: 50 bp, or the whole of a shorter chromosome. */
export function minSpanFor(length: number): number {
  return Math.max(1, Math.min(length, 50));
}

/** The whole chromosome. */
export function fullWindow(length: number): Window {
  return { start: 0, end: Math.max(1, length) };
}

/** `w` kept inside `[0, length]` and at least `minSpan` wide, its centre kept where it can be. */
export function clampWindow(w: Window, length: number, minSpan = minSpanFor(length)): Window {
  const len = Math.max(1, length);
  let span = Math.min(len, Math.max(minSpan, w.end - w.start));
  if (!Number.isFinite(span)) span = len;
  let start = Number.isFinite(w.start) ? w.start : 0;
  if (w.end - w.start < span) start = (w.start + w.end) / 2 - span / 2;
  start = Math.min(Math.max(0, start), len - span);
  return { start, end: start + span };
}

/**
 * Zoom by `factor` (> 1 zooms in) about `anchor`: the position under the
 * cursor stays under the cursor, as a map zooms.
 */
export function zoomWindow(
  w: Window,
  factor: number,
  anchor: number,
  length: number,
  minSpan = minSpanFor(length),
): Window {
  const span = w.end - w.start;
  if (!(factor > 0) || !(span > 0)) return clampWindow(w, length, minSpan);
  const next = Math.min(Math.max(1, length), Math.max(minSpan, span / factor));
  const a = Math.min(w.end, Math.max(w.start, anchor));
  const start = a - ((a - w.start) * next) / span;
  return clampWindow({ start, end: start + next }, length, minSpan);
}

/** Slide the window by `delta` bp, stopping at the chromosome's ends. */
export function panWindow(w: Window, delta: number, length: number): Window {
  return clampWindow({ start: w.start + delta, end: w.end + delta }, length, 0);
}

/** The window of the same width centred on `centre`. */
export function centreWindow(w: Window, centre: number, length: number): Window {
  const span = w.end - w.start;
  return clampWindow({ start: centre - span / 2, end: centre + span / 2 }, length, 0);
}

/** How many times the window is magnified over the whole chromosome. */
export function zoomLevel(w: Window, length: number): number {
  const span = w.end - w.start;
  return span > 0 ? Math.max(1, length / span) : 1;
}

/** Pixel x of `bp` for a window drawn over `[x0, x0 + width]`. */
export function bpToX(bp: number, w: Window, x0: number, width: number): number {
  const span = w.end - w.start;
  return span > 0 ? x0 + ((bp - w.start) / span) * width : x0;
}

/** Bp under pixel `x` for a window drawn over `[x0, x0 + width]`. */
export function xToBp(x: number, w: Window, x0: number, width: number): number {
  return width > 0 ? w.start + ((x - x0) / width) * (w.end - w.start) : w.start;
}

// ---------------------------------------------------------------------------
// Detail geometry and axis
// ---------------------------------------------------------------------------

export interface DetailGeom {
  /** The whole chromosome, thin, with the window outlined on it. */
  locator: Rect;
  /** The chromosome body the window is drawn on. */
  body: Rect;
  /** Baseline of the bp axis, under the body. */
  axisY: number;
}

/** Layout of the detail view in a `width` x `height` canvas. */
export function detailLayout(width: number, height: number): DetailGeom {
  const pad = 14;
  const locatorH = 10;
  const locator = { x: pad, y: 8, w: Math.max(1, width - 2 * pad), h: locatorH };
  // Room under the locator for the lens lines and the title; the body sits
  // right below it, like a browser track, not adrift in the middle.
  const top = locator.y + locatorH + 34;
  const axisH = 30;
  const avail = Math.max(16, height - top - axisH - 6);
  const thick = Math.max(16, Math.min(96, avail * 0.7));
  const y = top;
  const body = { x: pad, y, w: Math.max(1, width - 2 * pad), h: thick };
  return { locator, body, axisY: y + thick + 4 };
}

export interface WindowTick {
  pos: number;
  x: number;
  label: string;
}

/** A bp label precise enough to tell `step`-spaced ticks apart. */
export function formatBpAt(pos: number, step: number): string {
  if (pos === 0) return '0';
  if (step >= 1e6) return formatBp(pos);
  if (step >= 1e3) {
    if (Math.abs(pos) >= 1e6) {
      const digits = Math.min(3, Math.max(1, Math.ceil(-Math.log10(step / 1e6))));
      return `${(pos / 1e6).toFixed(digits)} Mb`;
    }
    return `${(pos / 1e3).toFixed(step >= 1e4 ? 0 : 1).replace(/\.0$/, '')} kb`;
  }
  return `${Math.round(pos).toLocaleString('en-US')} bp`;
}

/** Ticks for the window over `[x0, x0 + width]`, about one per `targetPx`. */
export function windowTicks(w: Window, x0: number, width: number, targetPx = 90): WindowTick[] {
  const span = w.end - w.start;
  if (!(span > 0) || !(width > 0)) return [];
  const n = Math.max(2, Math.floor(width / Math.max(20, targetPx)));
  const step = niceStep(span / n);
  const out: WindowTick[] = [];
  for (let pos = Math.ceil(w.start / step) * step; pos <= w.end + 1e-9; pos += step) {
    out.push({ pos, x: bpToX(pos, w, x0, width), label: formatBpAt(pos, step) });
  }
  return out;
}

/** `chr1:1.2-3.4 Mb`: the window as a locus. */
export function windowLabel(chrom: string, w: Window, length: number): string {
  if (w.start <= 0 && w.end >= length) return `${chrom} · ${formatBp(length)}`;
  const step = niceStep((w.end - w.start) / 20);
  return `${chrom}:${formatBpAt(Math.round(w.start), step)}–${formatBpAt(Math.round(w.end), step)}`;
}

// ---------------------------------------------------------------------------
// Hit-testing
// ---------------------------------------------------------------------------

export interface BarHit {
  panel: number;
  bar: number;
  /** Bp under the pointer, clamped to the chromosome. */
  pos: number;
  /** On the chromosome's name rather than its body. */
  onLabel: boolean;
}

/**
 * The bar under (`x`, `y`) in the overview, with `pad` px of slack across the
 * bar (thin bars are hard to hit) and its name in the gutter as a handle.
 */
export function hitBar(panels: readonly PanelGeom[], x: number, y: number, pad = 6): BarHit | null {
  for (let pi = 0; pi < panels.length; pi += 1) {
    const p = panels[pi];
    if (x < p.x || x > p.x + p.w || y < p.y || y > p.y + p.h) continue;
    const horizontal = p.orientation === 'horizontal';
    const span = p.far - p.origin;
    let best: BarHit | null = null;
    let bestDist = Number.POSITIVE_INFINITY;
    for (let bi = 0; bi < p.bars.length; bi += 1) {
      const g: BarGeom = p.bars[bi];
      const across = horizontal ? y : x;
      const lo = horizontal ? g.y : g.x;
      const thick = horizontal ? g.h : g.w;
      if (across < lo - pad || across > lo + thick + pad) continue;
      const along = horizontal ? x : y;
      const start = horizontal ? g.x : g.y;
      const len = horizontal ? g.w : g.h;
      // Horizontal names sit in the left gutter; vertical ones under the bars.
      const onLabel = horizontal
        ? along >= p.x && along < start - pad
        : Math.abs(along - (g.labelY - 4)) <= 9;
      if (!onLabel && (along < start - pad || along > start + len + pad)) continue;
      const dist = Math.abs(across - (lo + thick / 2));
      if (dist < bestDist) {
        bestDist = dist;
        const raw = span > 0 ? ((along - p.origin) / span) * p.scaleLength : 0;
        best = {
          panel: pi,
          bar: bi,
          pos: Math.round(Math.min(g.bar.length, Math.max(0, raw))),
          onLabel,
        };
      }
    }
    if (best) return best;
  }
  return null;
}

/**
 * The feature nearest `pos` within `tol` bp: one that contains `pos` wins
 * (the narrowest, the most specific, among several), else the closest edge.
 * Returns a feature index, or -1.
 */
export function nearestFeature(
  features: readonly IdeogramFeature[],
  idx: ChromIndex | undefined,
  pos: number,
  tol: number,
): number {
  if (!idx) return -1;
  let best = -1;
  let bestDist = Number.POSITIVE_INFINITY;
  let bestWidth = Number.POSITIVE_INFINITY;
  for (const k of overlapping(idx, pos - tol, pos + tol)) {
    const fi = idx.order[k];
    const f = features[fi];
    const dist = pos < f.start ? f.start - pos : pos > f.end ? pos - f.end : 0;
    const width = f.end - f.start;
    if (dist < bestDist || (dist === bestDist && width < bestWidth)) {
      best = fi;
      bestDist = dist;
      bestWidth = width;
    }
  }
  return best;
}

export type BinHit = { kind: 'bin'; bin: number } | { kind: 'wide'; feature: number };

/**
 * What a density view shows at `pos`: a bin with features in it, or a row
 * drawn as its own band (`keepWide`). Within `tol` bp of `pos`, the nearest.
 */
export function binAt(
  bins: BinSet,
  features: readonly IdeogramFeature[],
  pos: number,
  tol = 0,
): BinHit | null {
  for (const fi of bins.wide) {
    const f = features[fi];
    if (pos >= f.start && pos <= f.end) return { kind: 'wide', feature: fi };
  }
  const b = Math.floor((pos - bins.origin) / bins.binSize);
  if (b >= 0 && b < bins.count.length && bins.count[b] > 0) return { kind: 'bin', bin: b };
  const reach = Math.ceil(Math.max(0, tol) / bins.binSize);
  for (let d = 1; d <= reach; d += 1) {
    for (const c of [b - d, b + d]) {
      if (c >= 0 && c < bins.count.length && bins.count[c] > 0) return { kind: 'bin', bin: c };
    }
  }
  return null;
}

/** A drag shorter than this many pixels is a click. */
export const DRAG_MIN_PX = 4;

/** Zoom factor of one wheel notch (`deltaY` in pixels; negative zooms in). */
export function wheelZoomFactor(deltaY: number, deltaMode = 0): number {
  const px = deltaMode === 1 ? deltaY * 16 : deltaMode === 2 ? deltaY * 400 : deltaY;
  return Math.exp(-Math.max(-600, Math.min(600, px)) * 0.002);
}
