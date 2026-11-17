/**
 * Geometry of the genome-wide density strip: chromosomes laid out over a
 * width, bins to pixels and back, opacity, the view marker and the row order.
 * Pure: the strip (`DensityStrip.tsx`) only paints what this computes.
 */
import type { JBrowseCallDensity, JBrowseDensityTrack } from '../../api';
import type { NamedLocusSource } from './locusSources';

export type DensityGroup = 'source' | 'sample' | 'run';

export interface DensityRegion {
  refName: string;
  length: number;
}

/** One chromosome on the strip: `width` px for `length` bp starting at `x`. */
export interface DensitySlot extends DensityRegion {
  x: number;
  width: number;
  pxPerBp: number;
}

export interface DensityLocus {
  refName: string;
  /** 1-based, like a JBrowse locus string. */
  start: number;
  end: number;
}

/** The most tracks the API returns (the busiest are kept). */
export const MAX_DENSITY_TRACKS = 64;
/** Contigs under this share of the genome get no slot. */
export const MIN_SLOT_FRACTION = 0.002;
/** Separators may take at most this share of the width. */
const MAX_SEPARATOR_SHARE = 0.1;
/** Opacity of the faintest non-zero bin (a lone region stays visible). */
export const MIN_BIN_OPACITY = 0.2;

/**
 * Lay the chromosomes out proportionally over `width`, `separator` px apart.
 * Contigs under 0.2% of the genome are DROPPED rather than collapsed into an
 * "other" slot: they would be a few px wide at best, an "other" slot has no
 * single locus to navigate to, and hiding them never moves the others. Should
 * every contig be that small (a draft assembly), all are kept; and when the
 * separators of the survivors would eat more than 10% of the width only the
 * longest contigs are kept (in assembly order).
 */
export function layoutSlots(
  regions: DensityRegion[],
  width: number,
  separator = 1,
): DensitySlot[] {
  const valid = regions.filter((r) => Number.isFinite(r.length) && r.length > 0);
  if (!valid.length || !(width > 0)) return [];
  const total = valid.reduce((sum, r) => sum + r.length, 0);
  let kept = valid.filter((r) => r.length >= total * MIN_SLOT_FRACTION);
  if (!kept.length) kept = valid;
  const maxSlots = Math.max(1, Math.floor((width * MAX_SEPARATOR_SHARE) / separator));
  if (kept.length > maxSlots) {
    const longest = new Set(
      [...kept].sort((a, b) => b.length - a.length).slice(0, maxSlots),
    );
    kept = kept.filter((r) => longest.has(r));
  }
  const keptTotal = kept.reduce((sum, r) => sum + r.length, 0);
  const usable = Math.max(1, width - separator * (kept.length - 1));
  const pxPerBp = usable / keptTotal;
  let x = 0;
  return kept.map((r) => {
    const slot = { refName: r.refName, length: r.length, x, width: r.length * pxPerBp, pxPerBp };
    x += slot.width + separator;
    return slot;
  });
}

/**
 * The regions to lay out: the assembly's when given, else rebuilt from the
 * response (bins x bin size, so up to one bin longer than the contig).
 */
export function densityRegions(
  data: JBrowseCallDensity,
  regions?: DensityRegion[] | null,
): DensityRegion[] {
  const first = data.tracks[0];
  if (regions?.length) {
    const wanted = new Set(first ? first.chroms.map((c) => c.refName) : []);
    const inData = wanted.size ? regions.filter((r) => wanted.has(r.refName)) : regions;
    return inData.length ? inData : regions;
  }
  if (!first) return [];
  return first.chroms.map((c) => ({ refName: c.refName, length: c.counts.length * data.bin_size }));
}

/** Where bin `i` of a chromosome sits: x and width in px (the last bin is clipped to the contig). */
export function binRect(slot: DensitySlot, binSize: number, i: number): { x: number; width: number } {
  const from = i * binSize;
  const to = Math.min((i + 1) * binSize, slot.length);
  return { x: slot.x + from * slot.pxPerBp, width: Math.max(0, to - from) * slot.pxPerBp };
}

export interface PixelRun {
  x0: number;
  x1: number;
  count: number;
}

/**
 * The non-empty bins of a row as whole-pixel runs. Bins narrower than a pixel
 * that land on the same one are merged (their max), so the canvas never stacks
 * alpha; a bin is at least 1 px wide.
 */
export function pixelRuns(counts: number[], slot: DensitySlot, binSize: number): PixelRun[] {
  const runs: PixelRun[] = [];
  for (let i = 0; i < counts.length; i++) {
    const count = counts[i];
    if (!(count > 0)) continue;
    const r = binRect(slot, binSize, i);
    const x0 = Math.round(r.x);
    const x1 = Math.max(x0 + 1, Math.round(r.x + r.width));
    const last = runs[runs.length - 1];
    if (last && last.x0 === x0) {
      last.count = Math.max(last.count, count);
      last.x1 = Math.max(last.x1, x1);
    } else {
      runs.push({ x0, x1, count });
    }
  }
  return runs;
}

/** The slot under `x`, null in a separator or off the strip. */
export function slotAt(slots: DensitySlot[], x: number): DensitySlot | null {
  return slots.find((s) => x >= s.x && x <= s.x + s.width) ?? null;
}

export interface DensityHit extends DensityLocus {
  slot: DensitySlot;
  bin: number;
}

