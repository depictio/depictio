/**
 * Turning a group comparison's result rows into a volcano.
 *
 * Pure on purpose: the renderer owns fetching, polling and the Mantine chrome,
 * and everything that decides *where a point lands and whether it is labelled*
 * lives here, where it can be tested without a Plotly canvas or a server.
 *
 * The axes are the two things the test produced: effect size (log2 fold change
 * of the group means, A relative to B, so positive is higher in A) against
 * significance, drawn as -log10 of the BH-adjusted p-value. Significance uses
 * the FDR rather than the raw p-value because the FDR is what the threshold
 * line means, and a reader comparing the line to a raw p would be reading a
 * different cutoff from the one the table reports.
 */

import type { GroupCompareRow } from '../../../api';

/** Smallest p the y axis will represent. A p-value that underflowed to 0 in
 *  the worker would otherwise be -log10(0) = Infinity and take the whole axis
 *  with it. 1e-300 is just inside the double range, so a genuinely extreme
 *  result still lands far above everything else rather than being flattened
 *  into the cloud. */
export const MIN_PLOTTED_P = 1e-300;

export type VolcanoTier = 'UP' | 'DN' | 'NS';

export interface VolcanoPoint {
  feature: string;
  x: number;
  y: number;
  tier: VolcanoTier;
  /** Raw p-value, for the hover; the y axis shows the adjusted one. */
  pValue: number | null;
  fdr: number | null;
  meanA: number | null;
  meanB: number | null;
}

/** -log10 of an adjusted p-value, floored so it stays finite and non-negative. */
export function negLog10(p: number | null | undefined): number {
  if (p === null || p === undefined || !Number.isFinite(p)) return 0;
  return -Math.log10(Math.max(p, MIN_PLOTTED_P));
}

/**
 * Which side of both thresholds a feature falls on.
 *
 * Both have to be passed, which is the whole point of a volcano: a tiny but
 * perfectly reproducible shift is significant and uninteresting, and a large
 * shift measured in four cells is interesting and unsupported. The server
 * already computed the same call into `row.significant`; recomputing here is
 * what lets the reader move the two threshold controls without paying for a
 * fresh job.
 */
export function tierFor(
  row: GroupCompareRow,
  fdrThreshold: number,
  log2fcThreshold: number,
): VolcanoTier {
  const fdr = row.fdr;
  const fc = row.log2fc;
  if (fdr === null || fc === null || !Number.isFinite(fdr) || !Number.isFinite(fc)) return 'NS';
  if (fdr > fdrThreshold) return 'NS';
  if (Math.abs(fc) < log2fcThreshold) return 'NS';
  return fc > 0 ? 'UP' : 'DN';
}

/** Result rows as plottable points, in the order they arrived (by p-value). */
export function volcanoPoints(
  rows: GroupCompareRow[],
  fdrThreshold: number,
  log2fcThreshold: number,
): VolcanoPoint[] {
  return rows
    .filter((r) => r.log2fc !== null && Number.isFinite(r.log2fc))
    .map((r) => ({
      feature: r.feature,
      x: r.log2fc as number,
      y: negLog10(r.fdr),
      tier: tierFor(r, fdrThreshold, log2fcThreshold),
      pValue: r.p_value,
      fdr: r.fdr,
      meanA: r.mean_a,
      meanB: r.mean_b,
    }));
}

/**
 * Indices of the points to label, at most `topN`.
 *
 * Only points that passed both thresholds are eligible: labelling the top of a
 * comparison that found nothing would put names on noise. Ranked by the
 * product of the two axes so a label is earned on both, the same rule the
 * volcano kind uses, and ties break on input order (already p-sorted) so the
 * label set is stable across renders.
 */
export function topLabelIndices(points: VolcanoPoint[], topN: number): Set<number> {
  if (topN <= 0) return new Set();
  const ranked = points
    .map((p, i) => ({ i, score: Math.abs(p.x) * p.y, tier: p.tier }))
    .filter((d) => d.tier !== 'NS' && Number.isFinite(d.score))
    .sort((a, b) => b.score - a.score || a.i - b.i);
  return new Set(ranked.slice(0, topN).map((d) => d.i));
}

/** How many features fall in each tier, in the order the frame's badges read. */
export function tierCounts(points: VolcanoPoint[]): Record<string, number> {
  const counts: Record<string, number> = { UP: 0, DN: 0, NS: 0 };
  for (const p of points) counts[p.tier] += 1;
  return counts;
}
