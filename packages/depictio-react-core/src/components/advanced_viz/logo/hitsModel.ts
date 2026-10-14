/**
 * The "HMM hit coverage" lane under the logo: where a set of hmmsearch hits
 * (a domain table: model, protein, `hmm_from..hmm_to`, `ali_from..ali_to`,
 * E-value, score) land on the model. Per-state coverage depth, greedy row
 * packing of the hit bars, partial-hit flags. Pure, unit-tested in
 * `hitsModel.test.ts`.
 */

import { frameLength, numberOrNull, rowIndicesWhere, stringOrNull } from '../protein/rendererData';

type Frame = Record<string, unknown[]>;

export interface LogoHit {
  /** Stable id of the hit within one fetch (its row index). */
  key: string;
  /** The protein the hit belongs to. */
  entity: string;
  /** HMM states the hit aligns to, inclusive, `from <= to` (1-based). */
  from: number;
  to: number;
  /** Model length the table reports (`hmm_length`), if any. */
  modelLength: number | null;
  evalue: number | null;
  score: number | null;
  /** Residues of the protein the hit aligns, inclusive, `aliFrom <= aliTo`. */
  aliFrom: number | null;
  aliTo: number | null;
}

/** Column names of the hits table (`HmmLogoConfig`'s `hits_*_col` fields). */
export interface HitColumns {
  model?: string | null;
  entity: string;
  from: string;
  to: string;
  length?: string | null;
  evalue?: string | null;
  score?: string | null;
  aliFrom?: string | null;
  aliTo?: string | null;
}

/**
 * The hits of `model` (every row when the frame has no model column: the
 * fetch was scoped to it). A row without an entity or an HMM span is skipped;
 * reversed spans are put in order.
 */
export function hitsFromFrame(
  frame: Frame | null | undefined,
  cols: HitColumns,
  model: string | null,
): LogoHit[] {
  if (!frame || frameLength(frame) === 0) return [];
  const read = (name: string | null | undefined) => (name ? frame[name] : undefined);
  const entities = read(cols.entity) ?? [];
  const froms = read(cols.from) ?? [];
  const tos = read(cols.to) ?? [];
  const lengths = read(cols.length);
  const evalues = read(cols.evalue);
  const scores = read(cols.score);
  const aliFroms = read(cols.aliFrom);
  const aliTos = read(cols.aliTo);
  const out: LogoHit[] = [];
  for (const i of rowIndicesWhere(frame, cols.model, model)) {
    const entity = stringOrNull(entities[i]);
    const a = numberOrNull(froms[i]);
    const b = numberOrNull(tos[i]);
    if (entity == null || a == null || b == null) continue;
    const x = aliFroms ? numberOrNull(aliFroms[i]) : null;
    const y = aliTos ? numberOrNull(aliTos[i]) : null;
    const both = x != null && y != null;
    out.push({
      key: String(i),
      entity,
      from: Math.round(Math.min(a, b)),
      to: Math.round(Math.max(a, b)),
      modelLength: lengths ? numberOrNull(lengths[i]) : null,
      evalue: evalues ? numberOrNull(evalues[i]) : null,
      score: scores ? numberOrNull(scores[i]) : null,
      aliFrom: both ? Math.min(x, y) : (x ?? y),
      aliTo: both ? Math.max(x, y) : (y ?? x),
    });
  }
  return out;
}

export interface HitSelection {
  /** Hits at or below the E-value threshold, best first (all of them). */
  passing: LogoHit[];
  /** The ones the lane draws: the first `maxHits` of `passing`. */
  drawn: LogoHit[];
  /** Hits of the model before the threshold. */
  total: number;
}

/** Best first: highest score, then lowest E-value, then the protein's name. */
export function compareHits(a: LogoHit, b: LogoHit): number {
  const sa = a.score ?? -Infinity;
  const sb = b.score ?? -Infinity;
  if (sa !== sb) return sb - sa;
  const ea = a.evalue ?? Infinity;
  const eb = b.evalue ?? Infinity;
  if (ea !== eb) return ea - eb;
  return a.entity.localeCompare(b.entity) || a.from - b.from;
}

/**
 * Hits at or below `evalueMax` (a hit with no E-value is kept: nothing says
 * it is above), best score first, capped at `maxHits` for drawing. A null
 * threshold keeps every hit.
 */
export function selectHits(
  hits: readonly LogoHit[],
  opts: { evalueMax: number | null | undefined; maxHits: number },
): HitSelection {
  const max = opts.evalueMax;
  const passing = hits
    .filter((h) => max == null || h.evalue == null || h.evalue <= max)
    .sort(compareHits);
  const cap = Math.max(0, Math.floor(opts.maxHits));
  return { passing, drawn: passing.slice(0, cap), total: hits.length };
}

/**
 * Coverage depth per match state: `depth[k - 1]` hits span state `k`
 * (`k = 1..length`), spans clamped to the model.
 */
