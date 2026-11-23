/**
 * Parity of the sankey aggregation port with the post-load half of the
 * ``compute_sankey`` Celery task (``_sankey_result_from_frame``,
 * depictio/api/v1/celery_tasks.py). The expected values were produced by
 * calling the Python function on the same inputs
 * (scripts/generate_sankey_fixture.py → fixtures/sankey-expected.json):
 * row-count and weighted links, every sort mode, min_link_value, step
 * filters, the (missing) coercion of NULL / empty strings, dropped NULL
 * weights, option_cols wider than the steps and the dashboard-filter mask.
 * Numeric values are compared within 1e-9 — float sums may differ in the
 * last bits between polars and plain JS addition.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { sankeyFromColumns, type SankeyRequest } from '../src/sankey';

interface Fixture {
  columns: Record<string, unknown[]>;
  masks: Record<string, number[]>;
  cases: {
    name: string;
    request: SankeyRequest;
    mask: string | null;
    expected: Record<string, unknown>;
  }[];
}

const FIXTURE = JSON.parse(
  readFileSync(join(__dirname, '..', 'fixtures', 'sankey-expected.json'), 'utf-8'),
) as Fixture;
const N = FIXTURE.columns.stage1.length;

/** toEqual that lets numbers drift by up to 1e-9 (float sum order differs). */
function expectClose(actual: unknown, expected: unknown, path: string): void {
  if (typeof expected === 'number' && typeof actual === 'number') {
    expect(
      Math.abs(actual - expected),
      `${path}: ${actual} ≉ ${expected}`,
    ).toBeLessThanOrEqual(1e-9);
    return;
  }
  if (Array.isArray(expected)) {
    expect(actual, path).toBeInstanceOf(Array);
    const a = actual as unknown[];
    expect(a.length, `${path}.length`).toBe(expected.length);
    for (let i = 0; i < expected.length; i++) expectClose(a[i], expected[i], `${path}[${i}]`);
    return;
  }
  if (expected !== null && typeof expected === 'object') {
    // Exactly the server's shape: same keys, no extras on either side.
    const a = actual as Record<string, unknown>;
    const e = expected as Record<string, unknown>;
    expect(Object.keys(a).sort(), `${path} keys`).toEqual(Object.keys(e).sort());
    for (const k of Object.keys(e)) expectClose(a[k], e[k], `${path}.${k}`);
    return;
  }
  expect(actual, path).toBe(expected);
}

describe('sankeyFromColumns = _sankey_result_from_frame', () => {
  it.each(FIXTURE.cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    const mask = c.mask ? FIXTURE.masks[c.mask] : null;
    const out = sankeyFromColumns(FIXTURE.columns, N, mask, c.request);
    expectClose(out, c.expected, c.name);
  });
});

describe('request validation', () => {
  it('rejects fewer than two step columns', () => {
    expect(() =>
      sankeyFromColumns(FIXTURE.columns, N, null, { step_cols: ['stage1'] }),
    ).toThrow('step_cols must have ≥2 columns');
  });

  it('rejects a step column missing from the frame', () => {
    expect(() =>
      sankeyFromColumns(FIXTURE.columns, N, null, { step_cols: ['stage1', 'nope'] }),
    ).toThrow('column "nope" is not in the frame');
  });

  it('rejects a value column missing from the frame', () => {
    expect(() =>
      sankeyFromColumns(FIXTURE.columns, N, null, { step_cols: ['stage1', 'stage2'], value_col: 'nope' }),
    ).toThrow('column "nope" is not in the frame');
  });
});
