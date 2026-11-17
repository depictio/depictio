import { describe, expect, it } from 'vitest';

import { layoutPanels, type ChromBar, type IdeogramFeature } from './ideogramLayout';
import {
  autoBinSizeMedian,
  binAlpha,
  binAt,
  binBreakdown,
  binFeatures,
  binSpan,
  binValue,
  bpToX,
  buildChromIndex,
  centreWindow,
  clampWindow,
  countOverlapping,
  detailLayout,
  dominantCategory,
  formatBpAt,
  fullWindow,
  hitBar,
  lodDecision,
  lowerBound,
  minSpanFor,
  nearestFeature,
  niceStep,
  overlapping,
  panWindow,
  screenBinSize,
  wheelZoomFactor,
  windowLabel,
  windowTicks,
  xToBp,
  zoomLevel,
  zoomWindow,
} from './ideogramView';

let row = 0;
function feature(over: Partial<IdeogramFeature>): IdeogramFeature {
  row += 1;
  return {
    chrom: 'chr1',
    start: 0,
    end: 0,
    value: null,
    category: null,
    sample: null,
    label: null,
    chromLength: null,
    row,
    ...over,
  };
}

describe('lodDecision', () => {
  const opts = { lodThreshold: 100, maxFeatures: 1000 };
  it('auto draws marks while few features are in view and bins above the threshold', () => {
    expect(lodDecision('auto', 100, opts)).toEqual({ drawn: 'marks', guarded: false });
    expect(lodDecision('auto', 101, opts)).toEqual({ drawn: 'density', guarded: false });
  });
  it('marks keeps its meaning: marks up to the max_features guard, reported past it', () => {
    expect(lodDecision('marks', 1000, opts)).toEqual({ drawn: 'marks', guarded: false });
    expect(lodDecision('marks', 1001, opts)).toEqual({ drawn: 'density', guarded: true });
  });
  it('density is always bins, and auto never exceeds the guard', () => {
    expect(lodDecision('density', 1, opts).drawn).toBe('density');
    expect(lodDecision('auto', 500, { lodThreshold: 5000, maxFeatures: 400 }).drawn).toBe('density');
  });
});

describe('bin sizes', () => {
  it('niceStep rounds up to 1-2-5 steps', () => {
    expect(niceStep(0.3)).toBe(1);
    expect(niceStep(3)).toBe(5);
    expect(niceStep(11)).toBe(20);
    expect(niceStep(2000)).toBe(2000);
    expect(niceStep(5001)).toBe(10000);
  });
  it('autoBinSizeMedian sizes bins for the median chromosome, at least 1 kb', () => {
    // median 50 Mb / 50 bins = 1 Mb
    expect(autoBinSizeMedian([10e6, 50e6, 250e6], 50)).toBe(1_000_000);
    expect(autoBinSizeMedian([123_456_789], 50)).toBe(2_000_000);
    expect(autoBinSizeMedian([5000], 50)).toBe(1000);
    expect(autoBinSizeMedian([], 50)).toBe(1_000_000);
  });
  it('screenBinSize gives about pxPerBin pixels a bin', () => {
    // 1 Mb over 1000 px at 4 px a bin: 4 kb -> 5 kb
    expect(screenBinSize(1e6, 1000, 4)).toBe(5000);
    expect(screenBinSize(100, 1000, 4)).toBe(1);
    expect(screenBinSize(1e6, 0)).toBe(1);
  });
});

