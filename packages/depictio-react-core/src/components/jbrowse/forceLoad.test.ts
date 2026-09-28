import { describe, expect, it, vi } from 'vitest';

import {
  FORCE_LOAD_BYTES,
  densityTargets,
  hasLiftedLimits,
  liftDisplayLimits,
  planForceLoadReset,
} from './forceLoad';

/** A stand-in for FeatureDensityMixin: same limit semantics. */
function fakeDisplay(bpPerPx: number, extra: Record<string, unknown> = {}) {
  const d = {
    userBpPerPxLimit: undefined as number | undefined,
    userByteSizeLimit: undefined as number | undefined,
    regionTooLarge: false,
    setFeatureDensityStatsLimit: vi.fn((stats?: { bytes?: number }) => {
      if (stats?.bytes) d.userByteSizeLimit = stats.bytes;
      else d.userBpPerPxLimit = bpPerPx;
    }),
    reload: vi.fn(() => Promise.resolve()),
    ...extra,
  };
  return d;
}

describe('liftDisplayLimits', () => {
  it('lifts both limits and reloads when switched on', () => {
    const d = fakeDisplay(10);
    expect(liftDisplayLimits(d, { bpPerPx: 10, reload: 'always' })).toBe(1);
    expect(d.setFeatureDensityStatsLimit.mock.calls).toEqual([[{ bytes: FORCE_LOAD_BYTES }], [undefined]]);
    expect(d.userByteSizeLimit).toBe(FORCE_LOAD_BYTES);
    expect(d.userBpPerPxLimit).toBe(10);
    expect(d.reload).toHaveBeenCalledTimes(1);
  });

  it('covers the alignments sub-displays', () => {
    const pileup = fakeDisplay(10);
    const snp = fakeDisplay(10);
    const parent = { PileupDisplay: pileup, SNPCoverageDisplay: snp };
    expect(densityTargets(parent)).toEqual([pileup, snp]);
    expect(liftDisplayLimits(parent, { bpPerPx: 10, reload: 'always' })).toBe(2);
    expect(pileup.reload).toHaveBeenCalled();
    expect(snp.userByteSizeLimit).toBe(FORCE_LOAD_BYTES);
  });

  it('skips targets already lifted at this zoom, re-lifts on zoom out', () => {
    const d = fakeDisplay(10);
    liftDisplayLimits(d, { bpPerPx: 10, reload: 'always' });
    d.setFeatureDensityStatsLimit.mockClear();
    expect(liftDisplayLimits(d, { bpPerPx: 5, reload: 'ifBlocked' })).toBe(0);
    expect(d.setFeatureDensityStatsLimit).not.toHaveBeenCalled();
    expect(liftDisplayLimits(d, { bpPerPx: 50, reload: 'ifBlocked' })).toBe(1);
  });

  it('reloads on zoom only the targets showing the "too large" message', () => {
    const quiet = fakeDisplay(10);
    const blocked = fakeDisplay(10, { regionTooLarge: true });
    liftDisplayLimits(quiet, { bpPerPx: 10, reload: 'ifBlocked' });
    liftDisplayLimits(blocked, { bpPerPx: 10, reload: 'ifBlocked' });
    expect(quiet.reload).not.toHaveBeenCalled();
    expect(blocked.reload).toHaveBeenCalledTimes(1);
  });

  it('ignores dead nodes, displays without limits and throwing models', () => {
    const d = fakeDisplay(10);
    expect(liftDisplayLimits(d, { bpPerPx: 10, reload: 'always', alive: () => false })).toBe(0);
    expect(liftDisplayLimits({ type: 'LinearWiggleDisplay' }, { reload: 'always' })).toBe(0);
    expect(liftDisplayLimits(null, { reload: 'always' })).toBe(0);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const broken = fakeDisplay(10, {
      setFeatureDensityStatsLimit: () => {
        throw new Error('detached');
      },
    });
    expect(() => liftDisplayLimits(broken, { bpPerPx: 10, reload: 'always' })).not.toThrow();
    warn.mockRestore();
  });

  it('swallows a rejected reload', async () => {
    const d = fakeDisplay(10, { reload: () => Promise.reject(new Error('aborted')) });
    expect(() => liftDisplayLimits(d, { bpPerPx: 10, reload: 'always' })).not.toThrow();
    await Promise.resolve();
  });
});

describe('hasLiftedLimits', () => {
  it('is true once any target carries a user limit', () => {
    const d = fakeDisplay(10);
    expect(hasLiftedLimits(d)).toBe(false);
    liftDisplayLimits(d, { bpPerPx: 10, reload: 'always' });
    expect(hasLiftedLimits(d)).toBe(true);
  });
});

describe('planForceLoadReset', () => {
  it('re-opens from the first affected track down, keeping the order', () => {
    expect(planForceLoadReset(['genes', 'a', 'b', 'c'], new Set(['b']))).toEqual(['b', 'c']);
    expect(planForceLoadReset(['a', 'b'], new Set())).toEqual([]);
  });
});
