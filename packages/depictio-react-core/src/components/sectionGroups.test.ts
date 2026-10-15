import { describe, expect, it } from 'vitest';

import {
  MIN_FIT_ROW_PX,
  dockSplit,
  dockWidthFraction,
  effectiveDisplay,
  fitRowPx,
  layoutRows,
  rebaseOutsideBand,
} from './sectionGroups';

const tile = (i: string, x: number, y: number, w: number, h: number) => ({ i, x, y, w, h });
const geometry = (tiles: ReturnType<typeof tile>[]) =>
  Object.fromEntries(tiles.map((t) => [t.i, [t.x, t.y, t.w, t.h]]));

describe('effectiveDisplay', () => {
  it('keeps what the dashboard declares without an override', () => {
    expect(effectiveDisplay({ display: 'workbench' }, null)).toBe('workbench');
    expect(effectiveDisplay({ display: 'dock' }, null)).toBe('dock');
  });

  it('draws both groups as ordinary sections under classic', () => {
    expect(effectiveDisplay({ display: 'workbench' }, 'classic')).toBe('grid');
    expect(effectiveDisplay({ display: 'dock' }, 'classic')).toBe('grid');
  });

  it('turns a workbench into a dock under dock, and leaves a dock alone', () => {
    expect(effectiveDisplay({ display: 'workbench' }, 'dock')).toBe('dock');
    expect(effectiveDisplay({ display: 'dock' }, 'dock')).toBe('dock');
  });

  it('never touches a section that is not a group', () => {
    for (const override of ['classic', 'dock', null] as const) {
      expect(effectiveDisplay({ display: 'strip' }, override)).toBe('strip');
      expect(effectiveDisplay({ display: 'grid' }, override)).toBe('grid');
      expect(effectiveDisplay({ display: null }, override)).toBeNull();
      expect(effectiveDisplay({}, override)).toBeUndefined();
      expect(effectiveDisplay(undefined, override)).toBeUndefined();
    }
  });
});

describe('fitRowPx', () => {
  it('fills the room: rows plus the gaps between them', () => {
    // 10 rows and 9 gaps of 4 in 676 px: (676 - 36) / 10.
    expect(fitRowPx(10, 676, 4, 100)).toBe(64);
  });

  it('floors, so the section never overshoots by a fraction', () => {
    expect(fitRowPx(7, 500, 4, 100)).toBe(Math.floor((500 - 24) / 7));
  });

  it('squeezes no further than the minimum', () => {
    expect(fitRowPx(20, 300, 4, 100)).toBe(MIN_FIT_ROW_PX);
  });

  it('stretches no further than 1.5 times the normal row', () => {
    expect(fitRowPx(2, 900, 4, 100)).toBe(150);
    // A read-only grid counts in half rows (48 px): 72 at most.
    expect(fitRowPx(2, 900, 4, 48)).toBe(72);
  });

  it('never raises the minimum above a row that is already smaller', () => {
    expect(fitRowPx(50, 100, 4, 20)).toBe(20);
  });

  it('keeps the normal row when there is nothing to fit', () => {
    expect(fitRowPx(0, 600, 4, 100)).toBe(100);
    expect(fitRowPx(10, 0, 4, 100)).toBe(100);
    expect(fitRowPx(10, -20, 4, 100)).toBe(100);
    expect(fitRowPx(10, Number.NaN, 4, 100)).toBe(100);
  });

  it('counts the gaps of each stacked block, not of one tall block', () => {
    // Two stacks of 5 rows: 8 gaps in all, not 9.
    expect(fitRowPx(10, 672, 4, 100, 2)).toBe(64);
    expect(fitRowPx(10, 672, 4, 100, 1)).toBe(63);
  });
});

describe('layoutRows', () => {
  it('is the bottom edge of the lowest tile', () => {
    expect(layoutRows([tile('a', 0, 0, 3, 8), tile('b', 3, 0, 5, 3), tile('c', 3, 3, 5, 6)])).toBe(9);
    expect(layoutRows([])).toBe(0);
  });
});