export function coverageDepth(hits: readonly LogoHit[], length: number): Int32Array {
  const n = Math.max(0, Math.floor(length));
  const diff = new Int32Array(n + 1);
  for (const h of hits) {
    const lo = Math.max(1, h.from);
    const hi = Math.min(n, h.to);
    if (lo > hi) continue;
    diff[lo - 1] += 1;
    diff[hi] -= 1;
  }
  const depth = new Int32Array(n);
  let run = 0;
  for (let i = 0; i < n; i++) {
    run += diff[i];
    depth[i] = run;
  }
  return depth;
}

export interface HitPacking {
  /** Row of each hit, in the order given. */
  rowOf: Int32Array;
  rows: number;
  /** Per row, the indices of its hits sorted by `from` (hit testing). */
  byRow: number[][];
}

/**
 * Greedy first-fit packing in the order given (best hits first, so they take
 * the top rows): each hit goes to the first row where it overlaps no bar and
 * leaves `gap` states clear on each side.
 */
export function packHits(hits: readonly LogoHit[], gap = 1): HitPacking {
  const rowOf = new Int32Array(hits.length);
  const byRow: number[][] = [];
  hits.forEach((h, i) => {
    let row = 0;
    for (; row < byRow.length; row++) {
      const clash = byRow[row].some((j) => {
        const o = hits[j];
        return h.from <= o.to + gap && o.from <= h.to + gap;
      });
      if (!clash) break;
    }
    if (row === byRow.length) byRow.push([]);
    byRow[row].push(i);
    rowOf[i] = row;
  });
  for (const row of byRow) row.sort((a, b) => hits[a].from - hits[b].from);
  return { rowOf, rows: byRow.length, byRow };
}

/** Hits in the first `rowsShown` packed rows: the ones the lane draws. */
export function drawnHitCount(packing: HitPacking | null, rowsShown: number): number {
  if (!packing) return 0;
  const n = Math.max(0, Math.floor(rowsShown));
  let count = 0;
  for (let row = 0; row < Math.min(n, packing.byRow.length); row++) count += packing.byRow[row].length;
  return count;
}

/** Separator of the two parts of the hits lane label. */
export const HITS_LABEL_SEPARATOR = ' \u00b7 ';

/**
 * Label of the hits lane: how many hits pass the threshold, and, when the
 * bars cannot show them all, how many are drawn (`Hits 33 · 20 drawn`).
 * Rows left out of the lane are summarised here, never dropped silently.
 */
export function hitsLaneLabel(total: number, drawn: number): string {
  const shown = Math.max(0, Math.min(total, drawn));
  return shown < total
    ? `Hits ${total}${HITS_LABEL_SEPARATOR}${shown} drawn`
    : `Hits ${total}`;
}

/** The hit drawn at `state` on `row`, or null. */
export function hitAt(
  hits: readonly LogoHit[],
  packing: HitPacking,
  row: number,
  state: number,
): LogoHit | null {
  const members = packing.byRow[row];
  if (!members) return null;
  for (const i of members) {
    const h = hits[i];
    if (h.from > state) break;
    if (state <= h.to) return h;
  }
  return null;
}

/**
 * Whether a hit stops short of the model's ends (Pfam's jagged edges): left
 * when it starts after state 1, right when it ends before the model's last
 * state (the table's `hmm_length`, else the profile's length).
 */
export function partialEdges(
  hit: LogoHit,
  modelLength: number | null | undefined,
): { left: boolean; right: boolean } {
  const length = hit.modelLength ?? modelLength ?? null;
  return { left: hit.from > 1, right: length != null && hit.to < length };
}

/**
 * Position of an E-value on the lane's colour ramp, 0 (the weakest drawn) to
 * 1 (the strongest), on -log10. Null E-values sit at the weak end; one
 * distinct value maps to 1.
 */
export function evalueScale(hits: readonly LogoHit[]): (evalue: number | null) => number {
  const logs = hits
    .map((h) => h.evalue)
    .filter((e): e is number => e != null && e >= 0)
    .map(negLog10);
  if (!logs.length) return () => 0.5;
  const lo = Math.min(...logs);
  const hi = Math.max(...logs);
  return (e) => {
    if (e == null || e < 0) return 0;
    if (hi === lo) return 1;
    return Math.max(0, Math.min(1, (negLog10(e) - lo) / (hi - lo)));
  };
}

/** -log10 with E = 0 (an underflow in the search output) capped at 300. */
function negLog10(e: number): number {
  return e > 0 ? Math.min(300, -Math.log10(e)) : 300;
}

/** E-value as hmmsearch prints it (`2.3e-12`), a dash when absent. */
export function formatEvalue(e: number | null): string {
  if (e == null) return '-';
  if (e === 0) return '0';
  return e < 0.001 || e >= 1000 ? e.toExponential(1) : String(Number(e.toPrecision(2)));
}
