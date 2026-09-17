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
