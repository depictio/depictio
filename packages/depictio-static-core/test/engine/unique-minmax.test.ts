/**
 * unique() and minMax() vs. the server contracts:
 * - unique: deltatables routes.py get_unique_values:687-689 — drop nulls,
 *   stringify, dedupe, sort lexicographically.
 * - minMax: numeric, null-safe.
 */

import { describe, expect, it } from 'vitest';

import { expected, openFixture } from './helpers';

describe('unique', () => {
  it('returns sorted stringified non-null values (String column)', async () => {
    const { engine, handle } = await openFixture();
    const values = await engine.unique(handle, null, 'category_str');
    expect(values).toEqual(expected.unique['category_str_full']);
  });

  it('stringifies non-String columns exactly like the server (str(v))', async () => {
    const { engine, handle } = await openFixture();
    const values = await engine.unique(handle, null, 'batch');
    // Int64 -> BigInt -> "1".."5", matching Python str(int).
    expect(values).toEqual(expected.unique['batch_full']);
  });

  it('respects the mask', async () => {
    const { engine, handle } = await openFixture();
    const { mask } = await engine.mask(handle, [
      { kind: 'range', column: 'value_f64', min: -0.5, max: 1.5 },
    ]);
    const values = await engine.unique(handle, mask, 'category_str');
    expect(values).toEqual(expected.unique['category_str_masked_range_f64']);
  });

  it('empty mask -> empty list', async () => {
    const { engine, handle } = await openFixture();
    const values = await engine.unique(handle, new Uint8Array(expected.rows), 'category_str');
    expect(values).toEqual([]);
  });
});

describe('minMax', () => {
  it('matches Polars min/max on Float64', async () => {
    const { engine, handle } = await openFixture();
    const [min, max] = await engine.minMax(handle, null, 'value_f64');
    expect(min).toBe(expected.minmax['value_f64_full'][0]);
    expect(max).toBe(expected.minmax['value_f64_full'][1]);
  });

  it('matches Polars min/max on Int64 (BigInt decoded, float returned)', async () => {
    const { engine, handle } = await openFixture();
    const [min, max] = await engine.minMax(handle, null, 'value_i64');
    expect(min).toBe(expected.minmax['value_i64_full'][0]);
    expect(max).toBe(expected.minmax['value_i64_full'][1]);
  });

  it('respects the mask', async () => {
    const { engine, handle } = await openFixture();
    const { mask } = await engine.mask(handle, [
      { kind: 'in', column: 'category_str', values: ['alpha', 'beta'] },
    ]);
    const [min, max] = await engine.minMax(handle, mask, 'value_f64');
    expect(min).toBe(expected.minmax['value_f64_masked_in_str'][0]);
    expect(max).toBe(expected.minmax['value_f64_masked_in_str'][1]);
  });

  it('empty mask -> [null, null]', async () => {
    const { engine, handle } = await openFixture();
    const result = await engine.minMax(handle, new Uint8Array(expected.rows), 'value_f64');
    expect(result).toEqual(expected.minmax['empty']);
  });

  it('non-numeric column -> [null, null]', async () => {
    const { engine, handle } = await openFixture();
    const result = await engine.minMax(handle, null, 'category_str');
    expect(result).toEqual([null, null]);
  });
});
