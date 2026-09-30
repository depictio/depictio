import { describe, expect, it } from 'vitest';

import { fitCellWidth, lettersFit, rulerStep, scrollToReveal, visibleWindow } from './canvas';

describe('visibleWindow', () => {
  it('returns the cells in view plus overscan, clamped', () => {
    expect(visibleWindow(0, 100, 10, 50, 1)).toEqual([0, 10]);
    expect(visibleWindow(205, 100, 10, 50, 1)).toEqual([19, 31]);
    expect(visibleWindow(450, 100, 10, 50, 1)).toEqual([44, 49]);
  });

  it('is empty with nothing to show', () => {
    expect(visibleWindow(0, 100, 10, 0)).toEqual([0, -1]);
    expect(visibleWindow(0, 0, 10, 5)).toEqual([0, -1]);
  });

  it('stays small for a 500 x 1500 alignment at any scroll', () => {
    const [c0, c1] = visibleWindow(9000, 800, 12, 1500, 1);
    const [r0, r1] = visibleWindow(3000, 400, 14, 500, 1);
    expect(c1 - c0 + 1).toBeLessThanOrEqual(70);
    expect(r1 - r0 + 1).toBeLessThanOrEqual(32);
  });
});

describe('sizing helpers', () => {
  it('fits cells to the viewport within bounds', () => {
    expect(fitCellWidth(1000, 100)).toBe(10);
    expect(fitCellWidth(100, 1500)).toBe(1);
    expect(fitCellWidth(1000, 10)).toBe(16);
    expect(fitCellWidth(100, 1000, 0.05)).toBeCloseTo(0.1);
  });

  it('shows letters only on wide enough cells', () => {
    expect(lettersFit(8, 14)).toBe(true);
    expect(lettersFit(4, 14)).toBe(false);
    expect(lettersFit(10, 6)).toBe(false);
  });

  it('picks a 1-2-5 ruler step that keeps labels apart', () => {
    expect(rulerStep(10)).toBe(5);
    expect(rulerStep(2)).toBe(50);
    expect(rulerStep(1)).toBe(50);
    expect(rulerStep(0.3)).toBe(200);
    expect(rulerStep(100)).toBe(1);
  });
});

describe('scrollToReveal', () => {
  it('leaves a visible span alone', () => {
    expect(scrollToReveal(100, 200, 150, 200)).toBeNull();
  });

  it('centres a span that is off screen', () => {
    expect(scrollToReveal(0, 200, 500, 520)).toBe(410);
  });

  it('aligns a span wider than the viewport on its start', () => {
    expect(scrollToReveal(0, 200, 500, 900)).toBe(484);
  });
});
