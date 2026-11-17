import { describe, expect, it } from 'vitest';

import { scrollLanesBy, verticalScrollbars, wheelPixels } from './laneScroll';

/** A fake scrollbar view clamping to `[0, max]` as GenomeSpy's does. */
function bar(max: number, start = 0) {
  const renders = { n: 0 };
  const view: any = {
    name: 'scrollbar-vertical',
    viewportOffset: start,
    context: { animator: { requestRender: () => (renders.n += 1) } },
    setViewportOffset(v: number) {
      view.viewportOffset = Math.min(max, Math.max(0, v));
    },
  };
  return { view, renders };
}

function apiWith(views: unknown[]): any {
  return { debug: { getViewRoot: () => ({ visit: (cb: (v: unknown) => void) => views.forEach(cb) }) } };
}

describe('wheelPixels', () => {
  it('reads pixel, line and page deltas', () => {
    expect(wheelPixels(40, 0)).toBe(40);
    expect(wheelPixels(3, 1)).toBe(48);
    expect(wheelPixels(1, 2, 500)).toBe(500);
    expect(wheelPixels(Number.NaN)).toBe(0);
  });
});

describe('scrollLanesBy', () => {
  it('finds only the vertical scrollbars', () => {
    const { view } = bar(100);
    const other = { name: 'scrollbar-horizontal', viewportOffset: 0, setViewportOffset() {} };
    expect(verticalScrollbars(apiWith([view, other, { name: 'unit' }, null]))).toEqual([view]);
  });

  it('moves the lanes, clamped, and asks for a render', () => {
    const { view, renders } = bar(100);
    const api = apiWith([view]);
    expect(scrollLanesBy(api, 60)).toBe(true);
    expect(view.viewportOffset).toBe(60);
    expect(scrollLanesBy(api, 60)).toBe(true);
    expect(view.viewportOffset).toBe(100);
    expect(renders.n).toBe(2);
  });

  it('says no at the end of the lanes, so the page can take the wheel', () => {
    const { view } = bar(100, 100);
    expect(scrollLanesBy(apiWith([view]), 30)).toBe(false);
    const top = bar(100, 0);
    expect(scrollLanesBy(apiWith([top.view]), -30)).toBe(false);
    // Back up from the end is a move.
    expect(scrollLanesBy(apiWith([view]), -30)).toBe(true);
    expect(view.viewportOffset).toBe(70);
  });

  it('says no with nothing to scroll or no debug hook', () => {
    expect(scrollLanesBy(apiWith([]), 30)).toBe(false);
    expect(scrollLanesBy({} as any, 30)).toBe(false);
    expect(scrollLanesBy(null, 30)).toBe(false);
    expect(scrollLanesBy(apiWith([bar(100).view]), 0)).toBe(false);
    expect(scrollLanesBy({ debug: { getViewRoot: () => { throw new Error('x'); } } } as any, 5)).toBe(false);
  });
});
