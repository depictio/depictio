/**
 * Trendline refit parity: every px trendline kind the binder accepts, refit in
 * the browser, against what px + statsmodels + pandas draw for the same rows.
 *
 * `fixtures/trendline-expected.json` is produced by
 * `scripts/generate_trendline_fixture.py` with the real pipeline: the binding
 * comes from `build_binding` on the full frame, the expectation from
 * `create_figure_from_data` on the frame each mask keeps. So a case passes only
 * when the shipped binding, refilled under the mask, draws the vertices the
 * server would have drawn had it rendered the filtered view.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import type { BindingTable, TraceBinding, TrendlineBinding } from '../src/manifest';
import { refillFigure } from '../src/refill';
import { fitTrendline, lowess } from '../src/trendline';

interface FixtureMask {
  name: string;
  mask: number[] | null;
  expected: Record<string, { x: unknown[]; y: (number | null)[] } | null>;
}

interface FixtureCase {
  name: string;
  frame: string;
  temporal_x: boolean;
  traces: number;
  binding: { group_cols: string[]; traces: TraceBinding[]; trendlines: TrendlineBinding[] };
  masks: FixtureMask[];
}

const FIXTURE = JSON.parse(
  readFileSync(join(__dirname, '..', 'fixtures', 'trendline-expected.json'), 'utf-8'),
) as { frames: Record<string, Record<string, unknown[]>>; cases: FixtureCase[] };

/** Relative 1e-9: the ports follow the kernels' own arithmetic, but numpy's
 *  pairwise sums and statsmodels' pinv solve round differently from a loop. */
function close(actual: number, expected: number | null): boolean {
  if (expected === null) return Number.isNaN(actual) || actual === null;
  return Math.abs(actual - expected) <= 1e-9 * Math.max(1, Math.abs(expected));
}

function columnsOf(c: FixtureCase): Record<string, ArrayLike<unknown>> {
  const out: Record<string, ArrayLike<unknown>> = {};
  for (const [name, values] of Object.entries(FIXTURE.frames[c.frame])) {
    // A temporal column decodes from Parquet as Date objects.
    const temporal = c.temporal_x && c.binding.traces.some((t) => t.fields.x === name);
    out[name] = temporal
      ? values.map((v) => (v === null ? null : new Date(`${String(v)}Z`)))
      : values;
  }
  return out;
}

function bindingOf(c: FixtureCase): BindingTable {
  return {
    scaffold: { data: Array.from({ length: c.traces }, () => ({})), layout: {} },
    group_cols: c.binding.group_cols,
    traces: c.binding.traces,
    trendlines: c.binding.trendlines,
    sampled: false,
  };
}

function xMillis(v: unknown): unknown {
  if (v instanceof Date) return v.getTime();
  if (typeof v === 'string') return Date.parse(`${v}Z`);
  return v;
}

describe('trendline refit parity with px (fixtures/trendline-expected.json)', () => {
  expect(FIXTURE.cases.length).toBeGreaterThan(20);

  for (const c of FIXTURE.cases) {
    for (const m of c.masks) {
      it(`${c.name} — ${m.name}`, async () => {
        const cols = columnsOf(c);
        const { figure } = await refillFigure({
          binding: bindingOf(c),
          columns: (names) =>
            Promise.resolve(Object.fromEntries(names.map((n) => [n, cols[n]]))),
          mask: m.mask === null ? null : Uint8Array.from(m.mask),
        });
        const data = figure.data as Record<string, unknown>[];
        let drawn = 0;
        for (const [index, expected] of Object.entries(m.expected)) {
          const trace = data[Number(index)];
          if (expected === null) {
            expect(trace.visible, `trace ${index} should be hidden`).toBe(false);
            continue;
          }
          drawn++;
          expect(trace.visible).not.toBe(false);
          const x = trace.x as unknown[];
          const y = trace.y as number[];
          expect(x.map(xMillis)).toEqual(expected.x.map(xMillis));
          expect(y).toHaveLength(expected.y.length);
          const bad = y.findIndex((v, k) => !close(v, expected.y[k]));
          expect(bad, `y[${bad}] = ${y[bad]} vs ${expected.y[bad]}`).toBe(-1);
        }
        if (m.name !== 'one group down to a row') expect(drawn).toBeGreaterThan(0);
      });
    }
  }
});

describe('fitTrendline edge cases', () => {
  it('returns null below two usable pairs (px leaves the trace empty)', () => {
    expect(fitTrendline('lowess', {}, [1, null, 3], [2, 5, null], [0, 1, 2])).toBeNull();
  });

  it('a constant x gets the mean of y, as statsmodels pinv solves it', () => {
    const fit = fitTrendline('ols', {}, [2, 2, 2], [1, 2, 6], [0, 1, 2]);
    expect(fit?.y).toEqual([3, 3, 3]);
  });

  it('refuses an option it has no port of rather than drawing a guess', () => {
    expect(() =>
      fitTrendline('rolling', { window: '7D' }, [1, 2, 3], [1, 2, 3], [0, 1, 2]),
    ).toThrow(/window/);
    expect(() =>
      fitTrendline('rolling', { window: 2, win_type: 'gaussian' }, [1, 2, 3], [1, 2, 3], [0, 1, 2]),
    ).toThrow(/win_type/);
  });

  it('lowess interpolates exactly between fits when delta skips points', () => {
    // A straight line is reproduced whatever is skipped.
    const x = [0, 1, 2, 3, 4, 5, 6, 7];
    const y = x.map((v) => 2 * v + 1);
    const fit = lowess(x, y, 0.5, 0, 2.5);
    fit.forEach((v, k) => expect(v).toBeCloseTo(y[k], 9));
  });
});
