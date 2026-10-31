import { describe, expect, it } from 'vitest';

import type { HighlightEvent } from '../../highlight/bus';
import { locusHighlight, viewLeavesRegion, withAlpha } from './locusHighlight';

const canonical = (name: string) => ({ chr8: 'chr8', '8': 'chr8' })[name];

const event = (over: Partial<HighlightEvent>): HighlightEvent => ({
  sourceIndex: 'manhattan',
  entity: 'chr8',
  start: 1000,
  ...over,
});

describe('locusHighlight', () => {
  it('turns a 1-based position into a 1 bp band', () => {
    expect(locusHighlight(event({}), canonical, 'hg38')).toEqual({
      refName: 'chr8',
      start: 999,
      end: 1000,
      assemblyName: 'hg38',
    });
  });

  it('keeps an inclusive range as a half-open one', () => {
    const band = locusHighlight(event({ start: 10, end: 20 }), canonical, 'hg38');
    expect(band).toMatchObject({ start: 9, end: 20 });
  });

  it('resolves an alias to the assembly name and tints with the fallback colour', () => {
    const band = locusHighlight(event({ entity: '8' }), canonical, 'hg38', 'rgb(1, 2, 3)');
    expect(band).toMatchObject({ refName: 'chr8', color: 'rgba(1, 2, 3, 0.35)' });
  });

  it('wears the hovered mark colour over the fallback', () => {
    const band = locusHighlight(event({ color: '#ff8000' }), canonical, 'hg38', '#112233');
    expect(band?.color).toBe('rgba(255, 128, 0, 0.35)');
  });

  it('falls back when the mark colour is not one it reads', () => {
    const band = locusHighlight(event({ color: 'hsl(10, 50%, 50%)' }), canonical, 'hg38', '#112233');
    expect(band?.color).toBe('rgba(17, 34, 51, 0.35)');
    expect(locusHighlight(event({ color: 'teal' }), canonical, 'hg38')).not.toHaveProperty('color');
  });

  it('ignores an entity that is not a reference sequence (protein tiles)', () => {
    expect(locusHighlight(event({ entity: 'P04637' }), canonical, 'hg38')).toBeNull();
  });

  it('ignores an event without an entity, a null event and a bad position', () => {
    expect(locusHighlight(event({ entity: undefined }), canonical, 'hg38')).toBeNull();
    expect(locusHighlight(null, canonical, 'hg38')).toBeNull();
    expect(locusHighlight(event({ start: 0 }), canonical, 'hg38')).toBeNull();
    expect(locusHighlight(event({ start: Number.NaN }), canonical, 'hg38')).toBeNull();
  });

  it('never ends before it starts', () => {
    const band = locusHighlight(event({ start: 50, end: 40 }), canonical, 'hg38');
    expect(band).toMatchObject({ start: 49, end: 50 });
  });
});

describe('withAlpha', () => {
  it('reads hex in its short, long and alpha forms', () => {
    expect(withAlpha('#f80')).toBe('rgba(255, 136, 0, 0.35)');
    expect(withAlpha('#FF8000', 0.5)).toBe('rgba(255, 128, 0, 0.5)');
    expect(withAlpha('#ff800080')).toBe('rgba(255, 128, 0, 0.35)');
  });

  it('reads rgb() and rgba() and drops their own alpha', () => {
    expect(withAlpha('rgb(1, 2, 3)')).toBe('rgba(1, 2, 3, 0.35)');
    expect(withAlpha('rgba(1,2,3,0.9)')).toBe('rgba(1, 2, 3, 0.35)');
  });

  it('returns null for unset or unreadable colours', () => {
    expect(withAlpha(undefined)).toBeNull();
    expect(withAlpha('')).toBeNull();
    expect(withAlpha('var(--x)')).toBeNull();
    expect(withAlpha('#12')).toBeNull();
  });
});

describe('viewLeavesRegion', () => {
  const region = { refName: 'chr6', start: 1000, end: 2000 };
  it('is false while the view stays inside the region, give or take the tolerance', () => {
    expect(viewLeavesRegion([{ refName: 'chr6', start: 1000, end: 2000 }], region)).toBe(false);
    expect(viewLeavesRegion([{ refName: 'chr6', start: 990, end: 2010 }], region)).toBe(false);
    expect(viewLeavesRegion([{ refName: 'chr6', start: 1200, end: 1500 }], region)).toBe(false);
  });
  it('is true once the view reaches past an edge or onto another contig', () => {
    expect(viewLeavesRegion([{ refName: 'chr6', start: 500, end: 1500 }], region)).toBe(true);
    expect(viewLeavesRegion([{ refName: 'chr6', start: 1500, end: 2600 }], region)).toBe(true);
    expect(viewLeavesRegion([{ refName: 'chr7', start: 1200, end: 1500 }], region)).toBe(true);
  });
});
