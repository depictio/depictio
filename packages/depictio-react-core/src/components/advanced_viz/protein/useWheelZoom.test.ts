import { describe, expect, it } from 'vitest';

import { isApplePlatform, scrollLeftAfterZoom, zoomModifierLabel, zoomStep } from './useWheelZoom';

describe('zoomStep', () => {
  it('zooms in on a negative delta and out on a positive one', () => {
    expect(zoomStep(8, -100, 1, 16)).toBeGreaterThan(8);
    expect(zoomStep(8, 100, 1, 16)).toBeLessThan(8);
  });

  it('is multiplicative: the same delta scales by the same factor at any width', () => {
    expect(zoomStep(4, -60, 1, 100) / 4).toBeCloseTo(zoomStep(20, -60, 1, 100) / 20, 10);
  });

  it('clamps to the range', () => {
    expect(zoomStep(15.9, -2000, 1, 16)).toBe(16);
    expect(zoomStep(1.1, 2000, 1, 16)).toBe(1);
  });

  it('leaves the width alone on a zero delta', () => {
    expect(zoomStep(7, 0, 1, 16)).toBe(7);
  });

  it('reads line-mode deltas as 16 px each', () => {
    expect(zoomStep(8, -3, 1, 40, 1)).toBeCloseTo(zoomStep(8, -48, 1, 40, 0), 10);
  });
});

describe('scrollLeftAfterZoom', () => {
  it('keeps the column under the cursor in place', () => {
    // 100 px gutter, cursor 300 px in, view scrolled 500 px, 5 px columns: column 140.
    const next = scrollLeftAfterZoom(500, 300, 100, 5, 10);
    const colBefore = (500 + 300 - 100) / 5;
    const colAfter = (next + 300 - 100) / 10;
    expect(colAfter).toBeCloseTo(colBefore, 10);
  });

  it('anchors on the first grid column when the cursor is over the gutter', () => {
    const next = scrollLeftAfterZoom(200, 20, 100, 4, 8);
    expect((next + 100 - 100) / 8).toBeCloseTo((200 + 100 - 100) / 4, 10);
  });

  it('never scrolls below zero', () => {
    expect(scrollLeftAfterZoom(0, 50, 0, 10, 2)).toBe(0);
  });

  it('keeps the scroll on a degenerate width', () => {
    expect(scrollLeftAfterZoom(120, 10, 0, 0, 5)).toBe(120);
  });
});

describe('zoomModifierLabel', () => {
  it('names the Command key on a Mac and Ctrl elsewhere', () => {
    expect(zoomModifierLabel({ platform: 'MacIntel', userAgent: '' })).toBe('\u2318');
    expect(zoomModifierLabel({ userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)' })).toBe(
      '\u2318',
    );
    expect(zoomModifierLabel({ platform: 'Win32', userAgent: 'Mozilla/5.0 (Windows NT 10.0)' })).toBe(
      'Ctrl',
    );
    expect(zoomModifierLabel({ platform: 'Linux x86_64' })).toBe('Ctrl');
  });

  it('falls back to Ctrl when there is no navigator', () => {
    expect(isApplePlatform({})).toBe(false);
    expect(zoomModifierLabel({})).toBe('Ctrl');
  });
});
