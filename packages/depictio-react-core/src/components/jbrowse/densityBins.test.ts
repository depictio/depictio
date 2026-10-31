import { describe, expect, it } from 'vitest';

import type { JBrowseDensityTrack } from '../../api';
import {
  availableGroups,
  binAt,
  binOpacity,
  binRect,
  binsBucket,
  chromLabel,
  chromLocus,
  defaultDensityGroup,
  densityRegions,
  densityRows,
  layoutSlots,
  locusString,
  pixelRuns,
  rowHeightFor,
  rowTops,
  slotAt,
  viewMarkers,
} from './densityBins';
import type { NamedLocusSource } from './locusSources';

const genome = [
  { refName: 'chr1', length: 600_000 },
  { refName: 'chr2', length: 300_000 },
  { refName: 'chr3', length: 100_000 },
];

const src = (name: string, extra: Partial<NamedLocusSource> = {}): NamedLocusSource => ({
  name,
  ...extra,
});

const track = (label: string, run?: string): JBrowseDensityTrack => ({
  source: 'peaks',
  label,
  run,
  chroms: [],
});

describe('layoutSlots', () => {
  it('lays chromosomes out proportionally, a separator apart, filling the width', () => {
    const slots = layoutSlots(genome, 1000, 1);
    expect(slots.map((s) => s.refName)).toEqual(['chr1', 'chr2', 'chr3']);
    expect(slots[0].x).toBe(0);
    expect(slots[0].width / slots[1].width).toBeCloseTo(2);
    expect(slots[1].x).toBeCloseTo(slots[0].width + 1);
    const last = slots[2];
    expect(last.x + last.width).toBeCloseTo(1000);
  });
  it('drops contigs under 0.2% of the genome', () => {
    const slots = layoutSlots([...genome, { refName: 'tiny', length: 1000 }], 1000);
    expect(slots.map((s) => s.refName)).toEqual(['chr1', 'chr2', 'chr3']);
  });
  it('keeps everything when every contig is tiny, and the longest when there are too many', () => {
    const draft = Array.from({ length: 5 }, (_, i) => ({ refName: `c${i}`, length: 100 }));
    expect(layoutSlots(draft, 500)).toHaveLength(5);
    const many = Array.from({ length: 300 }, (_, i) => ({ refName: `c${i}`, length: 100 + i }));
    const slots = layoutSlots(many, 200, 1);
    expect(slots.length).toBeLessThanOrEqual(20);
    expect(slots.map((s) => s.refName)).toContain('c299');
    const names = slots.map((s) => Number(s.refName.slice(1)));
    expect([...names].sort((a, b) => a - b)).toEqual(names);
  });
  it('ignores bad regions and a null width', () => {
    expect(layoutSlots([{ refName: 'x', length: 0 }], 100)).toEqual([]);
    expect(layoutSlots(genome, 0)).toEqual([]);
  });
});

describe('densityRegions', () => {
  const data = {
    bin_size: 1000,
    max: 5,
    truncated: 0,
    tracks: [{ ...track('a'), chroms: [{ refName: 'chr2', counts: [1, 2, 3] }] }],
  };
  it('prefers the assembly regions present in the response', () => {
    expect(densityRegions(data, genome)).toEqual([genome[1]]);
  });
  it('rebuilds the lengths from the bins without them', () => {
    expect(densityRegions(data)).toEqual([{ refName: 'chr2', length: 3000 }]);
    expect(densityRegions({ ...data, tracks: [] })).toEqual([]);
  });
});

describe('bins and pixels', () => {
  const slots = layoutSlots(genome, 1000, 1);
  const [chr1, chr2] = slots;
  it('places a bin and clips the last one to the contig', () => {
    const r = binRect(chr2, 100_000, 2);
    expect(r.x).toBeCloseTo(chr2.x + 200_000 * chr2.pxPerBp);
    const clipped = binRect(chr2, 250_000, 1);
    expect(clipped.width).toBeCloseTo(50_000 * chr2.pxPerBp);
  });
  it('resolves a click to the 1-based bin locus', () => {
    const x = chr1.x + 150_000 * chr1.pxPerBp;
    const hit = binAt(slots, x, 100_000)!;
    expect(hit).toMatchObject({ refName: 'chr1', bin: 1, start: 100_001, end: 200_000 });
    expect(locusString(hit)).toBe('chr1:100001-200000');
  });
  it('clips the last bin to the contig end and clamps inside the slot', () => {
    const hit = binAt(slots, chr2.x + chr2.width - 0.01, 250_000)!;
    expect(hit).toMatchObject({ refName: 'chr2', bin: 1, start: 250_001, end: 300_000 });
  });
  it('misses a separator and falls back to the chromosome without a bin size', () => {
    expect(slotAt(slots, chr1.x + chr1.width + 0.5)).toBeNull();
    expect(binAt(slots, chr1.x + chr1.width + 0.5, 1000)).toBeNull();
    expect(binAt(slots, 5, 0)).toMatchObject({ start: 1, end: 600_000 });
    expect(locusString(chromLocus(chr2))).toBe('chr2:1-300000');
  });
  it('merges sub-pixel bins by their max and skips empty ones', () => {
    const slot = { refName: 'c', length: 1000, x: 10, width: 10, pxPerBp: 0.01 };
    // 100 bp bins are 1 px: ten bins, two non-empty
    expect(pixelRuns([0, 2, 0, 0, 0, 0, 0, 0, 0, 5], slot, 100)).toEqual([
      { x0: 11, x1: 12, count: 2 },
      { x0: 19, x1: 20, count: 5 },
    ]);
    // 25 bp bins are a quarter px: the first two land on the same pixel
    const merged = pixelRuns([1, 4, 2, 0, 0, 0, 3], slot, 25);
    expect(merged).toEqual([
      { x0: 10, x1: 11, count: 4 },
      { x0: 11, x1: 12, count: 2 },
      { x0: 12, x1: 13, count: 3 },
    ]);
  });
});

