import { describe, expect, it } from 'vitest';

import {
  baseRibbonHeight,
  chosenRibbonHeight,
  DEFAULT_RIBBON_PX,
  mainRibbonLaneHeight,
  MAIN_RIBBON_MAX_PX,
} from './ribbonHeight';

describe('mainRibbonLaneHeight', () => {
  it('draws a chosen height exactly, whatever room is spare', () => {
    for (const h of [16, 24, 30, 40, 52, 64]) {
      expect(mainRibbonLaneHeight(h, 0, 1)).toBe(h);
      expect(mainRibbonLaneHeight(h, 400, 1)).toBe(h);
      expect(mainRibbonLaneHeight(h, 400, 0.35)).toBe(h);
    }
  });

  it('keeps the auto-grow when no height is chosen', () => {
    expect(mainRibbonLaneHeight(null, 0, 1)).toBe(DEFAULT_RIBBON_PX);
    expect(mainRibbonLaneHeight(undefined, 10, 1)).toBe(DEFAULT_RIBBON_PX + 10);
    expect(mainRibbonLaneHeight(null, 400, 1)).toBe(MAIN_RIBBON_MAX_PX);
    expect(mainRibbonLaneHeight(null, 40, 0.35)).toBeCloseTo(DEFAULT_RIBBON_PX + 14);
  });

  it('treats a value that is not a height as none', () => {
    expect(chosenRibbonHeight(0)).toBeNull();
    expect(chosenRibbonHeight(Number.NaN)).toBeNull();
    expect(baseRibbonHeight(null)).toBe(DEFAULT_RIBBON_PX);
    expect(baseRibbonHeight(44)).toBe(44);
  });
});