describe('chromosome index', () => {
  const fs = [
    feature({ chrom: 'chr2', start: 500, end: 600 }),
    feature({ chrom: 'chr1', start: 300, end: 310 }),
    feature({ chrom: '1', start: 10, end: 2000 }),
    feature({ chrom: 'chr1', start: 100, end: 100 }),
    feature({ chrom: 'chr1', start: 900, end: 950, category: 'hidden' }),
  ];
  const index = buildChromIndex(fs, (f) => f.category !== 'hidden');
  const c1 = index.get('1')!;

  it('groups by folded chromosome key, sorted by start, skipping what keep drops', () => {
    expect([...index.keys()].sort()).toEqual(['1', '2']);
    expect(Array.from(c1.starts)).toEqual([10, 100, 300]);
    expect(c1.maxLen).toBe(1990);
  });
  it('finds every feature overlapping a span, a long one starting before it too', () => {
    expect(overlapping(c1, 150, 400).map((k) => fs[c1.order[k]].start)).toEqual([10, 300]);
    expect(countOverlapping(c1, 100, 100)).toBe(2);
    expect(countOverlapping(c1, 2001, 3000)).toBe(0);
    expect(countOverlapping(undefined, 0, 1)).toBe(0);
  });
  it('lowerBound is a binary search', () => {
    const arr = Float64Array.from([1, 3, 3, 7]);
    expect([0, 1, 3, 4, 8].map((x) => lowerBound(arr, x))).toEqual([0, 0, 1, 3, 4]);
  });
});

describe('binFeatures', () => {
  const fs = [
    feature({ start: 0, end: 10, category: 'a' }),
    feature({ start: 20, end: 30, category: 'b' }),
    feature({ start: 40, end: 50, category: 'b' }),
    feature({ start: 150, end: 160, category: 'a' }),
    feature({ start: 400, end: 900, category: 'a', value: 7 }),
  ];
  const idx = buildChromIndex(fs).get('1');
  const catOf = (f: IdeogramFeature) => (f.category === 'a' ? 0 : f.category === 'b' ? 1 : -1);

  it('counts by midpoint and tallies the dominant category per bin', () => {
    const bins = binFeatures(fs, idx, { start: 0, end: 1000, binSize: 100, catOf, nCats: 2 });
    expect(Array.from(bins.count.slice(0, 7))).toEqual([3, 1, 0, 0, 0, 0, 1]);
    expect(bins.maxCount).toBe(3);
    expect(dominantCategory(bins, 0)).toBe(1);
    expect(binBreakdown(bins, 0)).toEqual([
      { cat: 1, count: 2 },
      { cat: 0, count: 1 },
    ]);
    expect(binSpan(bins, 1)).toEqual([100, 200]);
    expect(binValue(bins, 0, false)).toBe(3);
    expect(dominantCategory(bins, 2)).toBe(-1);
  });
  it('averages a value and keeps rows at least a bin wide as their own band', () => {
    const valued = [
      feature({ start: 0, end: 10, value: 2 }),
      feature({ start: 10, end: 20, value: 4 }),
      feature({ start: 50, end: 60, value: null }),
      feature({ start: 100, end: 400, value: 9 }),
    ];
    const vidx = buildChromIndex(valued).get('1');
    const bins = binFeatures(valued, vidx, { start: 0, end: 400, binSize: 100, useValue: true, keepWide: true });
    expect(binValue(bins, 0, true)).toBe(3);
    expect(bins.count[0]).toBe(2); // the row with no value is skipped
    expect(bins.wide.map((i) => valued[i].start)).toEqual([100]);
    expect([bins.minValue, bins.maxValue]).toEqual([3, 9]);
    expect(Number.isNaN(binValue(bins, 2, true))).toBe(true);
  });
  it('aligns bins on multiples of the bin size for a span that starts mid-chromosome', () => {
    const bins = binFeatures(fs, idx, { start: 130, end: 260, binSize: 100 });
    expect(bins.origin).toBe(100);
    expect(bins.count.length).toBe(2);
    expect(bins.count[0]).toBe(1);
  });
  it('survives no index at all', () => {
    const bins = binFeatures(fs, undefined, { start: 0, end: 10, binSize: 5 });
    expect(bins.maxCount).toBe(0);
    expect([bins.minValue, bins.maxValue]).toEqual([0, 0]);
  });
  it('binAlpha has a floor, rises with the count and scales with opacity', () => {
    expect(binAlpha(0, 10, 1)).toBe(0);
    expect(binAlpha(10, 10, 1)).toBeCloseTo(1);
    expect(binAlpha(1, 10, 1)).toBeCloseTo(0.235);
    expect(binAlpha(10, 10, 0.5)).toBeCloseTo(0.5);
  });
  it('binAt finds a wide row, a filled bin, or the nearest within tolerance', () => {
    const bins = binFeatures(fs, idx, { start: 0, end: 1000, binSize: 100, keepWide: true });
    expect(binAt(bins, fs, 500)).toEqual({ kind: 'wide', feature: 4 });
    expect(binAt(bins, fs, 50)).toEqual({ kind: 'bin', bin: 0 });
    expect(binAt(bins, fs, 250)).toBeNull();
    expect(binAt(bins, fs, 250, 100)).toEqual({ kind: 'bin', bin: 1 });
  });
});

