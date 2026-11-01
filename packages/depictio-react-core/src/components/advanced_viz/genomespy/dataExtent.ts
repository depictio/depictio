/**
 * `open_on_data`: where a genome-wide summary opens. Rows on one chromosome
 * open on that chromosome when they spread over most of it, else on the region
 * they cover; rows on several chromosomes keep the whole genome (null).
 */
import type { Contig } from './genomeSpySpec';

export interface DataRegion {
  chrom: string;
  start: number;
  end: number;
}

/** Share of a chromosome the rows must span to open on all of it. */
const WHOLE_CHROMOSOME_SHARE = 0.5;
/** Margin around a region, at least this many bases a side. */
const MIN_MARGIN_BP = 5000;

export function dataExtentView(
  rows: readonly Record<string, unknown>[] | null,
  cols: { chr: string; pos: string; end?: string | null },
  contigs: readonly Contig[] | null,
): DataRegion | null {
  let chrom: string | null = null;
  let lo = Infinity;
  let hi = -Infinity;
  for (const row of rows ?? []) {
    const c = row[cols.chr];
    const pos = Number(row[cols.pos]);
    if (c === null || c === undefined || c === '' || !Number.isFinite(pos)) continue;
    if (chrom === null) chrom = String(c);
    else if (chrom !== String(c)) return null;
    const end = cols.end ? Number(row[cols.end]) : NaN;
    lo = Math.min(lo, pos);
    hi = Math.max(hi, Number.isFinite(end) && end > pos ? end : pos);
  }
  if (chrom === null) return null;
  const size = contigs?.find((c) => c.name === chrom)?.size;
  const span = hi - lo;
  if (size && span >= size * WHOLE_CHROMOSOME_SHARE) return { chrom, start: 0, end: size };
  const margin = Math.max(MIN_MARGIN_BP, span * 0.1);
  return {
    chrom,
    start: Math.max(0, Math.floor(lo - margin)),
    end: Math.ceil(size ? Math.min(size, hi + margin) : hi + margin),
  };
}
