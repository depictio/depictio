import { describe, expect, it } from 'vitest';

import {
  contigOffsets,
  intersectBounds,
  linearPixel,
  locusToLinear,
  placeStars,
  starPath,
  starRadius,
  starRowsOf,
  starVertices,
} from './starOverlay';

const contigs = [
  { name: 'chr1', size: 1000 },
  { name: 'chr2', size: 500 },
  { name: 'chrX', size: 200 },
];

describe('contigOffsets / locusToLinear', () => {
  const offsets = contigOffsets(contigs);

  it('lays the contigs end to end, as GenomeSpy does', () => {
    expect(locusToLinear(offsets, 'chr1', 10)).toBe(10);
    expect(locusToLinear(offsets, 'chr2', 10)).toBe(1010);
    expect(locusToLinear(offsets, 'chrX', 0)).toBe(1500);
  });

  it('accepts the names GenomeSpy accepts: with or without chr, and the number', () => {
    expect(locusToLinear(offsets, '2', 5)).toBe(1005);
    expect(locusToLinear(offsets, 'X', 5)).toBe(1505);
    expect(locusToLinear(offsets, 'CHR2', 5)).toBe(1005);
  });

  it('is null for a contig the axis lacks or a bad position', () => {
    expect(locusToLinear(offsets, 'chrUn', 5)).toBeNull();
    expect(locusToLinear(offsets, 'chr1', Number.NaN)).toBeNull();
  });
});

describe('linearPixel', () => {
  it('maps the domain onto the span', () => {
    expect(linearPixel(50, [0, 100], 10, 200)).toBe(110);
    expect(linearPixel(0, [0, 100], 10, 200)).toBe(10);
    expect(linearPixel(100, [0, 100], 10, 200)).toBe(210);
  });

  it('runs backwards for a negative length (a y axis)', () => {
    // bottom at pixel 300, top at 100: the domain's low end is the bottom
    expect(linearPixel(-10, [-10, 15], 300, -200)).toBe(300);
    expect(linearPixel(15, [-10, 15], 300, -200)).toBe(100);
    expect(linearPixel(2.5, [-10, 15], 300, -200)).toBe(200);
  });

  it('puts a degenerate domain in the middle', () => {
    expect(linearPixel(3, [3, 3], 0, 100)).toBe(50);
  });
});

describe('placeStars', () => {
  const offsets = contigOffsets(contigs);
  const bounds = { x: 60, y: 20, width: 400, height: 100 };
  const base = { offsets, bounds, xDomain: [0, 1700] as [number, number], yDomain: [0, 10] as [number, number], reach: 8 };

  it('places a star on its data point: x from the locus, y from the score (up is high)', () => {
    const [s] = placeStars({ ...base, rows: [{ chrom: 'chr2', pos: 350, score: 10, medal: 1 }] });
    // linear 1350 of 1700 over 400 px
    expect(s.x).toBeCloseTo(60 + (1350 / 1700) * 400, 6);
    expect(s.y).toBeCloseTo(20, 6); // the top of the box
    const [low] = placeStars({ ...base, rows: [{ chrom: 'chr1', pos: 0, score: 0, medal: 2 }] });
    expect(low.x).toBeCloseTo(60, 6);
    expect(low.y).toBeCloseTo(120, 6); // the bottom
  });

  it('follows a zoom: the same row lands elsewhere in a narrower domain', () => {
    const row = { chrom: 'chr1', pos: 500, score: 5, medal: 1 };
    const [wide] = placeStars({ ...base, rows: [row] });
    const [zoomed] = placeStars({ ...base, xDomain: [400, 600], rows: [row] });
    expect(wide.x).toBeCloseTo(60 + (500 / 1700) * 400, 6);
    expect(zoomed.x).toBeCloseTo(60 + 200, 6); // the middle of the box
  });

  it('hides stars outside the visible domain, keeps one a radius off the edge', () => {
    const rows = [
      { chrom: 'chr1', pos: 100, score: 5, medal: 1 },
      { chrom: 'chr1', pos: 900, score: 5, medal: 2 },
    ];
    expect(placeStars({ ...base, xDomain: [500, 1000], rows }).map((s) => s.medal)).toEqual([2]);
    // 5 px left of the box: its tip is still inside, the caller clips the rest
    const edge = [{ chrom: 'chr1', pos: 0, score: 5, medal: 1 }];
    const shifted = { ...base, xDomain: [20, 1720] as [number, number] }; // 20 linear = 4.7 px
    expect(placeStars({ ...shifted, rows: edge })).toHaveLength(1);
    expect(placeStars({ ...shifted, xDomain: [100, 1800], rows: edge })).toHaveLength(0);
  });

  it('skips rows on a contig the axis lacks and draws bronze first', () => {
    const rows = [
      { chrom: 'chr1', pos: 10, score: 5, medal: 1 },
      { chrom: 'nope', pos: 10, score: 5, medal: 2 },
      { chrom: 'chr1', pos: 20, score: 5, medal: 3 },
    ];
    expect(placeStars({ ...base, rows }).map((s) => s.medal)).toEqual([3, 1]);
  });
});

