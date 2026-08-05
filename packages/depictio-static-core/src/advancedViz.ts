/**
 * In-browser port of the advanced-viz sampling policy — the pure reduction
 * stage of `POST /advanced_viz/data`.
 *
 * The server reduces at scan level
 * (depictio/api/v1/endpoints/advanced_viz_endpoints/routes.py::_load_reduced,
 * :453–557) according to a per-kind policy table
 * (depictio/models/components/advanced_viz/sampling.py). This module replays
 * that decision tree over already-masked, materialized column arrays: the
 * static runtime does mask + projection with the existing engine, then hands
 * the projected columns here. Behaviour is pinned by
 * depictio/tests/unit/test_advanced_viz_sampling.py, mirrored in
 * test/advancedViz.test.ts.
 *
 * Server ↔ browser mapping (routes.py line refs):
 *
 *   policy table   — KIND_SAMPLING_POLICY / TAIL_ROLE / policyForKind /
 *     resolveTailDirection mirror sampling.py:40–133 verbatim.
 *   'none'         — the whole frame up to `advanced_viz_no_sample_max_rows`
 *     (:507–522); past that ceiling the kind is sampled anyway and the result
 *     is flagged `degraded` (its renderer's aggregates are now estimates).
 *   small frames   — `total <= cap` returns the frame whole, exact, under the
 *     kind's policy name (:524–526).
 *   'tail'         — resolve (column, direction, threshold) as _resolve_tail
 *     (:317–390): a client tail spec wins when usable; otherwise the kind's
 *     TAIL_ROLE names the role, `roles` binds it to a column, an 'auto'
 *     direction is read off the column's observed range, and the threshold
 *     comes from the limits ('both' → effect threshold; 'low'/'high' → p
 *     threshold, transformed to -log10(p) for 'high', :380–389). Then sample
 *     as _tail_sample (:393–450): the tail whole plus a strided middle, or a
 *     strided tail alone when the tail itself exceeds the cap; a result past
 *     cap*4 means the threshold isn't selecting cleanly → fall through to
 *     hash.
 *   hash           — stride = ceil(total / cap), keep rows whose row hash is
 *     ≡ 0 (mod stride), as _hash_sample (:270–301). A height outside
 *     [cap // 4, cap * 4] is a degenerate split (too few distinct value
 *     tuples): not degraded → return the WHOLE frame as policy 'full'
 *     (the server's fall-back to the unbounded row loader, :536–537 + :818–824);
 *     degraded (past the no-sample ceiling) → the first `cap` rows as policy
 *     'head' (:538–550), bounded because the frame was too big to hold.
 *
 * The explicit `limit_rows` / `full_load` request shapes are handled by the
 * CALLER (routes.py:656–666 sets no policy for them and never reaches
 * _load_reduced); this module only implements the default, policy-driven path
 * and assumes `limits.figure_max_points > 0` (the caller's gate, :665).
 * Float rounding (routes.py:840–842) is likewise the caller's step —
 * `roundSigFigs` is exported for it but reduceFrame does not round.
 *
 * DELIBERATE DEVIATION (the only one): the row hash. The server hashes
 * `pl.struct(projection).hash(seed=0) % stride == 0` (:289). Polars' hash is
 * not reproducible outside polars, so this port uses FNV-1a 32-bit over a
 * type-tagged serialization of the row's projected values, finalized with
 * murmur3's fmix32. It is property-preserving rather than bit-identical:
 * deterministic, decided per distinct value tuple (hashing all projected
 * columns, so rare categories survive per-row rather than being taken in or
 * out wholesale), and approximately uniform mod small strides — the sampled
 * ROW SET differs from the server's, the sampling BEHAVIOUR does not.
 */

import type { RuntimeLimits } from './manifest';

export type SamplingPolicy = 'none' | 'hash' | 'tail';
export type TailDirection = 'low' | 'high' | 'both';

export interface AdvancedVizTailSpec {
  column: string;
  direction: TailDirection;
  threshold: number;
}

