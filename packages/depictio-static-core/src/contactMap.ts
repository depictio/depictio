/**
 * Port of `depictio/api/v1/services/contact_map.py` — the windowing half of
 * the `compute_contact_map` Celery task, which the static runtime replays over
 * the bundled Parquet (serverless RFC §13: contact_map is `compute_live`).
 *
 * Every step commutes with the dashboard filters (they are a row mask applied
 * first), so the browser draws any window the reader pans to, at any filter
 * state, with the server's own resolution pick. Parity:
 * `test/contactMap.test.ts`, whose expected values were produced by the Python
 * functions on the same inputs.
 */

import { comparePolars } from './engine/sortSlice';

/** The recipe's resolution column name (`DEFAULT_RESOLUTION_COLUMN`). */
export const DEFAULT_RESOLUTION_COLUMN = 'resolution';
export const DEFAULT_BINS_PER_PIXEL = 0.25;
export const DEFAULT_PIXELS = 800;
export const DEFAULT_MAX_CELLS = 40_000;

/** `resolve_resolution_column`: the configured column when present, else the recipe's. */
export function resolveResolutionColumn(
  available: Iterable<string>,
  configured: string | null | undefined,
): string | null {
  const cols = new Set(available);
  if (configured && cols.has(configured)) return configured;
  if (cols.has(DEFAULT_RESOLUTION_COLUMN)) return DEFAULT_RESOLUTION_COLUMN;
  return null;
}

function levelsOf(resolutions: readonly number[]): number[] {
  return [...new Set(resolutions.filter((r) => r && Math.trunc(r) > 0).map((r) => Math.trunc(r)))].sort(
    (a, b) => a - b,
  );
}

/** `choose_resolution`: closest bins-per-pixel in log space, ties to the coarser level. */
export function chooseResolution(
  resolutions: readonly number[],
  spanBp: number | null | undefined,
  pixels?: number | null,
  targetBinsPerPixel?: number | null,
): number | null {
  const levels = levelsOf(resolutions);
  if (!levels.length) return null;
  if (!spanBp || spanBp <= 0 || !Number.isFinite(spanBp)) return levels[levels.length - 1];
  const px = pixels && Math.trunc(pixels) > 0 ? Math.trunc(pixels) : DEFAULT_PIXELS;
  const target = targetBinsPerPixel && targetBinsPerPixel > 0 ? targetBinsPerPixel : DEFAULT_BINS_PER_PIXEL;
  const ideal = spanBp / (px * target);
  let best = levels[levels.length - 1];
  let bestDistance = Infinity;
  for (const level of levels) {
    const distance = Math.abs(Math.log(level / ideal));
    if (distance <= bestDistance) {
      best = level;
      bestDistance = distance;
    }
  }
  return best;
}

/** `coarsest_within_budget`: step coarser until n*(n+1)/2 cells fit `maxCells`. */
export function coarsestWithinBudget(
  resolutions: readonly number[],
  chosen: number | null,
  spanBp: number | null | undefined,
  maxCells: number = DEFAULT_MAX_CELLS,
): number | null {
  const levels = levelsOf(resolutions);
  if (!levels.length) return chosen;
  const pick = chosen ?? levels[levels.length - 1];
  if (!spanBp || spanBp <= 0 || !Number.isFinite(spanBp)) return levels[levels.length - 1];
  for (const level of levels) {
    if (level < pick) continue;
    const bins = Math.ceil(spanBp / level);
    if ((bins * (bins + 1)) / 2 <= maxCells) return level;
  }
  return levels[levels.length - 1];
}

/**
 * `window_expr` for one row: the bin overlaps `[lo, hi)`. A null operand
 * makes the Polars predicate null, which `filter` drops — `false` here.
 */
export function binOverlaps(
  start: number | null,
  end: number | null | undefined,
  hasEndCol: boolean,
  resolution: number | null,
  lo: number,
  hi: number,
): boolean {
  if (start === null) return false;
  if (!(start < hi)) return false;
  if (hasEndCol) return end !== null && end !== undefined && end > lo;
  if (resolution) return start + resolution > lo;
  return start >= lo;
}

/** `ContactMapPayload` as the renderer dispatches it (filters applied upstream). */
export interface ContactMapRequest {
  chrom1_col: string;
  start1_col: string;
  chrom2_col: string;
  start2_col: string;
  count_col: string;
  end1_col?: string | null;
  end2_col?: string | null;
  sample_col?: string | null;
  resolution_col?: string | null;
  chrom?: string | null;
  start?: number | null;
  end?: number | null;
  resolution?: number | null;
  pixels?: number | null;
  target_bins_per_pixel?: number | null;
  sample?: string | null;
  max_cells?: number | null;
}

/** The columns `compute_contact_map` projects, in its order (resolution last). */
export function contactMapProjection(req: ContactMapRequest, resolutionCol: string | null): string[] {
  return [
    req.chrom1_col,
    req.start1_col,
    req.end1_col,
    req.chrom2_col,
    req.start2_col,
    req.end2_col,
    req.count_col,
    req.sample_col,
    resolutionCol,
  ].filter((c): c is string => Boolean(c));
}

