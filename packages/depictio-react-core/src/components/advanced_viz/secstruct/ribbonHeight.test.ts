import { describe, expect, it } from 'vitest';

import {
  baseRibbonHeight,
  chosenRibbonHeight,
  DEFAULT_RIBBON_PX,
  mainRibbonMax,
  MAIN_RIBBON_MAX_PX,
  MAIN_RIBBON_SOLO_MAX_PX,
} from './ribbonHeight';

describe('ribbon height', () => {
  it('treats a value that is not a height as none', () => {
    expect(chosenRibbonHeight(0)).toBeNull();
    expect(chosenRibbonHeight(Number.NaN)).toBeNull();
    expect(chosenRibbonHeight(null)).toBeNull();
    expect(chosenRibbonHeight(44)).toBe(44);
    expect(baseRibbonHeight(null)).toBe(DEFAULT_RIBBON_PX);
    expect(baseRibbonHeight(44)).toBe(44);
  });

  it('lets the lane grow further when it is the only data lane', () => {
    expect(mainRibbonMax(true)).toBe(MAIN_RIBBON_MAX_PX);
    expect(mainRibbonMax(false)).toBe(MAIN_RIBBON_SOLO_MAX_PX);
    expect(MAIN_RIBBON_MAX_PX).toBeGreaterThan(DEFAULT_RIBBON_PX);
    expect(MAIN_RIBBON_SOLO_MAX_PX).toBeGreaterThan(MAIN_RIBBON_MAX_PX);
  });
});
