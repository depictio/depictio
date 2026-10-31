import { describe, expect, it } from 'vitest';

import {
  clampFit,
  collectTrackDisplays,
  collectViewTracks,
  contentHeight,
  fitDisplaysToContent,
  fitTarget,
  FIT_MAX_PX,
  FIT_MIN_PX,
  maxFitPx,
  type DisplayLike,
} from './fitToContent';

/** Layout rectangles as `GranularRectLayout.getRectangles()` gives them. */
const rects = (...bottoms: number[]) => ({
  values: () => bottoms.map((b, i) => [0, b - 10, 5, b, { i }]),
});

/** A display that records `setHeight`. */
function display(fields: DisplayLike): DisplayLike & { calls: number[] } {
  const calls: number[] = [];
  return { height: 100, setHeight: (px: number) => calls.push(px), calls, ...fields };
}

describe('clampFit / maxFitPx', () => {
  it('holds a height between the minimum and the maximum, whole pixels', () => {
    expect(clampFit(10)).toBe(FIT_MIN_PX);
    expect(clampFit(123.2)).toBe(124);
    expect(clampFit(5000)).toBe(FIT_MAX_PX);
    expect(clampFit(5000, 300)).toBe(300);
  });
  it('caps a track at the tile height, between 160 and 600', () => {
    expect(maxFitPx(420)).toBe(420);
    expect(maxFitPx(90)).toBe(160);
    expect(maxFitPx(2000)).toBe(600);
    expect(maxFitPx(0)).toBe(600);
  });
});

describe('contentHeight', () => {
  it('feature tracks: lowest laid-out feature plus the room for its label', () => {
    const d = display({ type: 'LinearBasicDisplay', layoutFeatures: rects(27, 140) });
    expect(contentHeight(d)).toBe(156);
    expect(contentHeight(display({ type: 'LinearVariantDisplay', layoutFeatures: rects() }))).toBeNull();
  });
  it('alignments: coverage height plus the pileup rows actually used', () => {
    const d = display({
      type: 'LinearAlignmentsDisplay',
      SNPCoverageDisplay: { type: 'LinearSNPCoverageDisplay', height: 50 },
      PileupDisplay: { type: 'LinearPileupDisplay', layoutFeatures: rects(30, 90) },
    });
    // 50 + 90 + 4 below the last row, no label padding on reads.
    expect(contentHeight(d)).toBe(144);
  });
  it('alignments: default coverage height, and nothing before the reads are laid out', () => {
    const loaded = display({
      type: 'LinearAlignmentsDisplay',
      PileupDisplay: { type: 'LinearPileupDisplay', layoutFeatures: rects(20) },
    });
    expect(contentHeight(loaded)).toBe(45 + 20 + 4);
    const empty = display({
      type: 'LinearAlignmentsDisplay',
      PileupDisplay: { type: 'LinearPileupDisplay', layoutFeatures: rects() },
    });
    expect(contentHeight(empty)).toBeNull();
  });
  it('a read cloud lower panel brings its own stack height', () => {
    const d = display({
      type: 'LinearAlignmentsDisplay',
      SNPCoverageDisplay: { height: 45 },
      PileupDisplay: { type: 'LinearReadCloudDisplay', layoutHeight: 200 },
    });
    expect(contentHeight(d)).toBe(245);
    const arcs = display({
      type: 'LinearAlignmentsDisplay',
      PileupDisplay: { type: 'LinearReadArcsDisplay' },
    });
    expect(contentHeight(arcs)).toBeNull();
  });
  it('multi-sample variants: one row per sample, auto rows at 10 px', () => {
    const auto = display({
      type: 'MultiLinearVariantDisplay',
      sources: new Array(24).fill({}),
      rowHeightMode: 'auto',
      lineZoneHeight: 20,
    });
    expect(contentHeight(auto)).toBe(20 + 24 * 10);
    const fixed = display({
      type: 'LinearVariantMatrixDisplay',
      sources: new Array(5).fill({}),
      rowHeightMode: 14,
    });
    expect(contentHeight(fixed)).toBe(70);
  });
  it('signal and coverage displays keep their height', () => {
    expect(contentHeight(display({ type: 'LinearWiggleDisplay' }))).toBeNull();
    expect(
      contentHeight(display({ type: 'MultiLinearWiggleDisplay', sources: [{}, {}], layoutFeatures: rects(500) })),
    ).toBeNull();
    expect(contentHeight(display({ type: 'LinearSNPCoverageDisplay' }))).toBeNull();
    expect(contentHeight(display({}))).toBeNull();
  });
  it('survives a view that throws', () => {
    const d = display({ type: 'LinearBasicDisplay' });
    Object.defineProperty(d, 'layoutFeatures', {
      get() {
        throw new Error('view not initialized yet');
      },
    });
    expect(contentHeight(d)).toBeNull();
  });
});

describe('fitTarget / fitDisplaysToContent', () => {
  it('clamps a dense pileup to the maximum and a sparse track to the minimum', () => {
    const dense = display({
      type: 'LinearAlignmentsDisplay',
      PileupDisplay: { type: 'LinearPileupDisplay', layoutFeatures: rects(4000) },
    });
    expect(fitTarget(dense)).toBe(FIT_MAX_PX);
    expect(fitTarget(dense, 300)).toBe(300);
    // A single gene: 26 + 16 label, under the minimum.
    expect(fitTarget(display({ type: 'LinearBasicDisplay', layoutFeatures: rects(10) }))).toBe(FIT_MIN_PX);
  });
  it('leaves a track already on its fit alone', () => {
    const d = display({ type: 'LinearBasicDisplay', layoutFeatures: rects(84), height: 100 });
    expect(fitTarget(d)).toBeNull();
  });
  it('sets every fittable display and skips the rest', () => {
    const genes = display({ type: 'LinearBasicDisplay', layoutFeatures: rects(184) });
    const reads = display({
      type: 'LinearAlignmentsDisplay',
      PileupDisplay: { type: 'LinearPileupDisplay', layoutFeatures: rects(60) },
    });
    const signal = display({ type: 'LinearWiggleDisplay' });
    expect(fitDisplaysToContent([genes, reads, signal])).toBe(2);
    expect(genes.calls).toEqual([200]);
    expect(reads.calls).toEqual([109]);
    expect(signal.calls).toEqual([]);
  });
});

describe('collecting displays', () => {
  it('takes the tracks of a view and of the linear views nested in it', () => {
    const t1 = { displays: [{ type: 'a' }] };
    const t2 = { displays: [{ type: 'b' }] };
    const t3 = { displays: [] };
    const nested = { tracks: [t2], views: [] };
    const split = { tracks: [t1], views: [nested, nested] };
    const tracks = collectViewTracks(split);
    expect(tracks).toEqual([t1, t2]);
    expect(collectTrackDisplays([...tracks, t3]).map((d) => d.type)).toEqual(['a', 'b']);
    expect(collectViewTracks(undefined)).toEqual([]);
  });
});
