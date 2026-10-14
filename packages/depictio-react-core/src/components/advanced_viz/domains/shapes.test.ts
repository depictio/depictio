import { describe, expect, it } from 'vitest';

import {
  domainShapePath,
  fitDepth,
  outlineDash,
  toothCount,
  zigzagPoints,
  type PathContext,
} from './shapes';

type Call = [string, ...number[]];

/** A path context that records every call. */
function recorder(): { ctx: PathContext; calls: Call[] } {
  const calls: Call[] = [];
  const log =
    (name: string) =>
    (...args: number[]) => {
      calls.push([name, ...args]);
    };
  const ctx = {
    beginPath: log('beginPath'),
    closePath: log('closePath'),
    moveTo: log('moveTo'),
    lineTo: log('lineTo'),
    arcTo: log('arcTo'),
  } as unknown as PathContext;
  return { ctx, calls };
}

const names = (calls: Call[]) => calls.map((c) => c[0]);

describe('zigzagPoints', () => {
  it('alternates between the cut and the edge, ending on the edge', () => {
    expect(zigzagPoints(10, 0, 8, -2, 2)).toEqual([
      [8, 2],
      [10, 4],
      [8, 6],
      [10, 8],
    ]);
  });

  it('runs upwards too', () => {
    expect(zigzagPoints(0, 8, 0, 2, 1)).toEqual([
      [2, 4],
      [0, 0],
    ]);
  });
});

describe('toothCount and fitDepth', () => {
  it('follows the height, at least two teeth', () => {
    expect(toothCount(12)).toBe(3);
    expect(toothCount(4)).toBe(2);
    expect(toothCount(0)).toBe(2);
    expect(toothCount(20, 5)).toBe(4);
  });

  it('never cuts through a narrow domain', () => {
    expect(fitDepth(40, 3, 1)).toBe(3);
    expect(fitDepth(4, 3, 1)).toBe(2);
    expect(fitDepth(4, 3, 2)).toBe(1);
    expect(fitDepth(40, 3, 0)).toBe(0);
  });
});

describe('domainShapePath', () => {
  const base = { x: 10, y: 20, w: 100, h: 12, radius: 4 };

  it('draws a whole domain as a rounded rectangle', () => {
    const { ctx, calls } = recorder();
    domainShapePath(ctx, { ...base, left: false, right: false });
    expect(calls).toEqual([
      ['beginPath'],
      ['moveTo', 14, 20],
      ['lineTo', 106, 20],
      ['arcTo', 110, 20, 110, 24, 4],
      ['lineTo', 110, 28],
      ['arcTo', 110, 32, 106, 32, 4],
      ['lineTo', 14, 32],
      ['arcTo', 10, 32, 10, 28, 4],
      ['lineTo', 10, 24],
      ['arcTo', 10, 20, 14, 20, 4],
      ['closePath'],
    ]);
  });

  it('zigzags the right edge of a match that misses the end of the model', () => {
    const { ctx, calls } = recorder();
    domainShapePath(ctx, { ...base, left: false, right: true, depth: 3, toothPx: 6 });
    // Square corners on the right, the teeth cut 3 px in, the left still rounded.
    expect(calls.slice(0, 7)).toEqual([
      ['beginPath'],
      ['moveTo', 14, 20],
      ['lineTo', 110, 20],
      ['lineTo', 107, 23],
      ['lineTo', 110, 26],
      ['lineTo', 107, 29],
      ['lineTo', 110, 32],
    ]);
    expect(calls.slice(7)).toEqual([
      ['lineTo', 14, 32],
      ['arcTo', 10, 32, 10, 28, 4],
      ['lineTo', 10, 24],
      ['arcTo', 10, 20, 14, 20, 4],
      ['closePath'],
    ]);
  });

  it('zigzags the left edge of a match that misses the start of the model', () => {
    const { ctx, calls } = recorder();
    domainShapePath(ctx, { ...base, left: true, right: false, depth: 3, toothPx: 6 });
    expect(calls[1]).toEqual(['moveTo', 10, 20]);
    expect(calls.slice(-6)).toEqual([
      ['lineTo', 10, 32],
      ['lineTo', 13, 29],
      ['lineTo', 10, 26],
      ['lineTo', 13, 23],
      ['lineTo', 10, 20],
      ['closePath'],
    ]);
    expect(names(calls).filter((n) => n === 'arcTo')).toHaveLength(2);
  });

  it('zigzags both edges with no rounded corner, and keeps a narrow body', () => {
    const { ctx, calls } = recorder();
    domainShapePath(ctx, {
      x: 0,
      y: 0,
      w: 4,
      h: 8,
      radius: 4,
      left: true,
      right: true,
      depth: 3,
      toothPx: 4,
    });
    expect(names(calls)).not.toContain('arcTo');
    const xs = calls.filter((c) => c[0] === 'lineTo').map((c) => c[1]);
    // Teeth 1 px deep (4 px wide, two cut edges): the body stays 2 px wide.
    expect(Math.min(...xs.filter((x) => x > 2))).toBe(3);
    expect(Math.max(...xs.filter((x) => x < 2))).toBe(1);
    expect(calls[calls.length - 1]).toEqual(['closePath']);
  });

  it('clamps the corner radius to the shape', () => {
    const { ctx, calls } = recorder();
    domainShapePath(ctx, { x: 0, y: 0, w: 6, h: 12, radius: 10, left: false, right: false });
    expect(calls[1]).toEqual(['moveTo', 3, 0]);
    expect(calls[3]).toEqual(['arcTo', 6, 0, 6, 3, 3]);
  });
});

describe('outlineDash', () => {
  it('dashes a domain partial on an unknown side only', () => {
    expect(outlineDash(true)).toEqual([3, 2]);
    expect(outlineDash(false)).toEqual([]);
  });
});
