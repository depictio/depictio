/**
 * Locus text -> region, the way every genome browser's address bar reads it.
 *
 * Pure so the grammar can be tested without a DOM; `LocusInput.tsx` is the
 * Mantine control around it.
 *
 * Accepted:
 *   chr7:55,000,000-56,000,000   commas, spaces and underscores are ignored
 *   chr7:55000000-56000000       plain digits
 *   chr7:55.0Mb-56Mb             k / kb / m / mb / g / gb suffixes
 *   chr7:55000000..56000000      the Ensembl separator
 *   chr7:55000000                one coordinate, opening a window around it
 *   chr7                         the whole contig
 *   TP53                         a gene symbol, resolved against the gene asset
 *
 * The contig name is matched against the names the data actually carries, with
 * or without the `chr` prefix and without regard to case, because a GRCh38 run
 * writes `7` as often as `chr7` and a reader should not have to know which.
 */

import type { GeneRow } from './genomeSpySpec';

/** A single coordinate is not a window, so it opens one: 10 kb, about a gene. */
export const POINT_WINDOW_BP = 10_000;

/** Padding around a gene's span, as a fraction of its length, so the flanks
 *  and the neighbouring exons stay visible. */
export const GENE_PAD_FRACTION = 0.1;

export interface ParsedLocus {
  /** As typed, before it is matched against the contigs actually present. */
  chrom: string;
  /** `null` when the text named a contig and no interval. */
  start: number | null;
  end: number | null;
}

const UNIT_SCALE: Record<string, number> = {
  '': 1,
  k: 1e3,
  kb: 1e3,
  m: 1e6,
  mb: 1e6,
  g: 1e9,
  gb: 1e9,
};

/** One coordinate with an optional unit, or `null` when it is not a number. */
export function parseCoordinate(raw: string): number | null {
  const cleaned = raw.replace(/[,_\s]/g, '');
  const m = /^(\d+(?:\.\d+)?)(kb|mb|gb|k|m|g)?$/i.exec(cleaned);
  if (!m) return null;
  const scale = UNIT_SCALE[(m[2] ?? '').toLowerCase()];
  if (scale === undefined) return null;
  const value = Number(m[1]) * scale;
  return Number.isFinite(value) ? Math.round(value) : null;
}

/**
 * `chr:start-end`, `chr:pos` or `chr`, or `null` when the text is not a locus
 * at all (a gene symbol, most often, which the caller resolves instead).
 */
export function parseLocusText(text: string): ParsedLocus | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const colon = trimmed.lastIndexOf(':');
  if (colon < 0) {
    // A bare word is a contig only if it looks like one. Anything else is a
    // gene symbol as far as this parser is concerned.
    return /^[A-Za-z0-9._-]+$/.test(trimmed) ? { chrom: trimmed, start: null, end: null } : null;
  }
  const chrom = trimmed.slice(0, colon).trim();
  const rest = trimmed.slice(colon + 1).trim();
  if (!chrom) return null;
  if (!rest) return { chrom, start: null, end: null };

  const parts = rest.split(/\.\.|-|–| - /).map((p) => p.trim()).filter(Boolean);
  if (parts.length === 1) {
    const pos = parseCoordinate(parts[0]);
    if (pos === null) return null;
    const half = Math.round(POINT_WINDOW_BP / 2);
    return { chrom, start: Math.max(0, pos - half), end: pos + half };
  }
  if (parts.length !== 2) return null;
  const start = parseCoordinate(parts[0]);
  const end = parseCoordinate(parts[1]);
  if (start === null || end === null) return null;
  return { chrom, start: Math.min(start, end), end: Math.max(start, end) };
}

/** Normalise a contig name for comparison: case-insensitive, `chr` optional. */
function contigKey(name: string): string {
  return name.trim().toLowerCase().replace(/^chr/, '');
}

/**
 * The name `typed` refers to among the contigs the data carries, or `null`.
 * Matching on the data's own spelling matters: a filter carrying `chr7` where
 * the column holds `7` selects nothing at all.
 */
export function resolveContig(typed: string, contigs: readonly string[]): string | null {
  if (!typed) return null;
  const exact = contigs.find((c) => c === typed);
  if (exact) return exact;
  const key = contigKey(typed);
  return contigs.find((c) => contigKey(c) === key) ?? null;
}

/** Gene symbols matching `query`, prefix matches first, capped at `limit`. */
export function findGenes(
  genes: readonly GeneRow[] | null | undefined,
  query: string,
  limit = 8,
): GeneRow[] {
  const q = query.trim().toLowerCase();
  if (!genes || !q) return [];
  const prefix: GeneRow[] = [];
  const contains: GeneRow[] = [];
  let exact = false;
  for (const gene of genes) {
    const name = gene.name.toLowerCase();
    if (name === q) {
      prefix.unshift(gene);
      exact = true;
    } else if (name.startsWith(q)) prefix.push(gene);
    else if (name.includes(q)) contains.push(gene);
    // Stop early only once the exact symbol is in hand: with `limit` 1 the
    // first prefix hit (MYCL before MYC) would otherwise end the scan.
    if (exact && prefix.length >= limit) break;
  }
  return [...prefix, ...contains].slice(0, limit);
}

/** The window a gene opens on: its span plus a tenth of it at each end. */
export function geneWindow(gene: GeneRow): { chrom: string; start: number; end: number } {
  const pad = Math.max(1, Math.round((gene.end - gene.start) * GENE_PAD_FRACTION));
  return { chrom: gene.chrom, start: Math.max(0, gene.start - pad), end: gene.end + pad };
}

/**
 * Resolve what the reader typed into a region on the data's own contig names,
 * or say why it could not be resolved. `null` chromosome ranges mean the whole
 * contig, which is what `genomeRegionFilters` draws as "no range".
 */
export function resolveLocus(
  text: string,
  contigs: readonly string[],
  genes: readonly GeneRow[] | null | undefined,
): { chrom: string; start: number | null; end: number | null; via: 'locus' | 'gene' } | null {
  const parsed = parseLocusText(text);
  if (parsed) {
    const chrom = resolveContig(parsed.chrom, contigs);
    if (chrom) return { chrom, start: parsed.start, end: parsed.end, via: 'locus' };
  }
  // Not a contig this collection holds: a gene symbol is the other thing an
  // address bar takes, and it names its own contig.
  const gene = findGenes(genes, text, 1)[0];
  if (gene) {
    const chrom = resolveContig(gene.chrom, contigs) ?? gene.chrom;
    const window = geneWindow(gene);
    return { chrom, start: window.start, end: window.end, via: 'gene' };
  }
  return null;
}

/** `chr7:55,000,000-56,000,000`, the form the input shows back. */
export function formatLocus(chrom: string, start: number | null, end: number | null): string {
  if (start === null || end === null || !Number.isFinite(start) || !Number.isFinite(end)) {
    return chrom;
  }
  const fmt = (n: number) => Math.round(n).toLocaleString('en-US');
  return `${chrom}:${fmt(start)}-${fmt(end)}`;
}
