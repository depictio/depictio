/**
 * Mask kernel vs. Polars ground truth, in the server's own predicate forms
 * (deltatables_utils.py add_filter:225 / _categorical_predicate:138).
 * Each expectation carries matched-row count AND the value_f64 sum over the
 * matched rows — a row-set checksum, so an equal count over different rows
 * still fails.
 */

import { describe, expect, it } from 'vitest';

import type { BoundFilter } from '../../src/engine/filters';
import type { Bitmask } from '../../src/engine/QueryEngine';
import { expectClose, expected, openFixture } from './helpers';

async function runMask(filters: BoundFilter[]) {
  const { engine, handle } = await openFixture();
  const result = await engine.mask(handle, filters);
  const sum = (await engine.aggregate(handle, result.mask, [
    { col: 'value_f64', fn: 'sum' },
  ])) as [number];
  return { ...result, value_f64_sum: sum[0] };
}

function check(actual: { matched: number; value_f64_sum: number }, name: string) {
  const exp = expected.filters[name];
  expect(actual.matched, `${name} matched`).toBe(exp.matched);
  expectClose(actual.value_f64_sum, exp.value_f64_sum);
}

describe('mask: in (String column)', () => {
  it('matches server is_in over stringified values', async () => {
    const r = await runMask([{ kind: 'in', column: 'category_str', values: ['alpha', 'beta'] }]);
    check(r, 'in_str');
  });
});

describe('mask: in (codebook path — codebooks written by the Python builder)', () => {
  it('option STRINGS (the primary runtime path) hit the str()-keyed codebook as-is', async () => {
    // fetchUniqueValues / Object.keys(codebook) hand the UI strings — the
    // codebook keys were produced by Python serialize_option (str()).
    const r = await runMask([{ kind: 'in', column: 'batch', values: ['2', '4'] }]);
    check(r, 'in_codebook');
  });

  it('numeric fallback values translate to the same codes', async () => {
    const r = await runMask([{ kind: 'in', column: 'batch', values: [2, 4] }]);
    check(r, 'in_codebook');
  });

  it('boolean column: "true"/"false" option strings match the builder\'s lowered keys', async () => {
    const asStrings = await runMask([{ kind: 'in', column: 'flag_bool', values: ['true'] }]);
    check(asStrings, 'in_bool');
    // Raw boolean fallback serializes to the same lowered key.
    const asBool = await runMask([{ kind: 'in', column: 'flag_bool', values: [true] }]);
    check(asBool, 'in_bool');
    // Python str(True) === "True" is NOT a codebook key (the builder lowers
    // deliberately — companions.py docstring): it must match nothing.
    const pythonStr = await runMask([{ kind: 'in', column: 'flag_bool', values: ['True'] }]);
    expect(pythonStr.matched).toBe(0);
  });

  it('a value missing from the codebook matches nothing (others still match)', async () => {
    const r = await runMask([{ kind: 'in', column: 'batch', values: [2, 99] }]);
    check(r, 'in_codebook_miss');
  });

  it('all values missing from the codebook -> zero rows', async () => {
    const r = await runMask([{ kind: 'in', column: 'batch', values: [99] }]);
    check(r, 'in_codebook_all_miss');
    expect(r.matched).toBe(0);
  });
});

describe('mask: range (RangeSlider — inclusive on both ends)', () => {
  it('matches server (col >= lo) & (col <= hi)', async () => {
    const r = await runMask([{ kind: 'range', column: 'value_f64', min: -0.5, max: 1.5 }]);
    check(r, 'range_f64');
  });

  it('bounds are inclusive: a mask at [v, v] keeps rows equal to v', async () => {
    const { engine, handle } = await openFixture();
    const batch = await engine.columns(handle, ['value_f64']);
    const col = batch['value_f64'];
    let v: number | undefined;
    for (let i = 0; i < col.length; i++) {
      if (typeof col[i] === 'number') {
        v = col[i] as number;
        break;
      }
    }
    const { matched } = await engine.mask(handle, [
      { kind: 'range', column: 'value_f64', min: v, max: v },
    ]);
    expect(matched).toBeGreaterThan(0);
  });

  it('missing bounds are unbounded (matches all non-null rows)', async () => {
    const { engine, handle } = await openFixture();
    const { matched } = await engine.mask(handle, [{ kind: 'range', column: 'value_f64' }]);
    expect(matched).toBe(expected.rows - expected.null_counts['value_f64']);
  });
});

