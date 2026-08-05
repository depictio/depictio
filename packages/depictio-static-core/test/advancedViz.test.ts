/**
 * Browser-side advanced-viz sampling tests — the vitest mirror of
 * depictio/tests/unit/test_advanced_viz_sampling.py, pinning the same
 * properties over reduceFrame (the pure port of routes.py::_load_reduced):
 * the sample spans the whole frame, the reported total is the pre-sample
 * count, a degenerate hash split falls back to the whole frame, 'none' kinds
 * are never sampled below the ceiling and are flagged `degraded` above it,
 * and tail kinds keep their tail whole.
 */

import { describe, expect, it } from 'vitest';

import {
  KIND_SAMPLING_POLICY,
  TAIL_ROLE,
  policyForKind,
  reduceFrame,
  resolveTailDirection,
  roundSigFigs,
  type ReduceRequest,
  type ReduceResult,
} from '../src/advancedViz';
import { DEFAULT_LIMITS, type RuntimeLimits } from '../src/manifest';

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function limits(overrides: Partial<RuntimeLimits> = {}): RuntimeLimits {
  return { ...DEFAULT_LIMITS, ...overrides };
}

function reduce(
  data: Record<string, unknown[]>,
  req: Partial<ReduceRequest> & { limits?: RuntimeLimits } = {},
): ReduceResult {
  return reduceFrame({
    columns: Object.keys(data),
    data,
    limits: limits(),
    ...req,
  });
}

function seq(n: number, fn: (i: number) => unknown): unknown[] {
  const out: unknown[] = new Array(n);
  for (let i = 0; i < n; i++) out[i] = fn(i);
  return out;
}

/** A DE table: a dense non-significant blob plus a handful of real hits. */
function deFrame(n = 200_000, hits = 40): Record<string, unknown[]> {
  return {
    feature_id: seq(n, (i) => `g${i}`),
    effect_size: seq(n, (i) => (i % 13) - 6),
    // Hits are the first `hits` rows, at p ~ 1e-8; everything else is spread
    // over [0.2, 1.0] and must never be mistaken for a hit.
    significance: seq(n, (i) => (i < hits ? 1e-8 : 0.2 + (i % 800) / 1000.0)),
  };
}

function countWhere(values: unknown[], pred: (v: number) => boolean): number {
  let n = 0;
  for (const v of values) if (typeof v === 'number' && pred(v)) n++;
  return n;
}

// ---------------------------------------------------------------------------
// uniform hash sampling (no vizKind — the historical default)
// ---------------------------------------------------------------------------

describe('uniform hash sampling', () => {
  it('spans the whole frame, not a prefix', () => {
    // The regression the server path replaced: row_id is monotonic, so a
    // prefix would return only small values.
    const n = 200_000;
    const out = reduce(
      { row_id: seq(n, (i) => i), v: seq(n, (i) => i % 977) },
      { limits: limits({ figure_max_points: 10_000 }) },
    );

    expect(out.sampled).toBe(true);
    expect(out.total_rows).toBe(n);
    expect(out.sampling.policy).toBe('hash');
    const ids = out.rows['row_id'] as number[];
    expect(Math.max(...ids)).toBeGreaterThan(0.95 * n);
    expect(Math.min(...ids)).toBeLessThan(0.05 * n);
    // Spread across the whole range, not clustered at either end.
    const mean = ids.reduce((a, b) => a + b, 0) / ids.length;
    expect(mean).toBeGreaterThan(0.4 * n);
    expect(mean).toBeLessThan(0.6 * n);
  });

  it('keeps every category — the hash decides per row, not per value', () => {
    // 'rare' is 1 row in 1000; a per-value hash would drop it wholesale.
    const n = 300_000;
    const out = reduce(
      {
        row_id: seq(n, (i) => i),
        cls: seq(n, (i) => (i % 1000 === 0 ? 'rare' : `c${i % 7}`)),
      },
      { limits: limits({ figure_max_points: 10_000 }) },
    );

    expect(out.sampled).toBe(true);
    expect(new Set(out.rows['cls'])).toContain('rare');
  });

  it('reports total_rows as the pre-sample count', () => {
    const n = 50_000;
    const out = reduce(
      { row_id: seq(n, (i) => i) },
      { limits: limits({ figure_max_points: 1_000 }) },
    );

    expect(out.total_rows).toBe(n);
    expect(out.sampled).toBe(true);
    expect(out.row_count).toBeLessThan(n);
    expect(out.rows['row_id']).toHaveLength(out.row_count);
  });

  it('returns small frames whole, under the kind policy name, unsampled', () => {
    const out = reduce(
      { row_id: seq(300, (i) => i) },
      { vizKind: 'embedding', limits: limits({ figure_max_points: 10_000 }) },
    );

    expect(out.sampled).toBe(false);
    expect(out.total_rows).toBe(300);
    expect(out.row_count).toBe(300);
    expect(out.sampling).toEqual({ policy: 'hash', exact: true, degraded: false });

    // A small tail-kind frame is exact too, and says 'tail'.
    const tailOut = reduce(deFrame(500, 5), {
      vizKind: 'volcano',
      limits: limits({ figure_max_points: 10_000 }),
    });
    expect(tailOut.sampling).toEqual({ policy: 'tail', exact: true, degraded: false });
    expect(tailOut.row_count).toBe(500);
  });

  it.each([1, 2, 3])(
    'falls back to the whole frame on a degenerate split (%d distinct tuples)',
    (nDistinct) => {
      // struct-hash % stride decides per distinct value tuple; with a handful
      // of tuples the split is all-or-nothing per tuple, and both directions
      // are wrong. The server bails to the unbounded row loader (policy
      // 'full'); here that is the whole frame.
      const n = 90_000;
      const out = reduce(
        { flag: seq(n, (i) => i % nDistinct) },
        { limits: limits({ figure_max_points: 1_000 }) },
      );

      expect(out.sampling).toEqual({ policy: 'full', exact: true, degraded: false });
      expect(out.sampled).toBe(false);
      expect(out.row_count).toBe(n);
      expect(out.total_rows).toBe(n);
    },
  );

  it('samples uniformly when no vizKind is given (the pre-policy contract)', () => {
    const n = 20_000;
    const out = reduce(
      { row_id: seq(n, (i) => i), v: seq(n, (i) => i % 977) },
      { limits: limits({ figure_max_points: 1_000 }) },
    );

    expect(out.sampling.policy).toBe('hash');
    expect(out.sampling.degraded).toBe(false);
    expect(out.sampled).toBe(true);
    expect(out.total_rows).toBe(n);
    expect(out.row_count).toBeLessThan(n);
  });
});

