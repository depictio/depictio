/**
 * Intermutation distances for a rainfall plot: for every variant, how far it
 * sits from the previous variant on the same chromosome.
 *
 * Pulled out of `ManhattanRenderer` so the differencing rule can be unit
 * tested without mounting Plotly, and because the rule has three edge cases
 * that are easy to get wrong in a trace builder: rows arrive in whatever order
 * the data collection stored them, the first variant of each chromosome has no
 * predecessor, and two variants at the same position have a distance of zero,
 * which has no logarithm.
 */

export interface RainfallDistance {
  /** Index into the source columns, so the caller can read its own per-row
   *  values (colour, hover, selection key) back out. */
  row: number;
  /** Distance in base pairs to the previous variant on the same chromosome. */
  distance: number;
  /** `log10(distance)`, which is what the y axis carries. */
  logDistance: number;
}

/**
 * Distances for every row that has a predecessor on its own chromosome.
 *
 * Rows are grouped by chromosome and sorted by position before differencing,
 * so the caller does not have to pre-sort. The first variant of each
 * chromosome is dropped (no predecessor), as is any row whose distance is
 * zero: two calls at the same position are a real thing in a multi-allelic
 * table, and clamping them to one base pair would invent a distance the data
 * does not carry.
 *
 * The returned list is ordered by chromosome (in first-seen order) then by
 * position, which keeps a line-drawing caller from having to sort again.
 */
export function rainfallDistances(
  chromosomes: readonly unknown[],
  positions: readonly unknown[],
): RainfallDistance[] {
  const byChromosome = new Map<string, { row: number; pos: number }[]>();
  const n = Math.min(chromosomes.length, positions.length);
  for (let i = 0; i < n; i++) {
    const pos = Number(positions[i]);
    if (!Number.isFinite(pos)) continue;
    const chr = String(chromosomes[i] ?? '');
    let bucket = byChromosome.get(chr);
    if (!bucket) {
      bucket = [];
      byChromosome.set(chr, bucket);
    }
    bucket.push({ row: i, pos });
  }

  const out: RainfallDistance[] = [];
  for (const bucket of byChromosome.values()) {
    bucket.sort((a, b) => a.pos - b.pos);
    for (let j = 1; j < bucket.length; j++) {
      const distance = bucket[j].pos - bucket[j - 1].pos;
      if (distance <= 0) continue;
      out.push({ row: bucket[j].row, distance, logDistance: Math.log10(distance) });
    }
  }
  return out;
}