/**
 * Which reduction each kind's renderer can survive — sampling.py:40–62
 * verbatim.
 *
 *   'hash' — uniform sample; the renderer draws one mark per row.
 *   'none' — never sample; the renderer aggregates client-side, so a subset
 *            changes the reported values, not their resolution.
 *   'tail' — keep the distribution's tail whole, stride the dense middle.
 */
export const KIND_SAMPLING_POLICY: Record<string, SamplingPolicy> = {
  // Point clouds — uniform is faithful.
  embedding: 'hash',
  qq: 'hash',
  lollipop: 'hash',
  coverage_track: 'hash',
  // Tail-carrying point clouds.
  volcano: 'tail',
  ma: 'tail',
  manhattan: 'tail',
  // Client-side aggregation — a sample is a wrong answer.
  stacked_taxonomy: 'none',
  rarefaction: 'none',
  da_barplot: 'none',
  enrichment: 'none',
  sunburst: 'none',
  dot_plot: 'none',
  oncoplot: 'none',
  upset_plot: 'none',
  complex_heatmap: 'none',
  sankey: 'none',
  phylogenetic: 'none',
};

/**
 * The role whose tail a 'tail' kind must keep, and which end is interesting —
 * sampling.py:76–80. 'auto' is pinned at reduce time from the bound column's
 * observed range (a significance column arrives as a raw p-value or as its
 * -log10, depending on the pipeline).
 */
export const TAIL_ROLE: Record<string, [role: string, direction: TailDirection | 'auto']> = {
  volcano: ['significance', 'auto'],
  ma: ['log2_fold_change', 'both'],
  manhattan: ['score', 'auto'],
};

/**
 * Reduction policy for a viz kind — sampling.py::policy_for_kind (:91–102).
 * An absent or unrecognised kind gets 'hash', the behaviour every caller had
 * before the policy table existed.
 */
export function policyForKind(vizKind: string | null | undefined): SamplingPolicy {
  if (!vizKind) return 'hash';
  return KIND_SAMPLING_POLICY[vizKind] ?? 'hash';
}

/**
 * Pin an 'auto' tail direction from the column's observed range —
 * sampling.py::resolve_tail_direction (:112–133). p-values live in [0, 1];
 * -log10 scores do not stay there for any dataset with a single hit below
 * p = 0.1. An unreadable range (all-null / empty) lands on 'low': there is
 * nothing to preserve either way.
 */
export function resolveTailDirection(min: number | null, max: number | null): TailDirection {
  if (min === null || max === null) return 'low';
  return 0.0 <= min && max <= 1.0 ? 'low' : 'high';
}

/**
 * polars `round_sig_figs(6)` as applied at response assembly
 * (routes.py:831–842): finite non-zero numbers are rounded to six significant
 * digits; 0, null, NaN, ±Infinity and non-numbers pass through unchanged.
 * Applied per value by the caller (the server only rounds float columns; the
 * browser has no dtype, so the caller decides which columns to round).
 */
export function roundSigFigs(v: unknown): unknown {
  if (typeof v !== 'number' || v === 0 || !Number.isFinite(v)) return v;
  return Number(v.toPrecision(6));
}

export interface ReduceRequest {
  /** Projection, order preserved. Every name must be present in `data`. */
  columns: string[];
  /** Masked, materialized columns — all arrays the same length. */
  data: Record<string, unknown[]>;
  vizKind?: string | null;
  /** role -> bound column name (the tail fallback path reads these). */
  roles?: Record<string, string>;
  /** Client-supplied tail spec — wins over the role table when usable. */
  tail?: AdvancedVizTailSpec | null;
  limits: RuntimeLimits;
}

export interface ReduceResult {
  rows: Record<string, unknown[]>;
  row_count: number;
  /** ALWAYS the pre-reduction count — the "of M" half of the badge. */
  total_rows: number;
  sampled: boolean;
  /**
   * `policy` is what actually ran: 'none' | 'hash' | 'tail' | 'full' | 'head'.
   * `degraded` means a kind that must not be sampled was sampled anyway (its
   * renderer's aggregates are now estimates) — distinct from `exact`, which is
   * merely "you did not get every row".
   */
  sampling: { policy: string; exact: boolean; degraded: boolean };
}

