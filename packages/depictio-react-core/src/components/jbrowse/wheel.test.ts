import { describe, expect, it } from 'vitest';

import { canScrollBy, wheelIntent, wheelPixels, zoomFactor } from './wheel';

const wheel = (over: Partial<Parameters<typeof wheelIntent>[0]> = {}) => ({
  deltaX: 0,
  deltaY: 100,
  deltaMode: 0,
  ctrlKey: false,
  metaKey: false,
  ...over,
});

describe('wheelIntent', () => {
  it('sends a plain vertical wheel to the dashboard when guarded', () => {
    expect(wheelIntent(wheel(), true)).toBe('page');
    expect(wheelIntent(wheel(), false)).toBe('native');
  });

  it('leaves Ctrl + wheel and pinch to JBrowse', () => {
    expect(wheelIntent(wheel({ ctrlKey: true }), true)).toBe('native');
    expect(wheelIntent(wheel({ ctrlKey: true, metaKey: true }), true)).toBe('native');
  });

  it('zooms on Cmd + wheel, guard or not', () => {
    expect(wheelIntent(wheel({ metaKey: true }), true)).toBe('zoom');
    expect(wheelIntent(wheel({ metaKey: true }), false)).toBe('zoom');
  });

  it('leaves a horizontal swipe to JBrowse, which pans', () => {
    expect(wheelIntent(wheel({ deltaX: 40, deltaY: 10 }), true)).toBe('native');
  });
});

describe('wheelPixels', () => {
  it('converts lines and pages to pixels', () => {
    expect(wheelPixels(wheel({ deltaY: 3, deltaMode: 1 }), 800)).toBe(48);
    expect(wheelPixels(wheel({ deltaY: 1, deltaMode: 2 }), 800)).toBe(800);
    expect(wheelPixels(wheel({ deltaY: 12 }), 800)).toBe(12);
  });
});

describe('zoomFactor', () => {
  it('zooms out on wheel down and back in symmetrically', () => {
    expect(zoomFactor(100)).toBeGreaterThan(1);
    expect(zoomFactor(-100)).toBeLessThan(1);
    expect(zoomFactor(100) * zoomFactor(-100)).toBeCloseTo(1);
  });
});

describe('canScrollBy', () => {
  const box = (scrollTop: number) => ({ scrollTop, scrollHeight: 600, clientHeight: 200 });
  it('scrolls the tracks until their edge, then hands over', () => {
    expect(canScrollBy(box(0), 100)).toBe(true);
    expect(canScrollBy(box(0), -100)).toBe(false);
    expect(canScrollBy(box(400), 100)).toBe(false);
    expect(canScrollBy(box(400), -100)).toBe(true);
  });
  it('never scrolls a box that fits', () => {
    expect(canScrollBy({ scrollTop: 0, scrollHeight: 200, clientHeight: 200 }, 100)).toBe(false);
  });
});
