import { describe, expect, it } from 'vitest';

import { edgeHit, fittedHeight, layoutBottom, trackIdOfContainer } from './useFitTrackOnDoubleClick';

describe('fit a track on a double click', () => {
  it('reads the track id off its rendering container', () => {
    expect(trackIdOfContainer('trackRenderingContainer-lgv-loc-browser-hg38-genes', 'lgv-loc-browser')).toBe(
      'hg38-genes',
    );
    expect(trackIdOfContainer('trackRenderingContainer-other-x', 'lgv-loc-browser')).toBeNull();
    expect(trackIdOfContainer(undefined, 'lgv')).toBeNull();
  });
  it('fits to the content, capped, and leaves a fitted track alone', () => {
    expect(fittedHeight(354, 100)).toBe(354);
    expect(fittedHeight(40, 100)).toBe(40);
    expect(fittedHeight(5000, 100)).toBe(1200);
    expect(fittedHeight(100.4, 100)).toBeNull();
  });
  it('reads the content height off the layout, label included', () => {
    expect(layoutBottom([[0, 0, 5, 27], [0, 27, 5, 140, {}]])).toBe(156);
    expect(layoutBottom([])).toBe(0);
  });
  it('finds the track whose bottom edge the click sits on, gap included', () => {
    const boxes = [
      { left: 0, right: 800, bottom: 100 },
      { left: 0, right: 800, bottom: 220 },
    ];
    expect(edgeHit(boxes, 400, 97)).toBe(0);
    expect(edgeHit(boxes, 400, 108)).toBe(0);
    expect(edgeHit(boxes, 400, 150)).toBe(-1);
    expect(edgeHit(boxes, 400, 224)).toBe(1);
    expect(edgeHit(boxes, 900, 100)).toBe(-1);
  });
});