/**
 * Reduce a masked, projected frame the way its kind's policy allows —
 * `_load_reduced` (routes.py:453–557) minus the scan plumbing. Pure: input
 * arrays are never mutated; result arrays are fresh.
 */
export function reduceFrame(req: ReduceRequest): ReduceResult {
  const { columns, limits } = req;
  const cols = columns.map((name) => {
    const values = req.data[name];
    if (!Array.isArray(values)) {
      throw new Error(`advancedViz: projected column "${name}" is missing from data`);
    }
    return values;
  });
  const total = cols.length > 0 ? cols[0].length : 0;
  for (let c = 1; c < cols.length; c++) {
    if (cols[c].length !== total) {
      throw new Error(
        `advancedViz: column "${columns[c]}" has ${cols[c].length} values but ` +
          `"${columns[0]}" has ${total}`,
      );
    }
  }

  const policy = policyForKind(req.vizKind);
  const cap = limits.figure_max_points;

  // Set when a kind that must not be sampled was sampled anyway (routes.py:486).
  let degraded = false;

  if (policy === 'none') {
    const ceiling = limits.advanced_viz_no_sample_max_rows;
    if (ceiling <= 0 || total <= ceiling) {
      return exact(columns, cols, total, 'none');
    }
    // Serving it whole is what this kind needs and what the runtime cannot
    // afford — sample, and say the aggregate is approximate (routes.py:511–522).
    degraded = true;
  }

  if (total <= cap) {
    // Nothing to reduce — the frame whole, under the kind's policy name
    // (routes.py:524–526: `_exact(scan.collect(), total, policy)`).
    return exact(columns, cols, total, policy);
  }

  if (policy === 'tail') {
    const spec = resolveTail(req, columns, cols, limits);
    const idx = spec === null ? null : tailSample(columns, cols, total, cap, spec);
    if (idx !== null) {
      // The tail path never carries `degraded` — the server passes plain
      // `_reduced(frame, total, "tail")` (routes.py:532); degraded only rides
      // the hash/head branches, and only a 'none' kind can set it.
      return reduced(columns, cols, idx, total, 'tail', false);
    }
  }

  const idx = hashSample(cols, total, cap);
  if (idx === null) {
    if (!degraded) {
      // The projection's value tuples are too coarse to split on. The server
      // bails to the unbounded row loader, which reports policy 'full'
      // (routes.py:536–537 + 818–824) — here that is simply the whole frame.
      return exact(columns, cols, total, 'full');
    }
    // Past the no-sample ceiling the frame was too big to HOLD, not merely to
    // draw, so the fallback cannot be unbounded: a prefix is a poor sample,
    // but it is bounded and already flagged as an estimate (routes.py:538–550).
    const head: number[] = [];
    for (let i = 0; i < Math.min(cap, total); i++) head.push(i);
    return reduced(columns, cols, head, total, 'head', true);
  }
  return reduced(columns, cols, idx, total, 'hash', degraded);
}

// ---------------------------------------------------------------------------
// result assembly (routes.py:488–492)
// ---------------------------------------------------------------------------

function exact(
  columns: string[],
  cols: unknown[][],
  total: number,
  policy: string,
): ReduceResult {
  const rows: Record<string, unknown[]> = {};
  for (let c = 0; c < columns.length; c++) rows[columns[c]] = cols[c].slice();
  return {
    rows,
    row_count: total,
    total_rows: total,
    sampled: false,
    sampling: { policy, exact: true, degraded: false },
  };
}