// ---------------------------------------------------------------------------
// per-kind policy
// ---------------------------------------------------------------------------

describe('per-kind policy tables', () => {
  it('cover every AdvancedVizKind, and every tail kind has a role', () => {
    // Pinned from depictio/models/components/types.py:28–47.
    const kinds = [
      'volcano',
      'embedding',
      'manhattan',
      'stacked_taxonomy',
      'phylogenetic',
      'rarefaction',
      'da_barplot',
      'enrichment',
      'complex_heatmap',
      'upset_plot',
      'ma',
      'dot_plot',
      'lollipop',
      'qq',
      'sunburst',
      'oncoplot',
      'coverage_track',
      'sankey',
    ];
    expect(new Set(Object.keys(KIND_SAMPLING_POLICY))).toEqual(new Set(kinds));
    expect(Object.keys(KIND_SAMPLING_POLICY)).toHaveLength(18);

    const tailKinds = Object.keys(KIND_SAMPLING_POLICY).filter(
      (k) => KIND_SAMPLING_POLICY[k] === 'tail',
    );
    expect(new Set(Object.keys(TAIL_ROLE))).toEqual(new Set(tailKinds));
    expect(new Set(Object.keys(TAIL_ROLE))).toEqual(new Set(['volcano', 'ma', 'manhattan']));
  });

  it('policyForKind defaults absent/unknown kinds to hash', () => {
    expect(policyForKind(null)).toBe('hash');
    expect(policyForKind(undefined)).toBe('hash');
    expect(policyForKind('')).toBe('hash');
    expect(policyForKind('some_future_kind')).toBe('hash');
    expect(policyForKind('volcano')).toBe('tail');
    expect(policyForKind('sankey')).toBe('none');
  });

  it('never samples an aggregating kind below the ceiling', () => {
    const n = 20_000;
    const out = reduce(
      { sample_id: seq(n, (i) => `s${i % 500}`), abundance: seq(n, (i) => i) },
      { vizKind: 'stacked_taxonomy', limits: limits({ figure_max_points: 1_000 }) },
    );

    expect(out.row_count).toBe(n);
    expect(out.total_rows).toBe(n);
    expect(out.sampled).toBe(false);
    expect(out.sampling).toEqual({ policy: 'none', exact: true, degraded: false });
  });

  it('treats a non-positive ceiling as unbounded for a none kind', () => {
    const n = 20_000;
    const out = reduce(
      { row_id: seq(n, (i) => i) },
      {
        vizKind: 'sankey',
        limits: limits({ figure_max_points: 1_000, advanced_viz_no_sample_max_rows: 0 }),
      },
    );

    expect(out.row_count).toBe(n);
    expect(out.sampling).toEqual({ policy: 'none', exact: true, degraded: false });
  });

  it('samples an aggregating kind past the ceiling and flags it degraded', () => {
    // The fallback is a sample, and the response has to say the aggregate is
    // now an estimate.
    const n = 50_000;
    const out = reduce(
      { row_id: seq(n, (i) => i), v: seq(n, (i) => i % 977) },
      {
        vizKind: 'stacked_taxonomy',
        limits: limits({ figure_max_points: 1_000, advanced_viz_no_sample_max_rows: 1_000 }),
      },
    );

    expect(out.total_rows).toBe(n);
    expect(out.row_count).toBeLessThan(n);
    expect(out.row_count).toBeLessThanOrEqual(1_000 * 4);
    expect(out.sampling.policy).toBe('hash');
    expect(out.sampling.degraded).toBe(true);
    expect(out.sampling.exact).toBe(false);
    expect(out.sampled).toBe(true);
  });

  it('bounds an unsamplable frame past the ceiling with a head prefix', () => {
    // Two distinct value tuples: the hash can only split all-or-nothing. Past
    // the no-sample ceiling the fallback cannot be the whole frame — that is
    // exactly the load the ceiling protects against.
    const n = 40_000;
    const cap = 1_000;
    const out = reduce(
      { flag: seq(n, (i) => i % 2) },
      {
        vizKind: 'stacked_taxonomy',
        limits: limits({ figure_max_points: cap, advanced_viz_no_sample_max_rows: 1_000 }),
      },
    );

    expect(out.row_count).toBeLessThanOrEqual(cap);
    expect(out.total_rows).toBe(n);
    expect(out.sampling).toEqual({ policy: 'head', exact: false, degraded: true });
    expect(out.sampled).toBe(true);
    // A prefix: the first rows in order.
    expect(out.rows['flag'][0]).toBe(0);
    expect(out.rows['flag'][1]).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// tail-preserving reduction
// ---------------------------------------------------------------------------

describe('tail-preserving reduction', () => {
  it('keeps a tail a uniform sample would have dropped', () => {
    // A uniform 10k of 200k keeps ~2 of 40 hits. The tail keeps all 40.
    const out = reduce(deFrame(), {
      vizKind: 'volcano',
      tail: { column: 'significance', direction: 'low', threshold: 0.05 },
      limits: limits({ figure_max_points: 10_000 }),
    });

    expect(out.sampling).toEqual({ policy: 'tail', exact: false, degraded: false });
    expect(out.total_rows).toBe(200_000);
    const keptHits = countWhere(out.rows['significance'] as unknown[], (v) => v <= 0.05);
    expect(keptHits).toBe(40);
    // And it is still a reduction, not a full load dressed up as one.
    expect(out.row_count).toBeLessThanOrEqual(10_000 * 4);
  });

  it('samples rather than truncates a tail that is the whole table', () => {
    // Everything is "significant" — a mis-set threshold, or a table already
    // filtered upstream. It must not blow the cap open.
    const n = 50_000;
    const out = reduce(
      {
        feature_id: seq(n, (i) => `g${i}`),
        significance: seq(n, (i) => 1e-9 + i * 1e-12),
      },
      {
        vizKind: 'volcano',
        tail: { column: 'significance', direction: 'low', threshold: 0.05 },
        limits: limits({ figure_max_points: 1_000 }),
      },
    );

    expect(out.total_rows).toBe(n);
    expect(out.row_count).toBeLessThanOrEqual(1_000 * 4);
    expect(out.sampling.policy).toBe('tail');
  });

  it('keeps both ends of a signed effect', () => {
    // An MA plot's hits are large |log2FC| in either direction.
    const n = 12_000;
    const out = reduce(
      {
        feature_id: seq(n, (i) => `g${i}`),
        // 20 strongly up, 20 strongly down, the rest inside ±0.5.
        log2fc: seq(n, (i) => (i < 20 ? 5.0 : i < 40 ? -5.0 : ((i % 100) - 50) / 100.0)),
      },
      {
        vizKind: 'ma',
        tail: { column: 'log2fc', direction: 'both', threshold: 1.0 },
        limits: limits({ figure_max_points: 1_000 }),
      },
    );

    expect(countWhere(out.rows['log2fc'] as unknown[], (v) => v >= 1.0)).toBe(20);
    expect(countWhere(out.rows['log2fc'] as unknown[], (v) => v <= -1.0)).toBe(20);
  });

  it('samples null-significance rows instead of dropping them', () => {
    // ~(null <= t) is null, which would filter nulls out of BOTH branches;
    // the server pins fill_null(False).
    const n = 10_000;
    const out = reduce(
      {
        feature_id: seq(n, (i) => `g${i}`),
        significance: seq(n, (i) => (i % 2 ? null : 0.9 - (i % 700) / 1000.0)),
      },
      {
        vizKind: 'volcano',
        tail: { column: 'significance', direction: 'low', threshold: 0.05 },
        limits: limits({ figure_max_points: 1_000 }),
      },
    );

    const nulls = (out.rows['significance'] as unknown[]).filter((v) => v === null).length;
    expect(nulls).toBeGreaterThan(0);
  });

  it('falls back to a uniform sample when no column is usable', () => {
    // An unbound role is a binding problem, not a reason to return nothing.
    const n = 20_000;
    const out = reduce(
      { row_id: seq(n, (i) => i), v: seq(n, (i) => i % 977) },
      { vizKind: 'volcano', roles: {}, limits: limits({ figure_max_points: 1_000 }) },
    );

    expect(out.sampling.policy).toBe('hash');
    expect(out.total_rows).toBe(n);
    expect(out.row_count).toBeLessThan(n);
  });

  it('reads an auto direction off the column range: a -log10 column keeps its high end', () => {
    // With no tail spec from the client, the range decides: a column that
    // leaves [0, 1] is a -log10 score, so the tail is its LARGE end, compared
    // against -log10(p_threshold).
    const n = 15_000;
    const out = reduce(
      {
        feature_id: seq(n, (i) => `g${i}`),
        // 30 hits at -log10(p) = 8; the rest below 1.
        significance: seq(n, (i) => (i < 30 ? 8.0 : (i % 900) / 1000.0)),
      },
      {
        vizKind: 'volcano',
        roles: { significance: 'significance' },
        limits: limits({ figure_max_points: 1_000 }),
      },
    );

    expect(out.sampling.policy).toBe('tail');
    expect(countWhere(out.rows['significance'] as unknown[], (v) => v >= 8.0)).toBe(30);
  });

  it('reads an auto direction off the column range: a p-value column keeps its low end', () => {
    const n = 15_000;
    const out = reduce(
      {
        feature_id: seq(n, (i) => `g${i}`),
        significance: seq(n, (i) => (i < 25 ? 1e-8 : 0.2 + (i % 800) / 1000.0)),
      },
      {
        vizKind: 'volcano',
        roles: { significance: 'significance' },
        limits: limits({ figure_max_points: 1_000 }),
      },
    );

    expect(out.sampling.policy).toBe('tail');
    expect(countWhere(out.rows['significance'] as unknown[], (v) => v <= 0.05)).toBe(25);
  });

  it('ignores an unusable client tail spec and falls back to the role table', () => {
    const n = 15_000;
    const out = reduce(
      {
        feature_id: seq(n, (i) => `g${i}`),
        significance: seq(n, (i) => (i < 30 ? 8.0 : (i % 900) / 1000.0)),
      },
      {
        vizKind: 'volcano',
        roles: { significance: 'significance' },
        // Column not in the projection → the spec is unusable, not fatal.
        tail: { column: 'not_a_column', direction: 'low', threshold: 0.05 },
        limits: limits({ figure_max_points: 1_000 }),
      },
    );

    expect(out.sampling.policy).toBe('tail');
    expect(countWhere(out.rows['significance'] as unknown[], (v) => v >= 8.0)).toBe(30);
  });
});

// ---------------------------------------------------------------------------
// resolveTailDirection / roundSigFigs
// ---------------------------------------------------------------------------

describe('resolveTailDirection', () => {
  it('reads a [0, 1] range as a p-value (low) and anything else as -log10 (high)', () => {
    expect(resolveTailDirection(0, 1)).toBe('low');
    expect(resolveTailDirection(0.001, 0.9)).toBe('low');
    expect(resolveTailDirection(0, 50)).toBe('high');
    expect(resolveTailDirection(-3, 0.5)).toBe('high');
  });

  it('lands an unreadable range on low — nothing to preserve either way', () => {
    expect(resolveTailDirection(null, null)).toBe('low');
    expect(resolveTailDirection(0, null)).toBe('low');
    expect(resolveTailDirection(null, 1)).toBe('low');
  });
});

describe('roundSigFigs', () => {
  it('rounds finite numbers to six significant digits', () => {
    expect(roundSigFigs(0.30000000000000004)).toBe(0.3);
    expect(roundSigFigs(123456789)).toBe(123457000);
    expect(roundSigFigs(-0.000123456789)).toBe(-0.000123457);
    expect(roundSigFigs(1.5)).toBe(1.5);
  });

  it('passes 0, null, NaN, infinities and non-numbers through unchanged', () => {
    expect(roundSigFigs(0)).toBe(0);
    expect(roundSigFigs(null)).toBe(null);
    expect(roundSigFigs(Number.NaN)).toBeNaN();
    expect(roundSigFigs(Number.POSITIVE_INFINITY)).toBe(Number.POSITIVE_INFINITY);
    expect(roundSigFigs(Number.NEGATIVE_INFINITY)).toBe(Number.NEGATIVE_INFINITY);
    expect(roundSigFigs('abc')).toBe('abc');
    expect(roundSigFigs(undefined)).toBe(undefined);
  });
});