const plain = (v: unknown): unknown => (typeof v === 'bigint' ? Number(v) : v ?? null);
const num = (v: unknown): number | null => {
  const n = plain(v);
  return typeof n === 'number' && Number.isFinite(n) ? n : null;
};

/**
 * `contact_map_window` (services/contact_map.py) over column arrays: the
 * frame the server loaded is the bundled table under `mask` (the dashboard
 * filters, already resolved), restricted to `columns`' keys.
 */
export function contactMapWindow(
  columns: Record<string, ArrayLike<unknown>>,
  nRows: number,
  mask: ArrayLike<number> | null,
  req: ContactMapRequest,
  resolutionCol: string | null,
): Record<string, unknown> {
  const { chrom1_col: c1, start1_col: s1, chrom2_col: c2, start2_col: s2 } = req;
  const at = (name: string | null | undefined, i: number): unknown =>
    name && columns[name] ? plain(columns[name][i]) : null;
  const projectCols = contactMapProjection(req, resolutionCol);

  let sel: number[] = [];
  for (let i = 0; i < nRows; i++) {
    if (mask !== null && mask[i] !== 1) continue;
    if (req.sample && req.sample_col && at(req.sample_col, i) !== req.sample) continue;
    sel.push(i);
  }

  let resolutions: number[] = [];
  if (resolutionCol && sel.length) {
    const seen = new Set<number>();
    for (const i of sel) {
      const v = num(at(resolutionCol, i));
      if (v !== null && Math.trunc(v) > 0) seen.add(Math.trunc(v));
    }
    resolutions = [...seen].sort((a, b) => a - b);
  }

  const chrom = req.chrom || null;
  const start = req.start ?? null;
  const end = req.end ?? null;
  const span = start !== null && end !== null && end > start ? end - start : null;
  const maxCells = Math.trunc(req.max_cells || DEFAULT_MAX_CELLS);

  let resolution: number | null = null;
  if (resolutions.length) {
    const requested = req.resolution ? Math.trunc(req.resolution) : null;
    if (requested && resolutions.includes(requested)) {
      resolution = requested;
    } else {
      resolution = chooseResolution(resolutions, span, req.pixels, req.target_bins_per_pixel);
      resolution = coarsestWithinBudget(resolutions, resolution, span, maxCells);
    }
    sel = sel.filter((i) => num(at(resolutionCol, i)) === resolution);
  }

  if (chrom) sel = sel.filter((i) => at(c1, i) === chrom && at(c2, i) === chrom);
  if (start !== null && end !== null && Number.isFinite(start) && Number.isFinite(end) && end > start) {
    const has1 = Boolean(req.end1_col);
    const has2 = Boolean(req.end2_col);
    sel = sel.filter(
      (i) =>
        binOverlaps(num(at(s1, i)), num(at(req.end1_col, i)), has1, resolution, start, end) &&
        binOverlaps(num(at(s2, i)), num(at(req.end2_col, i)), has2, resolution, start, end),
    );
  }

  // df.sort([chrom1, start1, start2]): nulls first, stable.
  sel.sort((a, b) => {
    for (const name of [c1, s1, s2]) {
      const va = at(name, a);
      const vb = at(name, b);
      if (va === null || vb === null) {
        if (va === null && vb === null) continue;
        return va === null ? -1 : 1;
      }
      const c = comparePolars(va, vb);
      if (c !== 0) return c;
    }
    return a - b;
  });

  const truncated = sel.length > maxCells;
  if (truncated) sel = sel.slice(0, maxCells);

  const region =
    chrom && start !== null && end !== null
      ? { chrom, start, end }
      : chrom
        ? { chrom, start: null, end: null }
        : null;

  const rows: Record<string, unknown[]> = {};
  for (const name of projectCols) {
    if (name in rows) continue;
    rows[name] = sel.map((i) => at(name, i));
  }

  const distinctStrings = (name: string | null | undefined): string[] => {
    if (!name || !sel.length) return [];
    const seen = new Set<string>();
    for (const i of sel) {
      const v = at(name, i);
      if (v !== null) seen.add(String(v));
    }
    return [...seen].sort(comparePolars);
  };
  const chromosomes = distinctStrings(c1);
  const samples = req.sample_col ? distinctStrings(req.sample_col) : [];
  // Polars' n_unique counts null as one more value.
  const binCount = sel.length ? new Set(sel.map((i) => at(s1, i))).size : 0;
  const regionSpan = region && region.start !== null && region.end !== null ? region.end - region.start : null;
  const px = req.pixels && Math.trunc(req.pixels) > 0 ? Math.trunc(req.pixels) : DEFAULT_PIXELS;

  return {
    rows,
    columns: {
      chrom1: c1,
      start1: s1,
      end1: req.end1_col ?? null,
      chrom2: c2,
      start2: s2,
      end2: req.end2_col ?? null,
      count: req.count_col,
      sample: req.sample_col ?? null,
      resolution: resolutionCol,
    },
    summary: {
      row_count: sel.length,
      resolutions,
      resolution,
      resolution_col: resolutionCol,
      chromosomes,
      samples,
      n_samples: samples.length,
      bin_count: binCount,
      region,
      bins_per_pixel: regionSpan && resolution ? regionSpan / resolution / px : null,
      multi_resolution: resolutions.length > 1,
      truncated,
    },
    row_count: sel.length,
  };
}
