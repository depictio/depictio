import { describe, expect, it } from 'vitest';

import { collectScoreDisplays, isScoreDisplayType, rescaleDisplays } from './autoscale';
import type { Model } from './displaySettings';

/** A wiggle-like display: records the actions it receives. */
function display(type: string, stats?: { scoreMin: number; scoreMax: number }) {
  const calls: Array<[string, unknown]> = [];
  const d: Model = {
    type,
    stats,
    calls,
    setAutoscale: (v: unknown) => calls.push(['setAutoscale', v]),
    setMinScore: (v: unknown) => calls.push(['setMinScore', v]),
    setMaxScore: (v: unknown) => calls.push(['setMaxScore', v]),
  };
  return d;
}

const callsOf = (d: Model) => d.calls as Array<[string, unknown]>;
const track = (...displays: Model[]) => ({ displays });

describe('isScoreDisplayType', () => {
  it('takes the wiggle family and the coverage panel only', () => {
    expect(isScoreDisplayType('LinearWiggleDisplay')).toBe(true);
    expect(isScoreDisplayType('MultiLinearWiggleDisplay')).toBe(true);
    expect(isScoreDisplayType('LinearSNPCoverageDisplay')).toBe(true);
    expect(isScoreDisplayType('LinearBasicDisplay')).toBe(false);
    expect(isScoreDisplayType('LinearAlignmentsDisplay')).toBe(false);
    expect(isScoreDisplayType(undefined)).toBe(false);
  });
});

describe('collectScoreDisplays', () => {
  it('finds signal displays and the coverage nested in an alignments display', () => {
    const wiggle = display('LinearWiggleDisplay');
    const multi = display('MultiLinearWiggleDisplay');
    const coverage = display('LinearSNPCoverageDisplay');
    const alignments: Model = {
      type: 'LinearAlignmentsDisplay',
      SNPCoverageDisplay: coverage,
      PileupDisplay: display('LinearPileupDisplay'),
    };
    const genes = display('LinearBasicDisplay');
    const found = collectScoreDisplays([track(wiggle), track(genes), track(alignments), track(multi)]);
    expect(found).toEqual([wiggle, coverage, multi]);
  });

  it('is empty without a score display, or without tracks', () => {
    expect(collectScoreDisplays([track(display('LinearBasicDisplay'))])).toEqual([]);
    expect(collectScoreDisplays([{ displays: undefined }, null])).toEqual([]);
    expect(collectScoreDisplays(undefined)).toEqual([]);
  });

  it('survives a getter that throws (a display torn down)', () => {
    const broken = Object.defineProperty({}, 'displays', {
      get() {
        throw new Error('dead');
      },
    });
    expect(collectScoreDisplays([broken])).toEqual([]);
  });
});

describe('rescaleDisplays', () => {
  it('sets a local autoscale and lifts the fixed bounds', () => {
    const d = display('LinearWiggleDisplay');
    expect(rescaleDisplays([d], false)).toBe(1);
    expect(callsOf(d)).toEqual([
      ['setAutoscale', 'local'],
      ['setMinScore', undefined],
      ['setMaxScore', undefined],
    ]);
  });

  it('skips a display without the action and does not count it', () => {
    const odd: Model = { type: 'LinearWiggleDisplay' };
    expect(rescaleDisplays([odd], false)).toBe(0);
  });

  it('keeps a shared scale shared: bounds are the union of the visible stats', () => {
    const a = display('LinearWiggleDisplay', { scoreMin: 0, scoreMax: 10 });
    const b = display('LinearWiggleDisplay', { scoreMin: 2, scoreMax: 40 });
    const cov = display('LinearSNPCoverageDisplay', { scoreMin: 0, scoreMax: 99 });
    expect(rescaleDisplays([a, b, cov], true)).toBe(3);
    for (const d of [a, b]) {
      expect(callsOf(d)).toEqual([
        ['setAutoscale', 'local'],
        ['setMinScore', 0],
        ['setMaxScore', 40],
      ]);
    }
    // alone in its family: nothing to share, so its own scale (bounds lifted)
    expect(callsOf(cov)).toEqual([
      ['setAutoscale', 'local'],
      ['setMinScore', undefined],
      ['setMaxScore', undefined],
    ]);
  });

  it('lifts the bounds under a shared scale whose stats are not in yet', () => {
    const a = display('LinearWiggleDisplay');
    const b = display('LinearWiggleDisplay');
    rescaleDisplays([a, b], true);
    expect(callsOf(a).slice(1)).toEqual([
      ['setMinScore', undefined],
      ['setMaxScore', undefined],
    ]);
  });
});