describe('rebaseOutsideBand', () => {
  it('moves tiles right of the band left by its width, and widens them over the 8 columns', () => {
    const out = rebaseOutsideBand([tile('a', 3, 0, 5, 3), tile('b', 3, 3, 2, 2), tile('c', 5, 3, 3, 2)], {
      x: 0,
      w: 3,
    });
    expect(geometry(out)).toEqual({
      a: [0, 0, 8, 3],
      // 2 of the 5 kept columns is 3.2 of 8, and the edge it shares with the
      // next tile is the same edge for both.
      b: [0, 3, 3, 2],
      c: [3, 3, 5, 2],
    });
  });

  it('maps a band on the right the same way', () => {
    const out = rebaseOutsideBand([tile('a', 0, 0, 5, 3), tile('b', 0, 3, 2, 2), tile('c', 2, 3, 3, 2)], {
      x: 5,
      w: 3,
    });
    expect(geometry(out)).toEqual({ a: [0, 0, 8, 3], b: [0, 3, 3, 2], c: [3, 3, 5, 2] });
  });

  it('closes up a band in the middle, tiles on both sides sharing the room', () => {
    const out = rebaseOutsideBand([tile('l', 0, 0, 2, 4), tile('r', 5, 0, 3, 4)], { x: 2, w: 3 });
    expect(geometry(out)).toEqual({ l: [0, 0, 3, 4], r: [3, 0, 5, 4] });
  });

  it('keeps what a tile only partly in the band has outside it', () => {
    const [t] = rebaseOutsideBand([tile('a', 1, 0, 4, 2)], { x: 3, w: 3 });
    // Columns 1..3 remain of the tile's 1..5.
    expect(t.x).toBeGreaterThanOrEqual(0);
    expect(t.x + t.w).toBeLessThanOrEqual(8);
    expect(t.w).toBeGreaterThanOrEqual(1);
  });

  it('keeps every tile at least one column wide and inside the grid', () => {
    const tiles = [tile('a', 0, 0, 1, 1), tile('b', 6, 0, 1, 1), tile('c', 7, 0, 1, 1)];
    for (const t of rebaseOutsideBand(tiles, { x: 1, w: 5 })) {
      expect(t.w).toBeGreaterThanOrEqual(1);
      expect(t.x).toBeGreaterThanOrEqual(0);
      expect(t.x + t.w).toBeLessThanOrEqual(8);
    }
  });

  it('has nothing to rebase when the band is the whole grid', () => {
    expect(rebaseOutsideBand([tile('a', 0, 0, 8, 2)], { x: 0, w: 8 })).toEqual([]);
  });
});

describe('dockSplit', () => {
  // The protein workbench: a 3D structure on the left over the full height, the
  // linked views stacked beside it.
  const workbench = [
    tile('hmm', 3, 0, 5, 3),
    tile('structure', 0, 0, 3, 9),
    tile('track', 3, 3, 5, 2),
    tile('msa', 3, 5, 5, 4),
  ];

  it('docks the tallest tile and keeps the others scrolling over the full width', () => {
    const { band, docked, rest } = dockSplit(workbench);
    expect(band).toEqual({ x: 0, w: 3 });
    expect(geometry(docked)).toEqual({ structure: [0, 0, 3, 9] });
    expect(geometry(rest)).toEqual({
      hmm: [0, 0, 8, 3],
      track: [0, 3, 8, 2],
      msa: [0, 5, 8, 4],
    });
  });

  it('docks every tile that lies inside the anchor band, relative to the band', () => {
    const { band, docked, rest } = dockSplit([
      tile('tall', 5, 0, 3, 8),
      tile('under', 5, 8, 3, 2),
      tile('narrow', 6, 8, 1, 1),
      tile('beside', 0, 0, 5, 4),
    ]);
    expect(band).toEqual({ x: 5, w: 3 });
    expect(geometry(docked)).toEqual({
      tall: [0, 0, 3, 8],
      under: [0, 8, 3, 2],
      narrow: [1, 8, 1, 1],
    });
    expect(geometry(rest)).toEqual({ beside: [0, 0, 8, 4] });
  });

  it('leaves a tile that only overlaps the band in the scrolling column', () => {
    const { docked, rest } = dockSplit([tile('tall', 0, 0, 3, 8), tile('straddle', 2, 0, 3, 2)]);
    expect(docked.map((t) => t.i)).toEqual(['tall']);
    expect(rest.map((t) => t.i)).toEqual(['straddle']);
  });

  it('breaks a tie between equally tall tiles by reading order', () => {
    const { band } = dockSplit([tile('right', 4, 0, 4, 6), tile('left', 0, 0, 4, 6)]);
    expect(band).toEqual({ x: 0, w: 4 });
  });

  it('docks everything when the anchor spans the whole grid', () => {
    const { docked, rest } = dockSplit([tile('a', 0, 0, 8, 6), tile('b', 0, 6, 4, 2)]);
    expect(docked.map((t) => t.i)).toEqual(['a', 'b']);
    expect(rest).toEqual([]);
  });

  it('does not mutate the layout it is given', () => {
    const input = workbench.map((t) => ({ ...t }));
    dockSplit(input);
    expect(input).toEqual(workbench);
  });

  it('is empty for an empty layout', () => {
    expect(dockSplit([])).toEqual({ band: null, docked: [], rest: [] });
  });
});

describe('dockWidthFraction', () => {
  it('is the widest docked tile over the 8 columns', () => {
    expect(dockWidthFraction([tile('a', 0, 0, 3, 8), tile('b', 0, 8, 2, 2)])).toBe(3 / 8);
  });

  it('keeps the dock between a quarter and a half of the width', () => {
    expect(dockWidthFraction([tile('a', 0, 0, 1, 8)])).toBe(0.25);
    expect(dockWidthFraction([tile('a', 0, 0, 8, 8)])).toBe(0.5);
    expect(dockWidthFraction([])).toBe(0.25);
  });
});