describe('mask: eq (Slider)', () => {
  it('matches server col == value on an Int64 (BigInt-decoded) column', async () => {
    const exp = expected.filters['eq_i64'];
    const r = await runMask([{ kind: 'eq', column: 'value_i64', value: exp['value'] as number }]);
    check(r, 'eq_i64');
    expect(r.matched).toBeGreaterThan(0); // fixture guarantees repeats
  });
});

describe('mask: contains (TextInput — case-sensitive regex)', () => {
  it('anchored regex pattern', async () => {
    const r = await runMask([{ kind: 'contains', column: 'category_str', pattern: '^al' }]);
    check(r, 'contains_regex');
  });

  it('substring-style pattern', async () => {
    const r = await runMask([{ kind: 'contains', column: 'category_str', pattern: 'amma' }]);
    check(r, 'contains_sub');
  });

  it('is case-sensitive like polars str.contains', async () => {
    const { engine, handle } = await openFixture();
    const { matched } = await engine.mask(handle, [
      { kind: 'contains', column: 'category_str', pattern: '^AL' },
    ]);
    expect(matched).toBe(0);
  });
});

describe('mask: ts_range (date pickers via __ts__ companion, BigInt epoch-us)', () => {
  it('matches server (date >= start) & (date <= end)', async () => {
    const exp = expected.filters['ts_range'];
    const r = await runMask([
      {
        kind: 'ts_range',
        column: 'event_date',
        min: BigInt(exp['min_us'] as number),
        max: BigInt(exp['max_us'] as number),
      },
    ]);
    check(r, 'ts_range');
  });
});

describe('mask: link_no_match', () => {
  it('short-circuits to an all-false mask regardless of other filters', async () => {
    const r = await runMask([
      { kind: 'in', column: 'category_str', values: ['alpha'] },
      { kind: 'link_no_match' },
    ]);
    expect(r.matched).toBe(0);
    expect(r.value_f64_sum).toBe(0); // empty-selection sum on numeric = 0 (polars)
  });
});

describe('mask: missing-column skip (server per-filter skip)', () => {
  it('skips a filter on an absent column, keeps the rest', async () => {
    const r = await runMask([
      { kind: 'in', column: 'not_a_column', values: ['x'] },
      { kind: 'in', column: 'category_str', values: ['alpha', 'beta'] },
    ]);
    check(r, 'in_str'); // identical to the valid filter alone
  });

  it('skips a ts_range whose __ts__ companion is absent', async () => {
    const { engine, handle } = await openFixture();
    const { matched } = await engine.mask(handle, [
      { kind: 'ts_range', column: 'no_such_date', min: 0n, max: 1n },
    ]);
    expect(matched).toBe(expected.rows); // skipped -> no filtering at all
  });
});

describe('mask: null handling', () => {
  it('null never matches any predicate (all-null-excluding filters)', async () => {
    const { engine, handle } = await openFixture();
    // A predicate that would match "everything" still drops null rows.
    for (const [filter, column] of [
      [{ kind: 'range', column: 'value_f64' } as BoundFilter, 'value_f64'],
      [
        {
          kind: 'in',
          column: 'category_str',
          values: ['alpha', 'beta', 'gamma', 'delta', 'epsilon'],
        } as BoundFilter,
        'category_str',
      ],
      [{ kind: 'contains', column: 'category_str', pattern: '' } as BoundFilter, 'category_str'],
    ] as const) {
      const { matched } = await engine.mask(handle, [filter]);
      expect(matched, JSON.stringify(filter)).toBe(
        expected.rows - expected.null_counts[column],
      );
    }
  });
});

describe('mask: conjunction', () => {
  it('ANDs filters together like _apply_scan_filters', async () => {
    const r = await runMask([
      { kind: 'in', column: 'category_str', values: ['alpha', 'beta'] },
      { kind: 'range', column: 'value_f64', min: -0.5, max: 1.5 },
    ]);
    check(r, 'combo');
  });

  it('no filters -> all rows match', async () => {
    const { engine, handle } = await openFixture();
    const { mask, matched } = await engine.mask(handle, []);
    expect(matched).toBe(expected.rows);
    expect((mask as Bitmask).length).toBe(expected.rows);
  });
});
