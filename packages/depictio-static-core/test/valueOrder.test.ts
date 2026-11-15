/**
 * orderValues vs value_order.py::order_values. The expectations are the
 * Python function's own output for these inputs (pasted from a run against
 * the repo venv; the TS port must reproduce them exactly).
 */
import { describe, expect, it } from 'vitest';

import { orderValues, parseDurationHours } from '../src/valueOrder';

const CASES: [string[], Record<string, string | null> | null, string[]][] = [
  [['18h', '1h', '2h', '30min'], null, ['30min', '1h', '2h', '18h']],
  [['b', 'A', 'a', '10', '9'], null, ['10', '9', 'A', 'a', 'b']],
  [['Sample_10', 'Sample_2', 'x'], null, ['Sample_10', 'Sample_2', 'x']],
  [['t1', 't2', 't3', 't4'], { t1: '3', t2: '1', t3: null, t4: '10' }, ['t2', 't1', 't4', 't3']],
  [['x', 'y', 'z'], { x: 'b2', y: 'b10', z: 'a' }, ['z', 'x', 'y']],
  [['GM_1d', 'GM_12h', 'GM_30m'], null, ['GM_30m', 'GM_12h', 'GM_1d']],
];

describe('orderValues (value_order.order_values)', () => {
  it.each(CASES)('%j keyed by %j', (values, keys, want) => {
    expect(orderValues(values, keys ? new Map(Object.entries(keys)) : null)).toEqual(want);
  });
  it('drops nulls and dedupes', () => {
    expect(orderValues(['b', null, 'a', 'b'])).toEqual(['a', 'b']);
  });
  it('parses trailing durations only', () => {
    expect(parseDurationHours('30min')).toBeCloseTo(0.5);
    expect(parseDurationHours('GM_1d')).toBe(24);
    expect(parseDurationHours('h1')).toBeNull();
  });
});
