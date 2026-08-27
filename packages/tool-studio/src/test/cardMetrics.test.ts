/**
 * Pins the TypeScript card-metrics port against the real Python.
 *
 * `scripts/card_metrics_golden.py` runs depictio's own `card_metrics` /
 * `card_breakdown` over `e2e/golden/card_metrics.csv` and writes
 * `generated/cardMetricsGolden.json`; everything below recomputes the same
 * cases in the browser code and asserts they match. The fixture is adversarial
 * on purpose — nulls, a duplicated id, an outlier, a 30-value date axis (which
 * forces trend's bucketing branch) and a 6-value integer axis (which does not).
 *
 * Regenerate with `pnpm --filter tool-studio genkinds`; CI runs it with
 * TOOL_STUDIO_STRICT_GEN=1 and diffs the result, so the golden cannot silently
 * drift away from the server.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { parseFixture } from '../catalog/parseFixture';
import { aggregate } from '../api/aggregations';
import { buildFrame } from '../api/frame';
import { computeBreakdown, numericLayoutPayload } from '../api/cardMetrics';
import golden from './generated/cardMetricsGolden.json';

const raw = readFileSync(
  resolve(__dirname, '..', '..', 'e2e', 'golden', golden.fixture),
  'utf8',
);
const frame = buildFrame(parseFixture(golden.fixture, raw));

/** Doubles summed in a different order differ in the last bits, and polars
 *  does not promise row order in its reductions. Compare numerically with a
 *  relative tolerance and everything else exactly. */
function expectSame(actual: unknown, expected: unknown, path: string): void {
  if (typeof expected === 'number' && typeof actual === 'number') {
    const scale = Math.max(1, Math.abs(expected));
    expect(Math.abs(actual - expected) / scale, path).toBeLessThan(1e-9);
    return;
  }
  if (Array.isArray(expected)) {
    expect(Array.isArray(actual), path).toBe(true);
    expect((actual as unknown[]).length, `${path}.length`).toBe(expected.length);
    expected.forEach((item, i) => expectSame((actual as unknown[])[i], item, `${path}[${i}]`));
    return;
  }
  if (expected && typeof expected === 'object') {
    expect(actual, path).toBeTruthy();
    const a = actual as Record<string, unknown>;
    const e = expected as Record<string, unknown>;
    expect(Object.keys(a).sort(), `${path} keys`).toEqual(Object.keys(e).sort());
    for (const key of Object.keys(e)) expectSame(a[key], e[key], `${path}.${key}`);
    return;
  }
  expect(actual, path).toEqual(expected);
}

describe('card metrics match the server', () => {
  it.each(golden.layout_cases)('$name', (testCase) => {
    const actual = numericLayoutPayload(
      frame,
      testCase.card as Record<string, unknown>,
      testCase.column,
      testCase.layout,
    );
    expectSame(actual, (golden.layouts as Record<string, unknown>)[testCase.name], testCase.name);
  });

  it.each(golden.breakdown_cases)('$name', (testCase) => {
    const actual = computeBreakdown(
      frame,
      testCase.column,
      testCase.breakdown_col,
      testCase.aggregation,
      testCase.top_n_count,
    );
    expectSame(
      actual,
      (golden.breakdowns as Record<string, unknown>)[testCase.name],
      testCase.name,
    );
  });

  it('aggregations match the server', () => {
    for (const [key, expected] of Object.entries(golden.aggregations)) {
      const [column, agg] = key.split('::');
      expectSame(aggregate(frame, column, agg), expected, key);
    }
  });
});
