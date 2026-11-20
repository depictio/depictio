/**
 * Prologue interpreter tests (RFC phase 6).
 *
 * Two layers:
 *   1. Hand-authored unit cases for every op and every predicate node, pinning
 *      the Polars 1.42.1 semantics verified empirically while writing the
 *      interpreter (Kleene logic, NaN total ordering, is_in null propagation,
 *      nulls-first sort, null group keys, agg-kernel traps, ...).
 *   2. A differential suite against the polars-generated fixture pair
 *      `fixtures/prologue-fixture.json` + `fixtures/prologue-expected.json`
 *      (produced by the Python transpiler side against the SAME pinned
 *      contract). It self-skips while the fixture has not landed yet.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import type { PrologueOp } from '../src/manifest';
import { runPrologue, type ColumnTable } from '../src/prologue';

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function table(columns: Record<string, unknown[]>): ColumnTable {
  const lengths = Object.values(columns).map((c) => c.length);
  return { columns, length: lengths[0] ?? 0 };
}

function run(ops: PrologueOp[], t: ColumnTable): ColumnTable {
  return runPrologue(ops, t);
}

const NAN = Number.NaN;

// ---------------------------------------------------------------------------
// filter — cmp
// ---------------------------------------------------------------------------

describe('filter: cmp', () => {
  const t = () => table({ x: [1, 2, 3, null, 0.5], tag: ['a', 'b', 'c', 'd', 'e'] });

  it('applies each comparison operator; null cells never pass', () => {
    const cases: [string, string[]][] = [
      ['<', ['a', 'e']],
      ['<=', ['a', 'b', 'e']],
      ['>', ['c']],
      ['>=', ['b', 'c']],
      ['==', ['b']],
      ['!=', ['a', 'c', 'e']],
    ];
    for (const [op, expected] of cases) {
      const out = run(
        [{ op: 'filter', pred: { cmp: { col: 'x', op: op as '<', value: 2 } } }],
        t(),
      );
      expect(out.columns['tag'], `op ${op}`).toEqual(expected);
      expect(out.length).toBe(expected.length);
    }
  });

  it('a null literal makes every row null → nothing passes', () => {
    const out = run([{ op: 'filter', pred: { cmp: { col: 'x', op: '==', value: null } } }], t());
    expect(out.length).toBe(0);
  });

  it('NaN follows Polars TOTAL float order: the greatest float, NaN == NaN true', () => {
    const tn = () => table({ x: [NAN, 1, Number.POSITIVE_INFINITY, null], tag: ['nan', 'one', 'inf', 'null'] });
    // Verified on Polars 1.42.1: x == NaN → [true, false, ...], x != NaN →
    // [false, true, ...], x < NaN → true for every non-NaN float (incl. +inf),
    // NaN <= x → false for any non-NaN x, NaN >= 0.5 → true.
    expect(run([{ op: 'filter', pred: { cmp: { col: 'x', op: '==', value: NAN } } }], tn()).columns['tag']).toEqual(['nan']);
    expect(run([{ op: 'filter', pred: { cmp: { col: 'x', op: '!=', value: NAN } } }], tn()).columns['tag']).toEqual(['one', 'inf']);
    expect(run([{ op: 'filter', pred: { cmp: { col: 'x', op: '<', value: NAN } } }], tn()).columns['tag']).toEqual(['one', 'inf']);
    expect(run([{ op: 'filter', pred: { cmp: { col: 'x', op: '>=', value: 0.5 } } }], tn()).columns['tag']).toEqual(['nan', 'one', 'inf']);
    expect(run([{ op: 'filter', pred: { cmp: { col: 'x', op: '<=', value: Number.POSITIVE_INFINITY } } }], tn()).columns['tag']).toEqual(['one', 'inf']);
  });

  it('compares strings by code point and booleans as false < true', () => {
    const ts = table({ s: ['apple', 'banana', null, 'cherry'] });
    const out = run([{ op: 'filter', pred: { cmp: { col: 's', op: '<', value: 'banana' } } }], ts);
    expect(out.columns['s']).toEqual(['apple']);
    const tb = table({ b: [true, false, null] });
    const outB = run([{ op: 'filter', pred: { cmp: { col: 'b', op: '>', value: false } } }], tb);
    expect(outB.columns['b']).toEqual([true]);
  });

  it('matches bigint cells against number literals exactly', () => {
    const tb = table({ n: [1n, 2n, 3n, null] });
    const out = run([{ op: 'filter', pred: { cmp: { col: 'n', op: '>=', value: 2 } } }], tb);
    expect(out.columns['n']).toEqual([2n, 3n]);
  });

  it('throws on cross-dtype comparison (polars raises too)', () => {
    const ts = table({ s: ['a', 'b'] });
    expect(() => run([{ op: 'filter', pred: { cmp: { col: 's', op: '<', value: 5 } } }], ts)).toThrow(
      /incompatible types/,
    );
  });
});

// ---------------------------------------------------------------------------
// filter — null tests, is_in, Kleene combinators
// ---------------------------------------------------------------------------

describe('filter: is_null / is_not_null / is_in', () => {
  const t = () => table({ x: [1, null, 3, null], tag: ['a', 'b', 'c', 'd'] });

  it('is_null / is_not_null partition the rows (never null-valued)', () => {
    expect(run([{ op: 'filter', pred: { is_null: { col: 'x' } } }], t()).columns['tag']).toEqual(['b', 'd']);
    expect(run([{ op: 'filter', pred: { is_not_null: { col: 'x' } } }], t()).columns['tag']).toEqual(['a', 'c']);
  });

  it('is_in matches membership; a null cell yields null (fails), even with null in the list', () => {
    const out = run([{ op: 'filter', pred: { is_in: { col: 'x', values: [1, 3] } } }], t());
    expect(out.columns['tag']).toEqual(['a', 'c']);
    // Verified on 1.42.1: [1, None].is_in([1, None]) → [true, null].
    const withNull = run([{ op: 'filter', pred: { is_in: { col: 'x', values: [1, null] } } }], t());
    expect(withNull.columns['tag']).toEqual(['a']);
  });

  it('is_in null propagation is visible under NOT: not(null) = null still fails', () => {
    const out = run(
      [{ op: 'filter', pred: { not: { is_in: { col: 'x', values: [1] } } } }],
      t(),
    );
    // Row b/d have null cells: is_in → null, not → null → row fails.
    expect(out.columns['tag']).toEqual(['c']);
  });

  it('is_in never matches across dtypes (string "1" is not number 1)', () => {
    const ts = table({ s: ['1', '2'] });
    const out = run([{ op: 'filter', pred: { is_in: { col: 's', values: [1] } } }], ts);
    expect(out.length).toBe(0);
  });
});

describe('filter: Kleene three-valued logic', () => {
  // x: null on rows 1,3 — cmp(x > 0) is null there.
  const t = () => table({ x: [1, null, -1, null], flag: [true, true, true, false], tag: ['a', 'b', 'c', 'd'] });
  const xPos = { cmp: { col: 'x', op: '>' as const, value: 0 } };
  const flagTrue = { cmp: { col: 'flag', op: '==' as const, value: true } };
  const flagFalse = { cmp: { col: 'flag', op: '==' as const, value: false } };

  it('null AND false = false; null AND true = null (row fails either way, but NOT distinguishes)', () => {
    // not(null AND false) = not(false) = true → null-x rows PASS when flag is false.
    const out = run([{ op: 'filter', pred: { not: { and: [xPos, flagTrue] } } }], t());
    // a: not(true and true)=false; b: not(null and true)=not(null)=null;
    // c: not(false and true)=true; d: not(null and false)=not(false)=true.
    expect(out.columns['tag']).toEqual(['c', 'd']);
  });

  it('null OR true = true; null OR false = null', () => {
    const out = run([{ op: 'filter', pred: { or: [xPos, flagTrue] } }], t());
    // a: true|true=true; b: null|true=true; c: false|true=true; d: null|false=null.
    expect(out.columns['tag']).toEqual(['a', 'b', 'c']);
  });

  it('NOT null = null (a bare negated null never passes)', () => {
    const out = run([{ op: 'filter', pred: { not: xPos } }], t());
    expect(out.columns['tag']).toEqual(['c']);
  });

  it('nested combinators evaluate Kleene all the way down', () => {
    const out = run(
      [{ op: 'filter', pred: { and: [{ or: [xPos, flagFalse] }, { not: { is_null: { col: 'x' } } }] } }],
      t(),
    );
    // a: (true|false)&true=true; b: (null|false)&false=false;
    // c: (false|false)&true=false; d: (null|true)&false=false.
    expect(out.columns['tag']).toEqual(['a']);
  });

  it('empty and/or use identity semantics (and=true, or=false)', () => {
    expect(run([{ op: 'filter', pred: { and: [] } }], t()).length).toBe(4);
    expect(run([{ op: 'filter', pred: { or: [] } }], t()).length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// unpivot
// ---------------------------------------------------------------------------

describe('unpivot', () => {
  const t = () =>
    table({ id: [1, 2], group: ['x', 'y'], A: [10, 20], B: [30, 40], junk: [0, 0] });

  it('emits one block per on-column in on order, index repeated, variable = column NAME', () => {
    const out = run(
      [{ op: 'unpivot', on: ['A', 'B'], index: ['id', 'group'], variable: 'metric', value: 'value' }],
      t(),
    );
    // Verified against pl.DataFrame.unpivot on 1.42.1.
    expect(Object.keys(out.columns)).toEqual(['id', 'group', 'metric', 'value']);
    expect(out.length).toBe(4);
    expect(out.columns['id']).toEqual([1, 2, 1, 2]);
    expect(out.columns['group']).toEqual(['x', 'y', 'x', 'y']);
    expect(out.columns['metric']).toEqual(['A', 'A', 'B', 'B']);
    expect(out.columns['value']).toEqual([10, 20, 30, 40]);
  });

  it('drops columns not named in on/index (the junk column disappears)', () => {
    const out = run(
      [{ op: 'unpivot', on: ['A'], index: ['id'], variable: 'm', value: 'v' }],
      t(),
    );
    expect(Object.keys(out.columns)).toEqual(['id', 'm', 'v']);
  });

  it('empty table unpivots to an empty table with the right columns', () => {
    const out = run(
      [{ op: 'unpivot', on: ['A', 'B'], index: ['id'], variable: 'm', value: 'v' }],
      table({ id: [], A: [], B: [] }),
    );
    expect(out.length).toBe(0);
    expect(Object.keys(out.columns)).toEqual(['id', 'm', 'v']);
  });

  it('throws on a missing on/index column and on output-name collisions', () => {
    expect(() =>
      run([{ op: 'unpivot', on: ['nope'], index: ['id'], variable: 'm', value: 'v' }], t()),
    ).toThrow(/missing column "nope"/);
    expect(() =>
      run([{ op: 'unpivot', on: ['A'], index: ['id'], variable: 'id', value: 'v' }], t()),
    ).toThrow(/duplicate column "id"/);
  });
});

// ---------------------------------------------------------------------------
// group_by
// ---------------------------------------------------------------------------

describe('group_by', () => {
  it('keeps first-appearance group order (maintain_order=True)', () => {
    const t = table({ k: ['b', 'a', 'b', 'c', 'a'], v: [1, 2, 3, 4, 5] });
    const out = run(
      [{ op: 'group_by', by: ['k'], agg: [{ col: 'v', fn: 'sum', alias: 'v' }] }],
      t,
    );
    expect(out.columns['k']).toEqual(['b', 'a', 'c']);
    expect(out.columns['v']).toEqual([4, 7, 4]);
    expect(out.length).toBe(3);
  });

  it('a null key forms its own group (verified group order/content on 1.42.1)', () => {
    const t = table({ k: ['b', null, 'a', null, 'b'], v: [1, 2, 3, 4, 5] });
    const out = run(
      [{ op: 'group_by', by: ['k'], agg: [{ col: 'v', fn: 'sum', alias: 'v' }] }],
      t,
    );
    expect(out.columns['k']).toEqual(['b', null, 'a']);
    expect(out.columns['v']).toEqual([6, 6, 3]);
  });

  it('composite keys compare element-wise with null == null', () => {
    const t = table({ k1: [null, null, 'a'], k2: [1, 1, null], v: [1, 2, 3] });
    const out = run(
      [{ op: 'group_by', by: ['k1', 'k2'], agg: [{ col: 'v', fn: 'sum', alias: 'v' }] }],
      t,
    );
    expect(out.columns['k1']).toEqual([null, 'a']);
    expect(out.columns['k2']).toEqual([1, null]);
    expect(out.columns['v']).toEqual([3, 3]);
  });

  it('NaN keys group together (polars groups NaN with NaN)', () => {
    const t = table({ k: [NAN, NAN, 1], v: [1, 2, 3] });
    const out = run(
      [{ op: 'group_by', by: ['k'], agg: [{ col: 'v', fn: 'sum', alias: 'v' }] }],
      t,
    );
    expect(out.length).toBe(2);
    expect(out.columns['v']).toEqual([3, 3]);
  });

  it('pins the agg-kernel traps per group: all-null sum→0/mean→null, std single→null, nunique counts null, first/last positional, median interpolates', () => {
    const t = table({
      k: ['a', 'a', 'b', 'b', 'b', 'c', 'c'],
      v: [null, null, 1, null, 1, 2, 4],
    });
    const out = run(
      [
        {
          op: 'group_by',
          by: ['k'],
          agg: [
            { col: 'v', fn: 'sum', alias: 'sum' },
            { col: 'v', fn: 'mean', alias: 'mean' },
            { col: 'v', fn: 'count', alias: 'count' },
            { col: 'v', fn: 'nunique', alias: 'nunique' },
            { col: 'v', fn: 'std', alias: 'std' },
            { col: 'v', fn: 'var', alias: 'var' },
            { col: 'v', fn: 'first', alias: 'first' },
            { col: 'v', fn: 'last', alias: 'last' },
            { col: 'v', fn: 'min', alias: 'min' },
            { col: 'v', fn: 'max', alias: 'max' },
            { col: 'v', fn: 'median', alias: 'median' },
          ],
        },
      ],
      t,
    );
    // group a: all-null; group b: [1, null, 1]; group c: [2, 4].
    expect(out.columns['sum']).toEqual([0, 2, 6]); // all-null NUMERIC sum → 0 (polars)
    expect(out.columns['mean']).toEqual([null, 1, 3]);
    expect(out.columns['count']).toEqual([0, 2, 2]); // non-null count
    expect(out.columns['nunique']).toEqual([1, 2, 2]); // null IS a distinct value
    expect(out.columns['std']).toEqual([null, 0, Math.sqrt(2)]);
    expect(out.columns['var']).toEqual([null, 0, 2]);
    expect(out.columns['first']).toEqual([null, 1, 2]); // positional, nulls included
    expect(out.columns['last']).toEqual([null, 1, 4]);
    expect(out.columns['min']).toEqual([null, 1, 2]);
    expect(out.columns['max']).toEqual([null, 1, 4]);
    expect(out.columns['median']).toEqual([null, 1, 3]); // (2+4)/2 linear interpolation
  });

  it('len is the GROUP SIZE (nulls included) while count is the non-null count', () => {
    // Verified on polars 1.42.1: group_by(k).agg(pl.len(), pl.col('v').count(),
    // pl.col('v').len()) over this frame → len [2,2,1], count [1,0,1], len(v)
    // [2,2,1]; the null key forms its own group and is counted like any other.
    const t = table({ k: ['a', 'a', null, null, 'b'], v: [1, null, null, null, 5] });
    const out = run(
      [
        {
          op: 'group_by',
          by: ['k'],
          agg: [
            { fn: 'len', alias: 'n_rows' }, // bare pl.len() — no source column
            { col: null, fn: 'len', alias: 'n_rows_explicit_null' }, // pl.count()
            { col: 'v', fn: 'len', alias: 'n_rows_via_col' }, // pl.col('v').len()
            { col: 'v', fn: 'count', alias: 'n_v' },
            { col: 'v', fn: 'nunique', alias: 'u_v' },
          ],
        },
      ],
      t,
    );
    expect(out.columns['k']).toEqual(['a', null, 'b']);
    expect(out.columns['n_rows']).toEqual([2, 2, 1]);
    expect(out.columns['n_rows_explicit_null']).toEqual([2, 2, 1]);
    expect(out.columns['n_rows_via_col']).toEqual([2, 2, 1]);
    expect(out.columns['n_v']).toEqual([1, 0, 1]); // non-null count differs
    expect(out.columns['u_v']).toEqual([2, 1, 1]); // nunique counts null
  });

  it('len counts only the rows that survived an earlier filter', () => {
    const t = table({ k: ['a', 'a', 'a', 'b'], v: [1, 5, null, 9] });
    const out = run(
      [
        { op: 'filter', pred: { cmp: { col: 'v', op: '>', value: 2 } } },
        { op: 'group_by', by: ['k'], agg: [{ fn: 'len', alias: 'n' }] },
      ],
      t,
    );
    expect(out.columns['k']).toEqual(['a', 'b']);
    expect(out.columns['n']).toEqual([1, 1]);
  });

  it('len still validates a present col (polars raises on a missing column)', () => {
    const t = table({ k: ['a'], v: [1] });
    expect(() =>
      run([{ op: 'group_by', by: ['k'], agg: [{ col: 'nope', fn: 'len', alias: 'n' }] }], t),
    ).toThrow(/missing column "nope"/);
  });

  it('every fn other than len requires a source column', () => {
    const t = table({ k: ['a'], v: [1] });
    expect(() =>
      run(
        [
          {
            op: 'group_by',
            by: ['k'],
            agg: [{ fn: 'sum', alias: 'n' } as unknown as { col: string; fn: 'sum'; alias: string }],
          },
        ],
        t,
      ),
    ).toThrow(/agg fn "sum" needs a source column/);
  });

  it('std of a single-value group is null (ddof=1)', () => {
    const t = table({ k: ['a'], v: [5] });
    const out = run(
      [{ op: 'group_by', by: ['k'], agg: [{ col: 'v', fn: 'std', alias: 'std' }] }],
      t,
    );
    expect(out.columns['std']).toEqual([null]);
  });

  it('an empty table yields zero groups', () => {
    const t = table({ k: [], v: [] });
    const out = run(
      [{ op: 'group_by', by: ['k'], agg: [{ col: 'v', fn: 'sum', alias: 'v' }] }],
      t,
    );
    expect(out.length).toBe(0);
    expect(out.columns['k']).toEqual([]);
    expect(out.columns['v']).toEqual([]);
  });

  it('output columns are by-columns then aliases, in spec order', () => {
    const t = table({ k: ['a'], v: [1], w: [2] });
    const out = run(
      [
        {
          op: 'group_by',
          by: ['k'],
          agg: [
            { col: 'w', fn: 'sum', alias: 'w_sum' },
            { col: 'v', fn: 'mean', alias: 'v_mean' },
          ],
        },
      ],
      t,
    );
    expect(Object.keys(out.columns)).toEqual(['k', 'w_sum', 'v_mean']);
  });

  it('throws on unknown fn (mode is NOT in the prologue allowlist), missing column, alias collision', () => {
    const t = table({ k: ['a'], v: [1] });
    expect(() =>
      run([{ op: 'group_by', by: ['k'], agg: [{ col: 'v', fn: 'mode' as 'sum', alias: 'v' }] }], t),
    ).toThrow(/unknown agg fn "mode"/);
    expect(() =>
      run([{ op: 'group_by', by: ['k'], agg: [{ col: 'nope', fn: 'sum', alias: 'v' }] }], t),
    ).toThrow(/missing column "nope"/);
    expect(() =>
      run([{ op: 'group_by', by: ['k'], agg: [{ col: 'v', fn: 'sum', alias: 'k' }] }], t),
    ).toThrow(/duplicate column "k"/);
  });
});

// ---------------------------------------------------------------------------
// sort
// ---------------------------------------------------------------------------

describe('sort', () => {
  it('places nulls FIRST in both directions (polars nulls_last=False default)', () => {
    const t = table({ a: [2, null, 1], tag: ['x', 'y', 'z'] });
    const asc = run([{ op: 'sort', by: ['a'], desc: [false] }], t);
    expect(asc.columns['tag']).toEqual(['y', 'z', 'x']);
    const desc = run([{ op: 'sort', by: ['a'], desc: [true] }], t);
    expect(desc.columns['tag']).toEqual(['y', 'x', 'z']);
  });

  it('NaN is the greatest float and DOES reverse with desc (unlike nulls)', () => {
    const t = table({ a: [2, null, 1, NAN] });
    expect(run([{ op: 'sort', by: ['a'], desc: [false] }], t).columns['a']).toEqual([null, 1, 2, NAN]);
    expect(run([{ op: 'sort', by: ['a'], desc: [true] }], t).columns['a']).toEqual([null, NAN, 2, 1]);
  });

  it('is stable: ties preserve input order', () => {
    const t = table({ a: [1, 1, 1], tag: ['r1', 'r2', 'r3'] });
    expect(run([{ op: 'sort', by: ['a'], desc: [true] }], t).columns['tag']).toEqual(['r1', 'r2', 'r3']);
  });

  it('multi-key with per-key direction, nulls first on every key (verified on 1.42.1)', () => {
    const t = table({ a: [1, 1, 2, null], b: [null, 5, 3, 9] });
    const out = run([{ op: 'sort', by: ['a', 'b'], desc: [false, true] }], t);
    expect(out.columns['a']).toEqual([null, 1, 1, 2]);
    expect(out.columns['b']).toEqual([9, null, 5, 3]);
  });

  it('sorts strings by code point (never localeCompare)', () => {
    // U+FF01 (BMP) vs U+1D538 (supplementary): code-point order puts U+FF01 first.
    const t = table({ s: ['\u{1D538}', '！', 'a'] });
    const out = run([{ op: 'sort', by: ['s'], desc: [false] }], t);
    expect(out.columns['s']).toEqual(['a', '！', '\u{1D538}']);
  });

  it('throws on a missing sort column (polars ColumnNotFoundError — no silent drop here)', () => {
    const t = table({ a: [1] });
    expect(() => run([{ op: 'sort', by: ['nope'], desc: [false] }], t)).toThrow(/missing column "nope"/);
  });

  it('throws when desc does not pair with by', () => {
    const t = table({ a: [1], b: [2] });
    expect(() => run([{ op: 'sort', by: ['a', 'b'], desc: [true] }], t)).toThrow(/"desc"/);
  });
});

// ---------------------------------------------------------------------------
// rename
// ---------------------------------------------------------------------------

describe('rename', () => {
  it('renames in place, preserving column order', () => {
    const t = table({ a: [1], b: [2], c: [3] });
    const out = run([{ op: 'rename', map: { b: 'B' } }], t);
    expect(Object.keys(out.columns)).toEqual(['a', 'B', 'c']);
    expect(out.columns['B']).toEqual([2]);
  });

  it('supports swaps (polars allows a↔b)', () => {
    const t = table({ a: [1], b: [2] });
    const out = run([{ op: 'rename', map: { a: 'b', b: 'a' } }], t);
    expect(Object.keys(out.columns)).toEqual(['b', 'a']);
    expect(out.columns['b']).toEqual([1]);
    expect(out.columns['a']).toEqual([2]);
  });

  it('throws on a missing key and on a resulting duplicate', () => {
    const t = table({ a: [1], b: [2] });
    expect(() => run([{ op: 'rename', map: { zzz: 'c' } }], t)).toThrow(/missing column "zzz"/);
    expect(() => run([{ op: 'rename', map: { a: 'b' } }], t)).toThrow(/duplicate column "b"/);
  });
});

// ---------------------------------------------------------------------------
// pipeline behavior
// ---------------------------------------------------------------------------

describe('runPrologue pipeline', () => {
  it('chains ops (unpivot → filter → group_by → sort → rename) end to end', () => {
    const t = table({
      id: [1, 2, 3],
      habitat: ['sea', 'land', 'sea'],
      weight: [10, 20, 30],
      height: [1, 2, null],
    });
    const out = run(
      [
        { op: 'unpivot', on: ['weight', 'height'], index: ['id', 'habitat'], variable: 'metric', value: 'value' },
        { op: 'filter', pred: { is_not_null: { col: 'value' } } },
        { op: 'group_by', by: ['habitat'], agg: [{ col: 'value', fn: 'mean', alias: 'value' }] },
        { op: 'sort', by: ['value'], desc: [true] },
        { op: 'rename', map: { habitat: 'where' } },
      ],
      t,
    );
    // sea: weight 10,30 + height 1 → mean 41/3; land: 20 + 2 → 11.
    expect(Object.keys(out.columns)).toEqual(['where', 'value']);
    expect(out.columns['where']).toEqual(['sea', 'land']);
    expect(out.columns['value'][0]).toBeCloseTo(41 / 3, 12);
    expect(out.columns['value'][1]).toBe(11);
  });

  it('an empty ops list returns the table unchanged', () => {
    const t = table({ a: [1, 2] });
    expect(run([], t)).toBe(t);
  });

  it('never mutates the input table', () => {
    const columns = { k: ['b', 'a'], v: [1, 2] };
    const t = table(columns);
    run(
      [
        { op: 'filter', pred: { cmp: { col: 'v', op: '>', value: 0 } } },
        { op: 'sort', by: ['k'], desc: [false] },
        { op: 'rename', map: { k: 'kk' } },
      ],
      t,
    );
    expect(t.columns).toBe(columns);
    expect(columns['k']).toEqual(['b', 'a']);
    expect(columns['v']).toEqual([1, 2]);
  });

  it('throws descriptively on malformed input', () => {
    const t = table({ a: [1] });
    expect(() => run([{ op: 'pivot' } as unknown as PrologueOp], t)).toThrow(/unknown op "pivot"/);
    expect(() => run([{ op: 'filter' } as unknown as PrologueOp], t)).toThrow(/missing "pred"/);
    expect(() =>
      run([{ op: 'filter', pred: { nope: {} } as unknown as PrologueOp } as unknown as PrologueOp], t),
    ).toThrow(/unknown predicate kind/);
    expect(() => runPrologue([], { columns: { a: [1, 2] }, length: 3 })).toThrow(/table\.length/);
  });

  it('runs every op over an empty table without error', () => {
    const t = table({ k: [], v: [] });
    const out = run(
      [
        { op: 'filter', pred: { cmp: { col: 'v', op: '<', value: 1 } } },
        { op: 'sort', by: ['k'], desc: [false] },
        { op: 'rename', map: { v: 'value' } },
      ],
      t,
    );
    expect(out.length).toBe(0);
    expect(Object.keys(out.columns)).toEqual(['k', 'value']);
  });
});

// ---------------------------------------------------------------------------
// differential suite vs. the polars-generated fixture (skips until it lands)
// ---------------------------------------------------------------------------

const FIXTURES = join(__dirname, '..', 'fixtures');
const FIXTURE_PATH = join(FIXTURES, 'prologue-fixture.json');
const EXPECTED_PATH = join(FIXTURES, 'prologue-expected.json');
const fixturePresent = existsSync(FIXTURE_PATH) && existsSync(EXPECTED_PATH);

interface PrologueFixture {
  input: { columns: Record<string, unknown[]> };
  cases: { name: string; ops: PrologueOp[] }[];
}

interface PrologueExpected {
  cases: { name: string; output: { columns: Record<string, unknown[]>; length: number } }[];
}

/** 1e-9 relative float tolerance (same bar as the engine differential suite). */
function expectCellClose(actual: unknown, exp: unknown, ctx: string): void {
  if (typeof exp === 'number' && typeof actual === 'number') {
    if (Number.isNaN(exp)) {
      expect(Number.isNaN(actual), `${ctx}: expected NaN, got ${actual}`).toBe(true);
      return;
    }
    if (Number.isSafeInteger(exp) && Number.isSafeInteger(actual)) {
      expect(actual, ctx).toBe(exp);
      return;
    }
    const tol = 1e-9 * Math.max(1, Math.abs(exp));
    expect(Math.abs(actual - exp), `${ctx}: expected ${exp} ± ${tol}, got ${actual}`).toBeLessThanOrEqual(tol);
    return;
  }
  expect(actual, ctx).toStrictEqual(exp);
}

