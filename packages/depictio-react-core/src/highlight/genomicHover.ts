/**
 * Pure helpers for the tiles that follow a hover from the highlight bus by
 * *what* is hovered rather than by a residue position: a genome browser's
 * feature (`event.genomic`) or a table row (`event.record`).
 *
 * Nothing here touches React, the DOM or Plotly. A renderer hands in the bus
 * event and the columns it binds, and gets back a yes/no (a table row), a
 * genomic interval (a plot) or the index of the point to ring.
 */
import { matchChromosome } from '../components/advanced_viz/crossTileCursor';
import type { HighlightEvent } from './bus';

export type GenomicInterval = NonNullable<HighlightEvent['genomic']>;

/** Column names that hold a contig, whatever the schema calls them. */
const CONTIG_COLUMN = /^(chr|chrom|chromosome|contig|seqname|seqid|refname|reference)$/i;

export function isContigColumn(name: string): boolean {
  return CONTIG_COLUMN.test(name);
}

/** The same contig under another spelling ("chr8", "Chr8" and "8" are one);
 *  `aliases` are the other names `a` is known by. */
export function sameContig(
  a: string | null | undefined,
  b: string | null | undefined,
  aliases?: readonly string[],
): boolean {
  if (!a || !b) return false;
  return matchChromosome(String(a), [String(b)], aliases) !== null;
}

const isBlank = (v: unknown): boolean => v === null || v === undefined || v === '';

/** Equal as a reader would say: `100` and `"100"` are the same value, `"A"` and
 *  `"a"` are not. Empty values (null, undefined, `''`) equal nothing. */
export function valuesEqual(a: unknown, b: unknown): boolean {
  if (isBlank(a) || isBlank(b)) return false;
  if (a === b) return true;
  if (typeof a === 'number' || typeof b === 'number') {
    const na = typeof a === 'number' ? a : Number(String(a).trim());
    const nb = typeof b === 'number' ? b : Number(String(b).trim());
    return Number.isFinite(na) && Number.isFinite(nb) && na === nb;
  }
  return String(a) === String(b);
}

/**
 * Whether a hovered `record` points at `row`: every column both carry (and
 * that `columns`, when given, allows) holds the same value. A column the
 * record leaves empty does not count, and no shared column at all is no match,
 * so a table with none of the record's columns ignores it. Contig columns also
 * match across spellings (`aliases` are the hovered contig's other names).
 */
export function recordMatches(
  record: Record<string, unknown> | null | undefined,
  row: Record<string, unknown> | null | undefined,
  columns?: Iterable<string>,
  aliases?: readonly string[],
): boolean {
  if (!record || !row) return false;
  const allowed = columns ? new Set(columns) : null;
  let shared = 0;
  for (const key of Object.keys(record)) {
    if (allowed && !allowed.has(key)) continue;
    if (!Object.prototype.hasOwnProperty.call(row, key)) continue;
    const wanted = record[key];
    if (isBlank(wanted)) continue;
    shared += 1;
    const have = row[key];
    const equal = isContigColumn(key)
      ? !isBlank(have) && (valuesEqual(wanted, have) || sameContig(String(wanted), String(have), aliases))
      : valuesEqual(wanted, have);
    if (!equal) return false;
  }
  return shared > 0;
}

/** The interval a record names through the caller's own columns, or `null`
 *  when it lacks either (or the position is not a number). `endCol`, when
 *  bound and present, makes it a span; otherwise it is the single position. */
export function genomicFromRecord(
  record: Record<string, unknown> | null | undefined,
  chromCol: string | null | undefined,
  posCol: string | null | undefined,
  endCol?: string | null,
): GenomicInterval | null {
  if (!record || !chromCol || !posCol) return null;
  const chrom = record[chromCol];
  const pos = record[posCol];
  if (isBlank(chrom) || isBlank(pos)) return null;
  const start = Number(pos);
  if (!Number.isFinite(start)) return null;
  const rawEnd = endCol ? record[endCol] : undefined;
  const end = isBlank(rawEnd) ? start : Number(rawEnd);
  return {
    refName: String(chrom),
    start: Math.min(start, Number.isFinite(end) ? end : start),
    end: Math.max(start, Number.isFinite(end) ? end : start),
  };
}

/**
 * What a bus event asks a plot with these chrom / pos columns to mark: the
 * event's own `genomic` interval, else the one its `record` spells through
 * the plot's columns. `null` when the event names neither (a residue hover, a
 * table without those columns).
 */
