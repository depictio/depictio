import { describe, expect, it } from 'vitest';

import {
  PERSISTED_LOCUS_SUFFIX,
  initialLocus,
  shouldRenavigate,
  sidesLocus,
  wideRegionTarget,
} from './openingLocus';

describe('sidesLocus', () => {
  it('joins the call and its mate with a space when both sides are on', () => {
    expect(sidesLocus('chr4:1-100', 'chr4:900-1000', true)).toBe('chr4:1-100 chr4:900-1000');
  });
  it('keeps the call alone with the toggle off or without a mate', () => {
    expect(sidesLocus('chr4:1-100', 'chr4:900-1000', false)).toBe('chr4:1-100');
    expect(sidesLocus('chr4:1-100', null, true)).toBe('chr4:1-100');
  });
  it('is null without a locus', () => {
    expect(sidesLocus(null, 'chr4:9-10', true)).toBeNull();
  });
});

describe('initialLocus', () => {
  it('lets a dashboard pick beat the locus the reader left the view at', () => {
    const args = { persisted: 'chr1:5-9', location: 'chr10:100-400', bothSides: false };
    expect(initialLocus({ ...args, opening: 'filter' })).toBe('chr10:100-400');
    expect(initialLocus({ ...args, opening: 'first_call' })).toBe('chr1:5-9');
  });
  it('zooms into the region on the payload location when it lies inside it', () => {
    const region = { chrom: 'chr1', start: 0, end: Number.POSITIVE_INFINITY };
    const args = { region, regionLocus: 'chr1', persisted: null, bothSides: false };
    expect(initialLocus({ ...args, location: 'chr1:1,200,000-1,260,000' })).toBe('chr1:1,200,000-1,260,000');
    // Elsewhere, the region wins: the browser opens where the navigator shows.
    expect(initialLocus({ ...args, location: 'chr5:1,200,000-1,260,000' })).toBe('chr1');
  });
  it('opens on a locus another tile handed over, before anything else', () => {
    expect(
      initialLocus({
        pending: 'chr8:100-200',
        persisted: 'chr1:5-9',
        location: 'chr4:1-2',
        bothSides: false,
      }),
    ).toBe('chr8:100-200');
  });
  it('opens on the window another genome tile has in force when the opening is a default', () => {
    const args = {
      window: 'chr12:6,000-9,000',
      persisted: 'chr1:5-9',
      location: 'chr4:1-2',
      bothSides: false,
    };
    expect(initialLocus({ ...args, opening: 'data' })).toBe('chr12:6,000-9,000');
    expect(initialLocus({ ...args, opening: 'preset' })).toBe('chr12:6,000-9,000');
    // A place the dashboard asked for is not a default: it keeps the view.
    expect(initialLocus({ ...args, opening: 'yaml' })).toBe('chr1:5-9');
    expect(initialLocus({ ...args, opening: 'first_call' })).toBe('chr1:5-9');
    expect(initialLocus({ ...args, opening: 'filter' })).toBe('chr4:1-2');
  });
  it('ignores an empty hand-over', () => {
    expect(
      initialLocus({ pending: null, persisted: 'chr1:5-9', location: null, bothSides: false }),
    ).toBe('chr1:5-9');
  });
  it('prefers what the reader left the view at', () => {
    expect(
      initialLocus({ persisted: 'chr1:5-9', location: 'chr4:1-2', bothSides: true }),
    ).toBe('chr1:5-9');
  });
  it('opens on the payload, with the mate when both sides are on', () => {
    expect(
      initialLocus({ persisted: null, location: 'chr4:1-2', mateLocation: 'chr9:3-4', bothSides: true }),
    ).toBe('chr4:1-2 chr9:3-4');
    expect(
      initialLocus({ persisted: null, location: 'chr4:1-2', mateLocation: 'chr9:3-4', bothSides: false }),
    ).toBe('chr4:1-2');
  });
  it('opens on the region in force, unless the reader left the view inside it', () => {
    const region = { chrom: 'chr6', start: 26_000_000, end: 26_300_000 };
    const regionLocus = 'chr6:26000000-26300000';
    const base = { region, regionLocus, location: 'chr6:70-90', bothSides: false };
    expect(initialLocus({ ...base, persisted: 'chr6:70,322,816..152,717,713' })).toBe(regionLocus);
    expect(initialLocus({ ...base, persisted: null })).toBe(regionLocus);
    expect(initialLocus({ ...base, persisted: '6:26,100,000..26,150,000' })).toBe(
      '6:26,100,000..26,150,000',
    );
    expect(initialLocus({ ...base, pending: 'chr1:1-2', persisted: null })).toBe('chr1:1-2');
  });
  it('leaves the whole assembly to JBrowse when nothing is known', () => {
    expect(initialLocus({ persisted: null, location: null, bothSides: false })).toBeUndefined();
  });
});

describe('persisted locus key', () => {
  it('is a new key, so the old .loc (which held the preset view) is forgotten', () => {
    expect(PERSISTED_LOCUS_SUFFIX).toBe('loc.v2');
  });
});

describe('shouldRenavigate', () => {
  it('moves an open view for a location the dashboard asked for', () => {
    expect(shouldRenavigate('filter', 'chr4:1-2', 'chr1:1-2')).toBe(true);
    expect(shouldRenavigate('yaml', 'chr4:1-2', null)).toBe(true);
  });
  it('leaves the opening defaults alone on a refetch', () => {
    expect(shouldRenavigate('first_call', 'chr4:1-2', 'chr1:1-2')).toBe(false);
    expect(shouldRenavigate('data', 'chr4:1-2', 'chr1:1-2')).toBe(false);
    expect(shouldRenavigate('preset', 'chr4:1-2', null)).toBe(false);
  });
  it('does nothing for an unchanged or missing location', () => {
    expect(shouldRenavigate('filter', 'chr4:1-2', 'chr4:1-2')).toBe(false);
    expect(shouldRenavigate('filter', null, 'chr4:1-2')).toBe(false);
  });
  it('keeps the old behaviour against a backend that sends no opening', () => {
    expect(shouldRenavigate(undefined, 'chr4:1-2', 'chr1:1-2')).toBe(true);
  });
});

describe('wideRegionTarget', () => {
  const contig = { chrom: 'chr21', start: 0, end: Number.POSITIVE_INFINITY };
  it('sends a whole-contig region to the location inside it', () => {
    expect(wideRegionTarget(contig, '21:10934854-11029747', 1_000_000)).toBe('21:10934854-11029747');
  });
  it('keeps a narrow region as is', () => {
    expect(wideRegionTarget({ chrom: 'chr21', start: 0, end: 500_000 }, 'chr21:100-200', 1_000_000)).toBeNull();
  });
  it('keeps a wide region whose location is elsewhere', () => {
    expect(wideRegionTarget(contig, 'chr2:100-200', 1_000_000)).toBeNull();
    expect(wideRegionTarget(contig, null, 1_000_000)).toBeNull();
  });
});