function reduced(
  columns: string[],
  cols: unknown[][],
  idx: number[],
  total: number,
  policy: string,
  degraded: boolean,
): ReduceResult {
  const rows: Record<string, unknown[]> = {};
  for (let c = 0; c < columns.length; c++) {
    const src = cols[c];
    const out: unknown[] = new Array(idx.length);
    for (let k = 0; k < idx.length; k++) out[k] = src[idx[k]];
    rows[columns[c]] = out;
  }
  return {
    rows,
    row_count: idx.length,
    total_rows: total,
    sampled: true,
    sampling: { policy, exact: false, degraded },
  };
}

// ---------------------------------------------------------------------------
// tail resolution (_resolve_tail, routes.py:317–390)
// ---------------------------------------------------------------------------

interface ResolvedTail {
  column: string;
  direction: TailDirection;
  threshold: number;
}

function resolveTail(
  req: ReduceRequest,
  columns: string[],
  cols: unknown[][],
  limits: RuntimeLimits,
): ResolvedTail | null {
  const available = new Set(columns);

  // A payload that carries `tail` is taken at its word — the renderer draws
  // the threshold lines, so the plot keeps exactly the rows it would mark as
  // hits (routes.py:341–353). `Number(...)` mirrors the server's `float(...)`
  // coercion; a non-finite result is unusable (the contract pins finiteness,
  // nominally stricter than Python's float(), which admits inf/nan spellings
  // no JSON payload carries).
  const tail = req.tail;
  if (tail) {
    const direction = tail.direction || 'both';
    const threshold = Number(tail.threshold);
    if (
      available.has(tail.column) &&
      Number.isFinite(threshold) &&
      (direction === 'low' || direction === 'high' || direction === 'both')
    ) {
      return { column: tail.column, direction, threshold };
    }
  }

  // Fallback for callers that send only vizKind: the role table names the
  // column and the limits supply a conventional cutoff (routes.py:355–390).
  const spec = req.vizKind ? TAIL_ROLE[req.vizKind] : undefined;
  if (spec === undefined) return null;
  const [role, declared] = spec;
  const column = (req.roles ?? {})[role];
  if (!column || !available.has(column)) return null;

  let direction: TailDirection;
  if (declared === 'auto') {
    // The observed range tells a p-value from its -log10 — see
    // resolveTailDirection. Nulls and NaN are skipped, like polars' min/max
    // over nulls; an unreadable range lands on 'low' harmlessly.
    const values = cols[columns.indexOf(column)];
    let lo: number | null = null;
    let hi: number | null = null;
    for (const raw of values) {
      const v = typeof raw === 'bigint' ? Number(raw) : raw;
      if (typeof v !== 'number' || Number.isNaN(v)) continue;
      if (lo === null || v < lo) lo = v;
      if (hi === null || v > hi) hi = v;
    }
    direction = resolveTailDirection(lo, hi);
  } else {
    direction = declared;
  }

  let threshold =
    direction === 'both'
      ? limits.advanced_viz_tail_effect_threshold
      : limits.advanced_viz_tail_p_threshold;
  if (direction === 'high') {
    // A -log10 column compares against the transformed cutoff, not the raw p
    // (routes.py:385–389).
    threshold = threshold > 0 ? -Math.log10(threshold) : 0.0;
  }
  return { column, direction, threshold };
}

// ---------------------------------------------------------------------------
// tail sampling (_tail_predicate + _tail_sample, routes.py:305–314, 393–450)
// ---------------------------------------------------------------------------

/**
 * Rows a tail kind must keep whole: the significant end of the column.
 * null/undefined/NaN/non-numeric → false, mirroring `.fill_null(False)`
 * (routes.py:413) — nulls are not tail members and must not be dropped by the
 * negation either.
 */
function tailKeep(raw: unknown, direction: TailDirection, threshold: number): boolean {
  const v = typeof raw === 'bigint' ? Number(raw) : raw;
  if (typeof v !== 'number' || Number.isNaN(v)) return false;
  if (direction === 'low') return v <= threshold;
  if (direction === 'high') return v >= threshold;
  return Math.abs(v) >= threshold;
}