export function hoverInterval(
  event: HighlightEvent | null,
  chromCol: string | null | undefined,
  posCol: string | null | undefined,
  endCol?: string | null,
): GenomicInterval | null {
  if (!event) return null;
  if (event.genomic) {
    const { refName, start, end } = event.genomic;
    if (refName && Number.isFinite(start) && Number.isFinite(end)) {
      return { ...event.genomic, start: Math.min(start, end), end: Math.max(start, end) };
    }
  }
  const fromRecord = genomicFromRecord(event.record, chromCol, posCol, endCol);
  if (!fromRecord) return null;
  return event.entityAliases ? { ...fromRecord, aliases: event.entityAliases } : fromRecord;
}

/** Base pairs under `px` pixels on an axis showing `xRange` over `widthPx`. */
export function pixelsToBp(
  px: number,
  xRange: readonly [number, number] | null | undefined,
  widthPx: number | null | undefined,
): number {
  if (!xRange || !widthPx || widthPx <= 0) return 0;
  const span = Math.abs(xRange[1] - xRange[0]);
  return Number.isFinite(span) ? (px * span) / widthPx : 0;
}

export interface GenomicPoints {
  chroms: readonly string[];
  positions: readonly number[];
  /** Each point's row key (the selection value), when the plot has one. */
  keys?: readonly (string | null | undefined)[];
}

/**
 * Index of the point a hover refers to, or -1.
 *
 * Points whose key is in `rowKeys` win (on the target's contig when there is
 * one, nearest first). Otherwise the point on the target's contig closest to
 * the interval, within `toleranceBp` of it (the widening that keeps a one-base
 * feature hittable at pixel scale); ties go to the one nearest the midpoint.
 */
export function nearestGenomicPoint(
  points: GenomicPoints,
  target: GenomicInterval | null,
  opts: { toleranceBp?: number; rowKeys?: readonly string[] } = {},
): number {
  const { chroms, positions, keys } = points;
  const n = Math.min(chroms.length, positions.length);
  const tol = Math.max(0, opts.toleranceBp ?? 0);
  // One contig comparison per distinct spelling, not per point.
  const onTarget = new Map<string, boolean>();
  const contigMatches = (c: string): boolean => {
    if (!target) return true;
    let hit = onTarget.get(c);
    if (hit === undefined) {
      hit = sameContig(target.refName, c, target.aliases);
      onTarget.set(c, hit);
    }
    return hit;
  };
  const mid = target ? (target.start + target.end) / 2 : 0;
  const rank = (pos: number): [number, number] => {
    if (!target) return [0, 0];
    const d = pos < target.start ? target.start - pos : pos > target.end ? pos - target.end : 0;
    return [d, Math.abs(pos - mid)];
  };
  const better = (a: [number, number], b: [number, number] | null) =>
    !b || a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]);

  const wanted = opts.rowKeys?.length && keys ? new Set(opts.rowKeys) : null;
  if (wanted && keys) {
    let best = -1;
    let bestRank: [number, number] | null = null;
    for (let i = 0; i < n; i += 1) {
      const key = keys[i];
      if (key == null || !wanted.has(key) || !contigMatches(chroms[i])) continue;
      const r = rank(Number(positions[i]));
      if (better(r, bestRank)) {
        best = i;
        bestRank = r;
      }
    }
    if (best >= 0) return best;
  }

  if (!target) return -1;
  let best = -1;
  let bestRank: [number, number] | null = null;
  for (let i = 0; i < n; i += 1) {
    const pos = Number(positions[i]);
    if (!Number.isFinite(pos) || !contigMatches(chroms[i])) continue;
    const r = rank(pos);
    if (r[0] > tol) continue;
    if (better(r, bestRank)) {
      best = i;
      bestRank = r;
    }
  }
  return best;
}

/** Decides whether a table row is the one a hover refers to. */
export type RowMatcher = (row: Record<string, unknown>) => boolean;

/**
 * The test a table applies to its rows for the hover in force, or `null` when
 * the event names nothing a table can compare (a residue position, no keys, no
 * record). A row matches when the table's selection column holds one of the
 * event's `rowKeys`, or when the event's `record` agrees with it on the columns
 * both carry (see `recordMatches`); a table with neither simply never matches.
 */
export function rowMatcher(
  event: HighlightEvent | null,
  selectionColumn?: string | null,
): RowMatcher | null {
  if (!event) return null;
  const keys =
    selectionColumn && event.rowKeys?.length ? new Set(event.rowKeys.map(String)) : null;
  const record = event.record && Object.keys(event.record).length ? event.record : null;
  if (!keys && !record) return null;
  const aliases = event.genomic?.aliases ?? event.entityAliases;
  return (row) => {
    if (keys && selectionColumn) {
      const v = row[selectionColumn];
      if (v != null && keys.has(String(v))) return true;
    }
    return record ? recordMatches(record, row, undefined, aliases) : false;
  };
}
