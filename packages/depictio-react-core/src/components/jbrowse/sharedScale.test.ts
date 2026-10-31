import { describe, expect, it, vi } from 'vitest';

import { displayRange, scaleFamily, setBounds, sharedBounds, unionRange } from './sharedScale';

const wiggle = (scoreMin: number, scoreMax: number, extra: Record<string, unknown> = {}) => ({
  type: 'LinearWiggleDisplay',
  stats: { scoreMin, scoreMax },
  ...extra,
});

describe('scaleFamily', () => {
  it('keeps signal and read depth apart', () => {
    expect(scaleFamily('LinearWiggleDisplay')).toBe('signal');
    expect(scaleFamily('MultiLinearWiggleDisplay')).toBe('signal');
    expect(scaleFamily('LinearSNPCoverageDisplay')).toBe('depth');
    expect(scaleFamily('LinearBasicDisplay')).toBeNull();
  });
});

describe('displayRange', () => {
  it('reads min / max, or the mean stats under a mean summary', () => {
    expect(displayRange(wiggle(0, 10))).toEqual([0, 10]);
    const mean = {
      type: 'LinearWiggleDisplay',
      stats: { scoreMin: 0, scoreMax: 10, scoreMeanMin: 1, scoreMeanMax: 4 },
      rendererConfig: { summaryScoreMode: 'avg' },
    };
    expect(displayRange(mean)).toEqual([1, 4]);
  });

  it('is undefined before the stats load', () => {
    expect(displayRange({ type: 'LinearWiggleDisplay' })).toBeUndefined();
  });
});

describe('unionRange', () => {
  it('spans every known range and skips unknown ones', () => {
    expect(unionRange([[0, 5], undefined, [-2, 3]])).toEqual([-2, 5]);
    expect(unionRange([undefined])).toBeNull();
  });
});

describe('sharedBounds', () => {
  it('unites each family on its own', () => {
    const bounds = sharedBounds([
      wiggle(0, 10),
      wiggle(0, 80),
      { type: 'LinearSNPCoverageDisplay', stats: { scoreMin: 0, scoreMax: 30 } },
      { type: 'LinearSNPCoverageDisplay', stats: { scoreMin: 0, scoreMax: 12 } },
      { type: 'LinearBasicDisplay' },
    ]);
    expect(bounds.get('signal')).toEqual([0, 80]);
    expect(bounds.get('depth')).toEqual([0, 30]);
  });

  it('leaves a lone track of a family on its own scale', () => {
    const bounds = sharedBounds([
      wiggle(0, 10),
      { type: 'LinearSNPCoverageDisplay', stats: { scoreMin: 0, scoreMax: 30 } },
    ]);
    expect(bounds.size).toBe(0);
  });
});

describe('setBounds', () => {
  it('writes the range as bounds, and lifts them with undefined', () => {
    const d = { setMinScore: vi.fn(), setMaxScore: vi.fn() };
    setBounds(d, [0, 80]);
    expect(d.setMinScore).toHaveBeenLastCalledWith(0);
    expect(d.setMaxScore).toHaveBeenLastCalledWith(80);
    setBounds(d, undefined);
    expect(d.setMinScore).toHaveBeenLastCalledWith(undefined);
    expect(d.setMaxScore).toHaveBeenLastCalledWith(undefined);
  });
});