/**
 * Every row in the tail, plus a uniform sample of the dense middle — or, when
 * the tail alone exceeds the cap (a threshold that isn't selecting), a stride
 * over the tail itself rather than a truncation that would silently drop
 * whichever hits sorted last. Returns kept row indices, or null when the
 * result blew past cap*4 (the middle's value tuples were too coarse to hash;
 * the tail is a floor on the result, so only the upper bound means anything —
 * routes.py:430–440) — the caller then falls through to a uniform sample.
 */
function tailSample(
  columns: string[],
  cols: unknown[][],
  total: number,
  cap: number,
  spec: ResolvedTail,
): number[] | null {
  const values = cols[columns.indexOf(spec.column)];
  const keep = new Uint8Array(total);
  let nTail = 0;
  for (let i = 0; i < total; i++) {
    if (tailKeep(values[i], spec.direction, spec.threshold)) {
      keep[i] = 1;
      nTail++;
    }
  }

  const idx: number[] = [];
  if (nTail >= cap) {
    const stride = Math.ceil(nTail / cap);
    for (let i = 0; i < total; i++) {
      if (keep[i] === 1 && hashRow(cols, i) % stride === 0) idx.push(i);
    }
  } else {
    const budget = Math.max(1, cap - nTail);
    const stride = Math.max(1, Math.ceil((total - nTail) / budget));
    for (let i = 0; i < total; i++) {
      if (keep[i] === 1 || hashRow(cols, i) % stride === 0) idx.push(i);
    }
  }
  if (idx.length > cap * 4) return null;
  return idx;
}

// ---------------------------------------------------------------------------
// uniform hash sampling (_hash_sample, routes.py:270–301)
// ---------------------------------------------------------------------------

/**
 * ~`cap` row indices drawn uniformly, or null if the hash collapsed. The
 * decision hashes ALL projected columns, not one: a single-column hash would
 * keep or drop every row sharing a value, taking whole categories in or out.
 * A height outside [cap // 4, cap * 4] means the projection's distinct value
 * tuples were too few to split on — the band is deliberately wide, catching a
 * degenerate split rather than policing the sample size.
 */
function hashSample(cols: unknown[][], total: number, cap: number): number[] | null {
  const stride = Math.ceil(total / cap);
  const idx: number[] = [];
  for (let i = 0; i < total; i++) {
    if (hashRow(cols, i) % stride === 0) idx.push(i);
  }
  if (!(Math.floor(cap / 4) <= idx.length && idx.length <= cap * 4)) return null;
  return idx;
}

// ---------------------------------------------------------------------------
// row hashing — the one deliberate deviation from the server (see module doc)
// ---------------------------------------------------------------------------

/**
 * Deterministic 32-bit hash of row `i`'s projected value tuple: FNV-1a over a
 * type-tagged serialization of each cell, finished with murmur3's fmix32 so
 * the low bits (the ones `% stride` reads) are well mixed. Property-preserving
 * stand-in for `pl.struct(projection).hash(seed=0)` — same tuple, same hash;
 * different tuples split approximately uniformly.
 */
function hashRow(cols: unknown[][], i: number): number {
  let h = 0x811c9dc5;
  for (let c = 0; c < cols.length; c++) {
    const s = cellKey(cols[c][i]);
    for (let k = 0; k < s.length; k++) {
      h ^= s.charCodeAt(k);
      h = Math.imul(h, 0x01000193);
    }
    // Cell separator, so ("ab","c") and ("a","bc") hash differently.
    h ^= 0x1f;
    h = Math.imul(h, 0x01000193);
  }
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return h >>> 0;
}

/** Type-tagged cell serialization: number 1 and string "1" must not collide. */
function cellKey(v: unknown): string {
  if (v === null || v === undefined) return '\x00';
  if (typeof v === 'number') return 'n:' + String(v);
  if (typeof v === 'bigint') return 'n:' + v.toString();
  if (typeof v === 'boolean') return 'b:' + String(v);
  if (typeof v === 'string') return 's:' + v;
  if (v instanceof Date) return 'd:' + String(v.getTime());
  return 'x:' + String(v);
}
