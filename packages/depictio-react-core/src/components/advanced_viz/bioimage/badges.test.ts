import { describe, expect, it } from 'vitest';

import { axisLines, formatBytes, groupDigits, sizeSummary, type BadgeImageInfo } from './BioimageBadges';

const SLIDE: BadgeImageInfo = {
  labels: ['t', 'c', 'z', 'y', 'x'],
  shape: [1, 3, 1, 55296, 96000],
  dtype: 'Uint8',
  levels: 7,
  width: 96000,
  height: 55296,
  sizes: { c: 3, z: 1, t: 1 },
  physicalSize: { value: 0.4500000001, unit: 'µm' },
};

describe('size badge', () => {
  it('says the size of a whole slide in words, not axis letters', () => {
    expect(sizeSummary(SLIDE)).toBe('96 000 × 55 296 · RGB · 0.45 µm/px');
  });

  it('names channels, planes and time points when there are several', () => {
    const stack: BadgeImageInfo = {
      ...SLIDE,
      shape: [40, 4, 18, 512, 512],
      dtype: 'Uint16',
      width: 512,
      height: 512,
      sizes: { c: 4, z: 18, t: 40 },
      physicalSize: null,
    };
    expect(sizeSummary(stack)).toBe('512 × 512 · 4 ch · 18 z · 40 t');
  });

  it('lists each axis with its size and step, and the uncompressed size', () => {
    expect(axisLines({ ...SLIDE, tStep: { value: 60, unit: 's' } })).toEqual([
      't: 1 time points, 60 s each',
      'c: 3 channels',
      'z: 1 planes',
      'y: 55 296 px, 0.45 µm each',
      'x: 96 000 px, 0.45 µm each',
    ]);
    expect(formatBytes(3 * 55296 * 96000)).toBe('15.9 GB');
    expect(groupDigits(999)).toBe('999');
  });
});