describe('star geometry', () => {
  it('has ten vertices, tips on the outer circle, notches on the inner, first tip up', () => {
    const v = starVertices(100, 50, 10);
    expect(v).toHaveLength(10);
    expect(v[0][0]).toBeCloseTo(100, 6);
    expect(v[0][1]).toBeCloseTo(40, 6); // straight up (y down)
    v.forEach(([x, y], i) => {
      expect(Math.hypot(x - 100, y - 50)).toBeCloseTo(i % 2 === 0 ? 10 : 4.5, 6);
    });
  });

  it('has 36 degree tips: the angle at a tip is what a 60 degree triangle cannot give', () => {
    const v = starVertices(0, 0, 10, 0.382);
    const [tip, a, b] = [v[0], v[1], v[9]];
    const ang = (p: number[], q: number[]) => Math.atan2(p[1] - tip[1], p[0] - tip[0]) - Math.atan2(q[1] - tip[1], q[0] - tip[0]);
    // a regular pentagram (inner/outer = 0.382) has 36 degree points
    expect(Math.abs((ang(a, b) * 180) / Math.PI)).toBeCloseTo(36, 0);
  });

  it('is symmetric about the vertical axis', () => {
    const v = starVertices(0, 0, 10);
    for (let i = 1; i < 5; i++) {
      expect(v[i][0]).toBeCloseTo(-v[10 - i][0], 6);
      expect(v[i][1]).toBeCloseTo(v[10 - i][1], 6);
    }
  });

  it('writes a closed path of ten points', () => {
    const d = starPath(10, 10, 6);
    expect(d.startsWith('M10 4')).toBe(true);
    expect(d.endsWith('Z')).toBe(true);
    expect(d.match(/[ML]/g)).toHaveLength(10);
  });

  it('is point_size * 1.4 outside, at least 6 px', () => {
    expect(starRadius(10)).toBeCloseTo(14, 6);
    expect(starRadius(2)).toBe(6);
  });
});

describe('intersectBounds', () => {
  it('clips a lane to its viewport', () => {
    expect(intersectBounds({ x: 0, y: 0, width: 100, height: 100 }, { x: 0, y: 40, width: 100, height: 100 })).toEqual({
      x: 0,
      y: 40,
      width: 100,
      height: 60,
    });
    expect(intersectBounds({ x: 0, y: 0, width: 10, height: 10 }, { x: 20, y: 20, width: 10, height: 10 })).toBeNull();
  });
});

describe('starRowsOf', () => {
  const cols = { chr: 'chr', pos: 'pos', score: 'score', sample: 's' };
  const data = [
    { chr: 'chr1', pos: 5, score: 9, s: 'A', _star: 1 },
    { chr: 'chr1', pos: 6, score: 8, s: 'B', _star: 2 },
    { chr: 'chr1', pos: 7, score: 1, s: 'A', _star: 0 },
    { chr: null, pos: 7, score: 7, s: 'A', _star: 3 },
  ];

  it('keeps the starred rows with a position', () => {
    expect(starRowsOf(data, cols, null).map((r) => r.medal)).toEqual([1, 2]);
  });

  it('keeps a faceted lane to its sample', () => {
    expect(starRowsOf(data, cols, 'B')).toEqual([{ chrom: 'chr1', pos: 6, score: 8, medal: 2 }]);
  });

  it('copes with no rows', () => {
    expect(starRowsOf(null, cols, null)).toEqual([]);
  });
});
