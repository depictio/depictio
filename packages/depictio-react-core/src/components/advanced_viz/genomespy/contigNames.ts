/**
 * Rows name their contigs the way the pipeline's reference did (`20` on an
 * Ensembl build), the built-in assembly the way UCSC does (`chr20`). GenomeSpy
 * places a row by an exact name, so an unmatched one fell to the start of the
 * genome, and a contig the assembly lacks (`KI270711.1`) made it refuse the
 * whole dataset. Each row's contig is renamed to the assembly's spelling, with
 * the tolerance the other genome tiles use (`matchChromosome`); a row on a
 * contig the assembly does not have is left out.
 */
import { matchChromosome } from '../crossTileCursor';

export function renameToContigs(
  rows: Record<string, unknown>[],
  chrCol: string,
  contigNames: readonly string[] | null,
): Record<string, unknown>[] {
  if (!contigNames?.length) return rows;
  const known = new Set(contigNames);
  const spelled = new Map<string, string | null>();
  let changed = false;
  const out: Record<string, unknown>[] = [];
  for (const row of rows) {
    const name = String(row[chrCol]);
    if (known.has(name)) {
      out.push(row);
      continue;
    }
    if (!spelled.has(name)) spelled.set(name, matchChromosome(name, contigNames));
    const match = spelled.get(name);
    changed = true;
    if (match) out.push({ ...row, [chrCol]: match });
  }
  return changed ? out : rows;
}