describe('detail window', () => {
  const L = 1_000_000;
  it('zooms about the anchor so the position under the cursor stays put', () => {
    const w = zoomWindow(fullWindow(L), 4, 250_000, L);
    expect(w.end - w.start).toBe(250_000);
    // anchor at 25% of the old window stays at 25% of the new one
    expect((250_000 - w.start) / (w.end - w.start)).toBeCloseTo(0.25);
    const back = zoomWindow(w, 0.25, 250_000, L);
    expect(back).toEqual({ start: 0, end: L });
  });
  it('never zooms past the minimum span or out past the chromosome', () => {
    const tiny = zoomWindow({ start: 1000, end: 1100 }, 100, 1050, L);
    expect(tiny.end - tiny.start).toBe(minSpanFor(L));
    expect(zoomWindow(fullWindow(L), 0.1, 10, L)).toEqual({ start: 0, end: L });
    expect(minSpanFor(20)).toBe(20);
  });
  it('pans and stops at the ends without changing the width', () => {
    expect(panWindow({ start: 100, end: 200 }, 50, 1000)).toEqual({ start: 150, end: 250 });
    expect(panWindow({ start: 100, end: 200 }, -500, 1000)).toEqual({ start: 0, end: 100 });
    expect(panWindow({ start: 800, end: 900 }, 500, 1000)).toEqual({ start: 900, end: 1000 });
    expect(centreWindow({ start: 0, end: 100 }, 500, 1000)).toEqual({ start: 450, end: 550 });
  });
  it('clampWindow widens a too-narrow window about its centre', () => {
    expect(clampWindow({ start: 500, end: 510 }, 1000, 100)).toEqual({ start: 455, end: 555 });
    expect(clampWindow({ start: -50, end: 2000 }, 1000)).toEqual({ start: 0, end: 1000 });
  });
  it('maps bp to x and back, and reports the zoom level', () => {
    const w = { start: 1000, end: 2000 };
    expect(bpToX(1500, w, 10, 200)).toBe(110);
    expect(xToBp(110, w, 10, 200)).toBe(1500);
    expect(zoomLevel(w, 10_000)).toBe(10);
    expect(zoomLevel(fullWindow(500), 500)).toBe(1);
  });
  it('wheel zoom: up zooms in, down zooms out, lines count as pixels', () => {
    expect(wheelZoomFactor(-100)).toBeGreaterThan(1);
    expect(wheelZoomFactor(100)).toBeLessThan(1);
    expect(wheelZoomFactor(-3, 1)).toBeCloseTo(wheelZoomFactor(-48));
    expect(wheelZoomFactor(0)).toBe(1);
  });
});