describe.skipIf(!fixturePresent)('differential: runPrologue vs polars-generated fixture', () => {
  const fixture: PrologueFixture = fixturePresent
    ? JSON.parse(readFileSync(FIXTURE_PATH, 'utf-8'))
    : { input: { columns: {} }, cases: [] };
  const expectedFile: PrologueExpected = fixturePresent
    ? JSON.parse(readFileSync(EXPECTED_PATH, 'utf-8'))
    : { cases: [] };
  const expectedByName = new Map(expectedFile.cases.map((c) => [c.name, c.output]));

  it('covers every fixture case with an expectation', () => {
    for (const c of fixture.cases) {
      expect(expectedByName.has(c.name), `expected output missing for case "${c.name}"`).toBe(true);
    }
  });

  for (const c of fixturePresent ? fixture.cases : []) {
    it(`case: ${c.name}`, () => {
      const exp = expectedByName.get(c.name);
      expect(exp, `no expected output for "${c.name}"`).toBeDefined();
      if (!exp) return;
      const inputCols = fixture.input.columns;
      const names = Object.keys(inputCols);
      const length = names.length > 0 ? inputCols[names[0]].length : 0;
      // Fresh deep copy per case — runPrologue must not need a pristine input,
      // but a shared fixture object must never leak state between cases.
      const input: ColumnTable = {
        columns: JSON.parse(JSON.stringify(inputCols)),
        length,
      };
      const out = runPrologue(c.ops, input);
      expect(out.length, `${c.name}: length`).toBe(exp.length);
      expect(Object.keys(out.columns).sort(), `${c.name}: column set`).toEqual(
        Object.keys(exp.columns).sort(),
      );
      for (const [col, expValues] of Object.entries(exp.columns)) {
        const actual = out.columns[col];
        expect(actual.length, `${c.name}.${col}: column length`).toBe(expValues.length);
        for (let i = 0; i < expValues.length; i++) {
          expectCellClose(actual[i], expValues[i], `${c.name}.${col}[${i}]`);
        }
      }
    });
  }
});
