/**
 * Shared fixture loading for the engine tests.
 *
 * `fixtures/engine-fixture.parquet` + `fixtures/engine-expected.json` are
 * generated together by `scripts/generate_fixture.py` (run with the repo
 * venv's Polars — the server's version), so every expectation in these tests
 * is Polars-computed ground truth in the server's own predicate/agg forms.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import type { DataRef } from '../../src/manifest';
import { HyparquetEngine } from '../../src/engine/hyparquet/index';
import type { TableHandle } from '../../src/engine/QueryEngine';

const FIXTURES = join(__dirname, '..', '..', 'fixtures');

export interface ExpectedFilter {
  matched: number;
  value_f64_sum: number;
  [k: string]: unknown;
}

export interface Expected {
  rows: number;
  row_group_size: number;
  columns: Record<string, string>;
  null_counts: Record<string, number>;
  companions: Record<string, string>;
  codebooks: Record<string, Record<string, number>>;
  filters: Record<string, ExpectedFilter>;
  aggregates: Record<string, Record<string, Record<string, number | string | null>>>;
  unique: Record<string, string[]>;
  minmax: Record<string, [number | null, number | null]>;
  polars_version: string;
}

export const expected: Expected = JSON.parse(
  readFileSync(join(FIXTURES, 'engine-expected.json'), 'utf-8'),
);

export const parquetBytes: Uint8Array = new Uint8Array(
  readFileSync(join(FIXTURES, 'engine-fixture.parquet')),
);

/** DataRef mirroring what the bundle builder would emit for this table. */
export function fixtureRef(): DataRef {
  return {
    uri: 'inline:dc_fixture',
    rows: expected.rows,
    size_bytes: parquetBytes.byteLength,
    columns: Object.entries(expected.columns).map(([name, dtype]) => ({ name, dtype })),
    companions: expected.companions,
    codebooks: expected.codebooks,
    aggregation_hash: null,
  };
}

export async function openFixture(): Promise<{ engine: HyparquetEngine; handle: TableHandle }> {
  const engine = new HyparquetEngine();
  const handle = await engine.open(fixtureRef(), parquetBytes);
  return { engine, handle };
}

/** Float comparison at the spike-mandated 1e-9 relative tolerance. */
export function expectClose(actual: unknown, exp: number | string | null): void {
  if (exp === null || typeof exp === 'string') {
    if (actual !== exp) {
      throw new Error(`expected ${JSON.stringify(exp)}, got ${JSON.stringify(actual)}`);
    }
    return;
  }
  if (typeof actual !== 'number') {
    throw new Error(`expected number ${exp}, got ${JSON.stringify(actual)}`);
  }
  // Exact only for SAFE integers (counts etc.) — a huge float like 3.79e+23
  // is "integer" to Number.isInteger but differs across summation orders.
  if (Number.isSafeInteger(exp) && Number.isSafeInteger(actual)) {
    if (actual !== exp) throw new Error(`expected ${exp}, got ${actual}`);
    return;
  }
  const tol = 1e-9 * Math.max(1, Math.abs(exp));
  if (Math.abs(actual - exp) > tol) {
    throw new Error(`expected ${exp} ± ${tol}, got ${actual} (Δ=${Math.abs(actual - exp)})`);
  }
}