describe('detail geometry and axis', () => {
  it('stacks the locator, the body and the axis inside the canvas', () => {
    const g = detailLayout(800, 300);
    expect(g.locator.y + g.locator.h).toBeLessThan(g.body.y);
    expect(g.body.h).toBeLessThanOrEqual(96);
    expect(g.body.y - (g.locator.y + g.locator.h)).toBeLessThanOrEqual(40);
    expect(g.axisY).toBeGreaterThan(g.body.y + g.body.h);
    expect(g.axisY + 20).toBeLessThanOrEqual(300);
    expect(g.body.x + g.body.w).toBe(800 - g.body.x);
  });
  it('ticks the window in 1-2-5 steps with labels precise enough to differ', () => {
    const ticks = windowTicks({ start: 1_200_000, end: 1_300_000 }, 0, 600, 100);
    const labels = ticks.map((t) => t.label);
    expect(new Set(labels).size).toBe(labels.length);
    expect(ticks[0].pos).toBeGreaterThanOrEqual(1_200_000);
    expect(ticks.every((t) => t.x >= 0 && t.x <= 600)).toBe(true);
    expect(windowTicks({ start: 0, end: 0 }, 0, 600)).toEqual([]);
  });
  it('formats positions by the tick step', () => {
    expect(formatBpAt(0, 10)).toBe('0');
    expect(formatBpAt(25_000_000, 5e6)).toBe('25 Mb');
    expect(formatBpAt(1_250_000, 10_000)).toBe('1.25 Mb');
    expect(formatBpAt(12_500, 500)).toBe('12,500 bp');
    expect(formatBpAt(120_000, 10_000)).toBe('120 kb');
  });
  it('labels the window as a locus, or the whole chromosome by its length', () => {
    expect(windowLabel('chr1', { start: 0, end: 5e6 }, 5e6)).toBe('chr1 · 5.0 Mb');
    expect(windowLabel('chr1', { start: 1e6, end: 2e6 }, 5e6)).toBe('chr1:1.00 Mb–2.00 Mb');
  });
});

describe('hit-testing', () => {
  const bars: ChromBar[] = [
    { name: 'chr1', key: '1', length: 1000, source: 'data' },
    { name: 'chr2', key: '2', length: 500, source: 'data' },
  ];

  it('finds the bar and the position under the pointer, its name as a handle', () => {
    const [panel] = layoutPanels([{ title: null, bars }], { width: 600, height: 200, orientation: 'horizontal' });
    const g = panel.bars[1];
    const mid = hitBar([panel], g.x + g.w / 2, g.y + g.h / 2);
    expect(mid).toMatchObject({ panel: 0, bar: 1, onLabel: false });
    expect(mid!.pos).toBeCloseTo(250, -1);
    expect(hitBar([panel], panel.x + 2, g.y + g.h / 2)).toMatchObject({ bar: 1, onLabel: true });
    // Past the end of the shorter bar there is nothing to hit.
    expect(hitBar([panel], g.x + g.w + 40, g.y + g.h / 2)).toBeNull();
    expect(hitBar([panel], 5000, 5000)).toBeNull();
  });

  it('hit-tests vertical bars along y, names underneath', () => {
    const [panel] = layoutPanels([{ title: null, bars }], { width: 300, height: 300, orientation: 'vertical' });
    const g = panel.bars[0];
    expect(hitBar([panel], g.x + g.w / 2, g.y + 10)).toMatchObject({ bar: 0, onLabel: false });
    expect(hitBar([panel], g.x + g.w / 2, g.labelY - 4)).toMatchObject({ bar: 0, onLabel: true });
  });

  it('picks the feature containing the position, the narrowest among several, else the closest', () => {
    const fs = [
      feature({ start: 0, end: 1000 }),
      feature({ start: 400, end: 420 }),
      feature({ start: 600, end: 600 }),
    ];
    const idx = buildChromIndex(fs).get('1');
    expect(nearestFeature(fs, idx, 410, 5)).toBe(1);
    expect(nearestFeature(fs, idx, 100, 5)).toBe(0);
    const pts = [feature({ start: 100, end: 100 }), feature({ start: 130, end: 130 })];
    const pidx = buildChromIndex(pts).get('1');
    expect(nearestFeature(pts, pidx, 122, 10)).toBe(1);
    expect(nearestFeature(pts, pidx, 115, 2)).toBe(-1);
    expect(nearestFeature(pts, undefined, 115, 2)).toBe(-1);
  });
});
