import { describe, expect, it } from 'vitest';

import { expected, openFixture } from './helpers';

describe('HyparquetEngine decode round-trip', () => {
  it('reads the row count from metadata', async () => {
    const { handle } = await openFixture();
    expect((handle as { rows?: number }).rows).toBe(expected.rows);
  });

  it('decodes every column at full table length', async () => {
    const { engine, handle } = await openFixture();
    const names = Object.keys(expected.columns);
    const batch = await engine.columns(handle, names);
    for (const name of names) {
      expect(batch[name].length, name).toBe(expected.rows);
    }
  });

  it('preserves typed arrays across row-group concat (REQUIRED+PLAIN columns)', async () => {
    const { engine, handle } = await openFixture();
    const batch = await engine.columns(handle, ['idx_i32', 'metric_f64_nn']);
    // 4 row groups of Int32Array/Float64Array chunks concatenated into one
    // typed array each (spike §3 kernel-input shape).
    expect(batch['idx_i32']).toBeInstanceOf(Int32Array);
    expect(batch['metric_f64_nn']).toBeInstanceOf(Float64Array);
    expect(batch['idx_i32'].length).toBe(expected.rows);
    // Value fidelity across the row-group boundaries (row 600 starts group 2).
    const idx = batch['idx_i32'] as Int32Array;
    const metric = batch['metric_f64_nn'] as Float64Array;
    for (const i of [0, 599, 600, 1799, 1800, expected.rows - 1]) {
      expect(idx[i], `idx_i32[${i}]`).toBe(i);
      expect(metric[i], `metric_f64_nn[${i}]`).toBeCloseTo(i * 0.25 - 100.0, 9);
    }
  });

  it('falls back to plain arrays for null-carrying and String columns', async () => {
    const { engine, handle } = await openFixture();
    const batch = await engine.columns(handle, [
      'value_f64',
      '__code__batch',
      '__ts__event_date',
      'category_str',
    ]);
    // Nulls (and dictionary-encoded strings) force the plain-Array
    // representation with null entries (spike §3 gotcha).
    for (const name of ['value_f64', '__code__batch', '__ts__event_date', 'category_str']) {
      expect(Array.isArray(batch[name]), name).toBe(true);
    }
    // Dtype fidelity: numbers for f64/Int32 code, BigInt for Int64 __ts__,
    // strings for the String column.
    const firstNonNull = (col: ArrayLike<unknown>) => {
      for (let i = 0; i < col.length; i++) if (col[i] != null) return col[i];
      return undefined;
    };
    expect(typeof firstNonNull(batch['value_f64'])).toBe('number');
    expect(typeof firstNonNull(batch['__code__batch'])).toBe('number');
    expect(typeof firstNonNull(batch['__ts__event_date'])).toBe('bigint');
    expect(typeof firstNonNull(batch['category_str'])).toBe('string');
  });

  it('round-trips null counts per column', async () => {
    const { engine, handle } = await openFixture();
    const names = Object.keys(expected.columns).filter((n) => n !== 'event_date');
    const batch = await engine.columns(handle, names);
    for (const name of names) {
      const col = batch[name];
      let nulls = 0;
      for (let i = 0; i < col.length; i++) if (col[i] == null) nulls++;
      expect(nulls, name).toBe(expected.null_counts[name]);
    }
  });

  it('caches decoded columns (second read returns the same object)', async () => {
    const { engine, handle } = await openFixture();
    const a = await engine.columns(handle, ['value_f64']);
    const b = await engine.columns(handle, ['value_f64']);
    expect(b['value_f64']).toBe(a['value_f64']);
  });

  it('opens from a Uint8Array view into a larger buffer', async () => {
    const { engine } = await openFixture();
    const { parquetBytes, fixtureRef } = await import('./helpers');
    const arena = new Uint8Array(parquetBytes.byteLength + 32);
    arena.set(parquetBytes, 16);
    const view = arena.subarray(16, 16 + parquetBytes.byteLength);
    const handle = await engine.open(fixtureRef(), view);
    const batch = await engine.columns(handle, ['value_f64']);
    expect(batch['value_f64'].length).toBe(expected.rows);
  });

  it('rejects a column that is not in the table', async () => {
    const { engine, handle } = await openFixture();
    await expect(engine.columns(handle, ['nope'])).rejects.toThrow(/not in table/);
  });
});
