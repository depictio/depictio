import { describe, expect, it } from 'vitest';
import { clampAxisLineWidth, effectivePointSize, outlineColour } from './embeddingStyle';

describe('effectivePointSize', () => {
  it('draws an explicit size at any point count', () => {
    expect(effectivePointSize(7, 4355)).toBe(7);
    expect(effectivePointSize(25, 80)).toBe(25);
  });

  it('shrinks to 4 px past 1,000 points only when no size is set', () => {
    expect(effectivePointSize(null, 4355)).toBe(4);
    expect(effectivePointSize(undefined, 1000)).toBe(6);
    expect(effectivePointSize(null, 90)).toBe(6);
  });
});

describe('outlineColour', () => {
  it('keeps the text colour by default', () => {
    expect(outlineColour(undefined, false, '#222')).toBe('#222');
    expect(outlineColour('contrast', true, '#eee')).toBe('#eee');
  });

  it('takes the page colour in background mode', () => {
    expect(outlineColour('background', false, '#222')).toBe('#ffffff');
    expect(outlineColour('background', true, '#eee')).toBe('#1a1b1e');
  });
});

describe('clampAxisLineWidth', () => {
  it('keeps 1 px by default and clamps to 1-6', () => {
    expect(clampAxisLineWidth(undefined)).toBe(1);
    expect(clampAxisLineWidth(3)).toBe(3);
    expect(clampAxisLineWidth(10)).toBe(6);
    expect(clampAxisLineWidth(0)).toBe(1);
  });
});