describe('binOpacity', () => {
  it('is 0 for empty, floored for a lone count and 1 at the max', () => {
    expect(binOpacity(0, 10)).toBe(0);
    expect(binOpacity(5, 0)).toBe(0);
    expect(binOpacity(10, 10)).toBeCloseTo(1);
    expect(binOpacity(1, 10_000)).toBeGreaterThanOrEqual(0.2);
  });
  it('follows the square root and never exceeds 1', () => {
    const mid = binOpacity(25, 100);
    expect(mid).toBeCloseTo(0.2 + 0.8 * 0.5);
    expect(binOpacity(500, 100)).toBeCloseTo(1);
    expect(binOpacity(25, 100)).toBeGreaterThan(binOpacity(4, 100));
  });
});

describe('viewMarkers', () => {
  const slots = layoutSlots(genome, 1000, 1);
  it('maps a visible region to its x-range', () => {
    const [m] = viewMarkers(slots, [{ refName: 'chr2', start: 100_000, end: 200_000 }]);
    expect(m.x).toBeCloseTo(slots[1].x + 100_000 * slots[1].pxPerBp);
    expect(m.width).toBeCloseTo(100_000 * slots[1].pxPerBp);
  });
  it('gives a view across two contigs two marks, and widens a point view', () => {
    const marks = viewMarkers(slots, [
      { refName: 'chr1', start: 590_000, end: 600_000 },
      { refName: 'chr2', start: 0, end: 10_000 },
    ]);
    expect(marks).toHaveLength(2);
    const [narrow] = viewMarkers(slots, [{ refName: 'chr3', start: 10, end: 20 }]);
    expect(narrow.width).toBe(2);
  });
  it('skips contigs without a slot and empty windows', () => {
    expect(viewMarkers(slots, [{ refName: 'nope', start: 0, end: 10 }])).toEqual([]);
    expect(viewMarkers(slots, [{ refName: 'chr1', start: 10, end: 10 }])).toEqual([]);
  });
});

describe('chromLabel', () => {
  it('drops the chr prefix before giving up', () => {
    const wide = { refName: 'chr12', length: 1, x: 0, width: 80, pxPerBp: 1 };
    expect(chromLabel(wide)).toBe('chr12');
    expect(chromLabel({ ...wide, width: 30 })).toBe('12');
    expect(chromLabel({ ...wide, width: 10 })).toBeNull();
  });
});

describe('rows', () => {
  it('groups tracks by run in first-seen order with a separator between runs', () => {
    const rows = densityRows([
      track('s1', 'r1'),
      track('s2', 'r2'),
      track('s3', 'r1'),
      track('s4'),
    ]);
    expect(rows.map((r) => r.track.label)).toEqual(['s1', 's3', 's2', 's4']);
    expect(rows.map((r) => r.separatorBefore)).toEqual([false, false, true, true]);
  });
  it('keeps the order and draws no separator without runs', () => {
    const rows = densityRows([track('b'), track('a')]);
    expect(rows.map((r) => r.track.label)).toEqual(['b', 'a']);
    expect(rows.some((r) => r.separatorBefore)).toBe(false);
  });
  it('sizes rows: 14 for one, 48/n clamped to 3..10, near 64 px at the cap', () => {
    expect(rowHeightFor(1)).toBe(14);
    expect(rowHeightFor(2)).toBe(10);
    expect(rowHeightFor(8)).toBe(6);
    expect(rowHeightFor(16)).toBe(3);
    expect(rowHeightFor(64) * 64).toBeLessThanOrEqual(64);
    expect(rowHeightFor(64)).toBeGreaterThanOrEqual(1);
  });
  it('stacks rows with a gap at each run boundary', () => {
    const rows = densityRows([track('a', 'r1'), track('b', 'r2')]);
    expect(rowTops(rows, 10, 1)).toEqual({ tops: [0, 11], height: 21 });
  });
});

describe('groups', () => {
  it('opens on sample only when every enabled source has a sample column', () => {
    expect(defaultDensityGroup([src('a', { sample_column: 's' }), src('b', { sample_column: 's' })])).toBe(
      'sample',
    );
    expect(defaultDensityGroup([src('a', { sample_column: 's' }), src('b')])).toBe('source');
    expect(defaultDensityGroup([])).toBe('source');
  });
  it('falls back to source past the track cap', () => {
    expect(defaultDensityGroup([src('a', { sample_column: 's' })], 64)).toBe('sample');
    expect(defaultDensityGroup([src('a', { sample_column: 's' })], 65)).toBe('source');
  });
  it('offers only the groupings the sources can serve', () => {
    expect(availableGroups([src('a')])).toEqual(['source']);
    expect(availableGroups([src('a', { sample_column: 's' }), src('b', { run_column: 'r' })])).toEqual([
      'source',
      'sample',
      'run',
    ]);
  });
});

describe('binsBucket', () => {
  it('rounds up to 200s within 200..2000', () => {
    expect(binsBucket(50)).toBe(200);
    expect(binsBucket(201)).toBe(400);
    expect(binsBucket(1234)).toBe(1400);
    expect(binsBucket(9999)).toBe(2000);
    expect(binsBucket(NaN)).toBe(200);
  });
});
