import { describe, expect, it } from 'vitest';

import type { ChordLink } from './chordLayout';
import {
  BREAKPOINT_PAD_BP,
  breakpointHighlight,
  breakpointOf,
  breakpointRegion,
  nearestSide,
  sideColumns,
} from './chordLinking';

const link: ChordLink = {
  chromA: 'chr9',
  posA: 130_854_000,
  chromB: 'chr22',
  posB: 23_632_000,
  label: 'BCR::ABL1',
  weight: 12,
  category: 'fusion',
  sample: 'S1',
  row: 4,
};

describe('nearestSide', () => {
  it('is the end the pointer is closer to', () => {
    const a = { x: 0, y: 0 };
    const b = { x: 100, y: 0 };
    expect(nearestSide({ x: 10, y: 5 }, a, b)).toBe('a');
    expect(nearestSide({ x: 90, y: -5 }, a, b)).toBe('b');
  });
  it('takes the first end on a tie', () => {
    expect(nearestSide({ x: 50, y: 0 }, { x: 0, y: 0 }, { x: 100, y: 0 })).toBe('a');
  });
});

describe('breakpointOf', () => {
  it('reads either end', () => {
    expect(breakpointOf(link, 'a')).toEqual({ chrom: 'chr9', pos: 130_854_000 });
    expect(breakpointOf(link, 'b')).toEqual({ chrom: 'chr22', pos: 23_632_000 });
  });
});

describe('breakpointHighlight', () => {
  it('is the breakpoint as a genomic interval, with the colour, aliases and row key', () => {
    expect(
      breakpointHighlight(link, 'b', { color: '#e8590c', positionColumn: 'pos_b', rowKey: 'BCR::ABL1' }),
    ).toEqual({
      entity: 'chr22',
      start: 23_632_000,
      end: 23_632_000,
      entityAliases: ['22'],
      positionColumn: 'pos_b',
      color: '#e8590c',
      rowKeys: ['BCR::ABL1'],
      genomic: { refName: 'chr22', start: 23_632_000, end: 23_632_000, aliases: ['22'] },
    });
  });
  it('leaves out what it was not given', () => {
    const ev = breakpointHighlight(link, 'a');
    expect(ev.color).toBeUndefined();
    expect(ev.rowKeys).toBeUndefined();
    expect(ev.genomic?.refName).toBe('chr9');
  });
});

describe('breakpointRegion', () => {
  it('is one contig and a window around the breakpoint', () => {
    expect(breakpointRegion(link, 'a')).toEqual({
      chroms: ['chr9'],
      range: [130_854_000 - BREAKPOINT_PAD_BP, 130_854_000 + BREAKPOINT_PAD_BP],
    });
  });
  it('never starts below 0', () => {
    expect(breakpointRegion({ ...link, posB: 100 }, 'b').range).toEqual([0, 100 + BREAKPOINT_PAD_BP]);
  });
});

describe('sideColumns', () => {
  it('names the columns of the end, for the region filter pair', () => {
    const cfg = { chrom_a_col: 'ca', pos_a_col: 'pa', chrom_b_col: 'cb', pos_b_col: 'pb' };
    expect(sideColumns(cfg, 'a')).toEqual({ chrom: 'ca', pos: 'pa' });
    expect(sideColumns(cfg, 'b')).toEqual({ chrom: 'cb', pos: 'pb' });
  });
});
