import { describe, expect, it } from 'vitest';

import { fitTrackHeights, isFittableDisplay } from './fitTracks';

describe('fitTrackHeights', () => {
  it('shares the free height among the signal tracks', () => {
    // 100 px of chrome, a 60 px gene track, two 100 px signals, an 800 px host.
    const tracks = [
      { height: 60, fittable: false },
      { height: 100, fittable: true },
      { height: 100, fittable: true },
    ];
    expect(fitTrackHeights(tracks, 360, 800)).toBe(320);
  });

  it('is stable once applied', () => {
    const tracks = [
      { height: 60, fittable: false },
      { height: 320, fittable: true },
      { height: 320, fittable: true },
    ];
    expect(fitTrackHeights(tracks, 800, 800)).toBe(320);
  });

  it('never goes below the minimum', () => {
    const tracks = Array.from({ length: 20 }, () => ({ height: 100, fittable: true }));
    expect(fitTrackHeights(tracks, 2100, 500)).toBe(40);
  });

  it('is null without a signal track', () => {
    expect(fitTrackHeights([{ height: 60, fittable: false }], 160, 800)).toBeNull();
  });
});

describe('isFittableDisplay', () => {
  it('takes the wiggle displays only', () => {
    expect(isFittableDisplay('LinearWiggleDisplay')).toBe(true);
    expect(isFittableDisplay('MultiLinearWiggleDisplay')).toBe(true);
    expect(isFittableDisplay('LinearBasicDisplay')).toBe(false);
    expect(isFittableDisplay(undefined)).toBe(false);
  });
});