/** The bin under `x`, with the 1-based locus it spans; null off every slot. */
export function binAt(slots: DensitySlot[], x: number, binSize: number): DensityHit | null {
  const slot = slotAt(slots, x);
  if (!slot) return null;
  if (!(binSize > 0)) return { slot, bin: 0, refName: slot.refName, start: 1, end: slot.length };
  const bins = Math.max(1, Math.ceil(slot.length / binSize));
  const bin = Math.min(bins - 1, Math.max(0, Math.floor((x - slot.x) / (binSize * slot.pxPerBp))));
  return {
    slot,
    bin,
    refName: slot.refName,
    start: bin * binSize + 1,
    end: Math.min((bin + 1) * binSize, slot.length),
  };
}

/** The whole chromosome of a slot. */
export function chromLocus(slot: DensitySlot): DensityLocus {
  return { refName: slot.refName, start: 1, end: slot.length };
}

/** `chr:start-end`, the string `navToLocString` takes. */
export function locusString(l: DensityLocus): string {
  return `${l.refName}:${l.start}-${l.end}`;
}

/**
 * Opacity of a bin: `sqrt(count / max)` so a few hot bins do not wash out the
 * rest, with a floor so every non-zero bin shows. 0 for an empty bin.
 */
export function binOpacity(count: number, max: number): number {
  if (!(count > 0) || !(max > 0)) return 0;
  const t = Math.sqrt(Math.min(count, max) / max);
  return MIN_BIN_OPACITY + (1 - MIN_BIN_OPACITY) * t;
}

/** Visible regions as on screen (JBrowse's, 0-based half-open). */
export interface VisibleRegion {
  refName: string;
  start: number;
  end: number;
}

/**
 * The x-range of the view window, one per visible region (a view across two
 * contigs gets two marks, not one spanning what is between). Regions on a
 * contig without a slot are skipped; a mark is at least 2 px wide.
 */
export function viewMarkers(
  slots: DensitySlot[],
  visible: VisibleRegion[],
): { x: number; width: number }[] {
  const out: { x: number; width: number }[] = [];
  for (const v of visible) {
    const slot = slots.find((s) => s.refName === v.refName);
    if (!slot) continue;
    const start = Math.max(0, v.start);
    const end = Math.min(slot.length, v.end);
    if (!(end > start)) continue;
    const width = Math.max(2, (end - start) * slot.pxPerBp);
    out.push({ x: slot.x + start * slot.pxPerBp, width });
  }
  return out;
}

/** The chromosome name that fits a slot (`chr` dropped when that helps), null when none does. */
export function chromLabel(slot: DensitySlot, charPx = 6): string | null {
  const fits = (s: string) => s.length * charPx + 4 <= slot.width;
  if (fits(slot.refName)) return slot.refName;
  const bare = slot.refName.replace(/^chr/i, '');
  return bare && fits(bare) ? bare : null;
}

export interface DensityRow {
  track: JBrowseDensityTrack;
  /** A run boundary sits right above this row. */
  separatorBefore: boolean;
}

/**
 * Rows in drawing order: tracks of one run next to each other (runs in
 * first-seen order, runless tracks in a group of their own), a separator at
 * each change. With no run anywhere the order is the API's and there is none.
 */
export function densityRows(tracks: JBrowseDensityTrack[]): DensityRow[] {
  const order: string[] = [];
  const groups = new Map<string, JBrowseDensityTrack[]>();
  for (const t of tracks) {
    const key = t.run ? t.run : '';
    if (!groups.has(key)) {
      groups.set(key, []);
      order.push(key);
    }
    groups.get(key)!.push(t);
  }
  const rows: DensityRow[] = [];
  order.forEach((key, g) => {
    groups.get(key)!.forEach((track, i) => rows.push({ track, separatorBefore: g > 0 && i === 0 }));
  });
  return rows;
}

/** Row height in px: one row is a comfortable 14, many shrink to keep the strip near 64 px tall. */
export function rowHeightFor(n: number): number {
  if (n <= 1) return 14;
  const h = Math.min(10, Math.max(3, 48 / n));
  return n * h > 64 ? Math.max(1, Math.floor(64 / n)) : h;
}

/** Top of each row and the total height, with `gap` px at every run separator. */
export function rowTops(
  rows: DensityRow[],
  rowHeight: number,
  gap = 1,
): { tops: number[]; height: number } {
  let y = 0;
  const tops = rows.map((r) => {
    if (r.separatorBefore) y += gap;
    const top = y;
    y += rowHeight;
    return top;
  });
  return { tops, height: y };
}

/** Which groupings are worth offering: `sample` / `run` only when a source has the column. */
export function availableGroups(sources: NamedLocusSource[]): DensityGroup[] {
  const groups: DensityGroup[] = ['source'];
  if (sources.some((s) => s.sample_column)) groups.push('sample');
  if (sources.some((s) => s.run_column)) groups.push('run');
  return groups;
}

/**
 * The grouping to open with: `sample` when every enabled source has a
 * `sample_column` and the rows stay within the cap (`trackCount`, when
 * known), else `source`.
 */
export function defaultDensityGroup(
  enabledSources: NamedLocusSource[],
  trackCount?: number | null,
): DensityGroup {
  if (!enabledSources.length) return 'source';
  if (!enabledSources.every((s) => s.sample_column)) return 'source';
  if (trackCount != null && trackCount > MAX_DENSITY_TRACKS) return 'source';
  return 'sample';
}

/** Bins to request for a strip `width` px wide: whole 200s, so a resize does not refetch on every px. */
export function binsBucket(bins: number): number {
  const clamped = Math.min(2000, Math.max(200, Number.isFinite(bins) ? bins : 200));
  return Math.min(2000, Math.ceil(clamped / 200) * 200);
}
