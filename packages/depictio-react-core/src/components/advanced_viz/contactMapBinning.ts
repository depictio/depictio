/**
 * Coarsen a sorted list of bin starts down to at most `maxBins` buckets by
 * merging runs of adjacent bins. Returns, for every original bin start, the
 * index of the coarsened bucket it falls into.
 *
 * Pulled out of `ContactMapRenderer` so it can be unit tested without
 * mounting the renderer (Plotly + react-plotly.js) just to check a binning
 * rule.
 */
export function coarsenBins(
  starts: number[],
  maxBins: number,
): { buckets: number[]; index: Map<number, number> } {
  const index = new Map<number, number>();
  if (starts.length <= maxBins) {
    starts.forEach((s, i) => index.set(s, i));
    return { buckets: starts, index };
  }
  const factor = Math.ceil(starts.length / maxBins);
  const buckets: number[] = [];
  starts.forEach((s, i) => {
    const bucket = Math.floor(i / factor);
    if (buckets.length === bucket) buckets.push(s);
    index.set(s, bucket);
  });
  return { buckets, index };
}

// ---------------------------------------------------------------------------
// Multi-resolution: which partition to read, and when to read another one
// ---------------------------------------------------------------------------

/**
 * Bins per CSS pixel aimed for when picking a resolution. Mirrors
 * `DEFAULT_BINS_PER_PIXEL` in `depictio/api/v1/services/contact_map.py`, the
 * server makes the same choice when the client sends none, and the two have to
 * agree or the badge would name a resolution the data was not read at.
 */
export const DEFAULT_BINS_PER_PIXEL = 0.25;

/** Assumed tile width when the DOM has not measured one yet. */
export const DEFAULT_PIXELS = 800;

/**
 * The available resolution whose bin size lands closest to what the visible
 * span deserves, measured in log space so halving and doubling the ideal are
 * equally wrong. Ties go to the coarser level: fewer cells for the same
 * readability.
 *
 * `null` span (no region yet) means the whole contig, whose right answer is the
 * coarsest level available.
 */
export function chooseResolution(
  resolutions: number[],
  spanBp: number | null,
  pixels: number = DEFAULT_PIXELS,
  targetBinsPerPixel: number = DEFAULT_BINS_PER_PIXEL,
): number | null {
  const levels = Array.from(new Set(resolutions.filter((r) => Number.isFinite(r) && r > 0))).sort(
    (a, b) => a - b,
  );
  if (levels.length === 0) return null;
  if (!spanBp || !Number.isFinite(spanBp) || spanBp <= 0) return levels[levels.length - 1];

  const px = pixels > 0 ? pixels : DEFAULT_PIXELS;
  const target = targetBinsPerPixel > 0 ? targetBinsPerPixel : DEFAULT_BINS_PER_PIXEL;
  const ideal = spanBp / (px * target);

  let best = levels[levels.length - 1];
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const level of levels) {
    const distance = Math.abs(Math.log(level / ideal));
    if (distance <= bestDistance) {
      best = level;
      bestDistance = distance;
    }
  }
  return best;
}

/**
 * Whether a new visible window is different enough from the loaded one to be
 * worth another round trip.
 *
 * Two reasons to go back to the server, and only two: the span changed by more
 * than `factor` (so a different resolution is probably the right one), or the
 * window moved off the edge of what is loaded (so there is nothing to draw
 * there). Panning inside the loaded window is free and must stay free, which
 * is what stops a drag from firing a request per frame.
 */
export function shouldRefetchWindow(
  loaded: { start: number; end: number } | null,
  next: { start: number; end: number } | null,
  factor = 2,
): boolean {
  if (!next || !Number.isFinite(next.start) || !Number.isFinite(next.end)) return false;
  if (!loaded) return true;
  const loadedSpan = loaded.end - loaded.start;
  const nextSpan = next.end - next.start;
  if (!(loadedSpan > 0) || !(nextSpan > 0)) return true;
  const ratio = nextSpan / loadedSpan;
  if (ratio >= factor || ratio <= 1 / factor) return true;
  return next.start < loaded.start || next.end > loaded.end;
}

/** A bin size as a reader says it: `500 kb`, `1 Mb`, `10 bp`. */
export function formatResolution(bp: number): string {
  if (!Number.isFinite(bp) || bp <= 0) return '';
  if (bp >= 1_000_000) {
    const mb = bp / 1_000_000;
    return `${Number.isInteger(mb) ? mb : mb.toFixed(1)} Mb`;
  }
  if (bp >= 1_000) {
    const kb = bp / 1_000;
    return `${Number.isInteger(kb) ? kb : kb.toFixed(1)} kb`;
  }
  return `${bp} bp`;
}
