import { describe, expect, it } from 'vitest';

import { resizeIsIdle, type ResizableGraphDiv } from './idleResize';

const drawn = (over: Partial<ResizableGraphDiv> = {}): ResizableGraphDiv => ({
  layout: {},
  _fullLayout: { width: 583, height: 544.2 },
  ...over,
});

describe('resizeIsIdle', () => {
  it('is idle when the box has the size of the last draw', () => {
    expect(resizeIsIdle(drawn(), { width: 583, height: 544.2 })).toBe(true);
  });

  it('tolerates the pixel Plotly tolerates', () => {
    expect(resizeIsIdle(drawn(), { width: 584, height: 543.5 })).toBe(true);
    expect(resizeIsIdle(drawn(), { width: 585, height: 544.2 })).toBe(false);
    expect(resizeIsIdle(drawn(), { width: 583, height: 546 })).toBe(false);
  });

  it('is not idle before the first draw or without a measure', () => {
    expect(resizeIsIdle({ layout: {} }, { width: 583, height: 544 })).toBe(false);
    expect(resizeIsIdle(drawn(), null)).toBe(false);
    expect(resizeIsIdle(drawn(), { width: Number.NaN, height: 544 })).toBe(false);
  });

  it('is not idle for a box below the autosize floor', () => {
    const tiny = drawn({ _fullLayout: { width: 4, height: 4 } });
    expect(resizeIsIdle(tiny, { width: 4, height: 4 })).toBe(false);
  });

  it('leaves a figure with a fixed width or height to Plotly', () => {
    expect(resizeIsIdle(drawn({ layout: { width: 583 } }), { width: 583, height: 544.2 })).toBe(false);
    expect(resizeIsIdle(drawn({ layout: { height: 544 } }), { width: 583, height: 544.2 })).toBe(false);
  });

  it('leaves a figure framed to the window to Plotly', () => {
    const framed = drawn({ _context: { fillFrame: true } });
    expect(resizeIsIdle(framed, { width: 583, height: 544.2 })).toBe(false);
    expect(resizeIsIdle(drawn({ _context: { frameMargins: 0.1 } }), { width: 583, height: 544.2 })).toBe(false);
  });
});
