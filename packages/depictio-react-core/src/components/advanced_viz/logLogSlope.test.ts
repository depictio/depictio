import { describe, expect, it } from 'vitest';

import { logLogSlope } from './logLogSlope';

/** A power law y = x^k sampled on a log-spaced x grid. */
function powerLaw(k: number, count = 40): { xs: number[]; ys: number[] } {
  const xs = Array.from({ length: count }, (_, i) => 10 ** (i / 10));
  return { xs, ys: xs.map((x) => x ** k) };
}

describe('logLogSlope', () => {
  it('recovers the exponent of a power law everywhere on the curve', () => {
    const { xs, ys } = powerLaw(-1.5);
    const out = logLogSlope(xs, ys, 5);
    expect(out).toHaveLength(xs.length);
    for (const p of out) expect(p.slope).toBeCloseTo(-1.5, 6);
  });

  it('follows a slope that changes half way along the curve', () => {
    // Flat to -2 at x = 100, which is the shape a P(s) curve's crossover has.
    const xs = Array.from({ length: 41 }, (_, i) => 10 ** (i / 10));
    const ys = xs.map((x) => (x < 100 ? 1 : (x / 100) ** -2));
    const out = logLogSlope(xs, ys, 3);
    const at = (target: number) =>
      out.reduce((best, p) => (Math.abs(p.x - target) < Math.abs(best.x - target) ? p : best));
    expect(at(10).slope).toBeCloseTo(0, 6);
    expect(at(1000).slope).toBeCloseTo(-2, 6);
  });

  it('reports x in data units, not log units', () => {
    const { xs, ys } = powerLaw(1, 5);
    const out = logLogSlope(xs, ys, 2);
    expect(out[0].x).toBeCloseTo(xs[0]);
  });

  it('drops points a log axis cannot carry', () => {
    const out = logLogSlope([0, 1, 10, 100], [1, 1, 10, 100], 1);
    // The x = 0 point is gone; the other three still get a slope.
    expect(out).toHaveLength(3);
    expect(out.every((p) => p.x > 0)).toBe(true);
  });

  it('sorts by x before fitting', () => {
    const { xs, ys } = powerLaw(2, 20);
    const order = xs.map((_, i) => i).reverse();
    const out = logLogSlope(
      order.map((i) => xs[i]),
      order.map((i) => ys[i]),
      4,
    );
    for (const p of out) expect(p.slope).toBeCloseTo(2, 6);
    expect(out[0].x).toBeLessThan(out[out.length - 1].x);
  });

  it('returns nothing when there is no curve to fit', () => {
    expect(logLogSlope([1], [1], 5)).toEqual([]);
    expect(logLogSlope([], [], 5)).toEqual([]);
    // A single distinct x has no slope, however many rows carry it.
    expect(logLogSlope([2, 2, 2], [1, 2, 3], 2)).toEqual([]);
  });
});
