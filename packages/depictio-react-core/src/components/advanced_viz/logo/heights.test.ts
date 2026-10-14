import { describe, expect, it } from 'vitest';

import fixture from './__fixtures__/heights.json';
import {
  AMINO_ORDER,
  BACKGROUND_AMINO,
  backgroundFor,
  columnHeights,
  detectAlphabet,
  HEIGHT_MODES,
  logoHeights,
  type HeightMode,
  type LogoAlphabet,
} from './heights';

// The fixture is written by depictio/tests/unit/recipes/test_hmm_logo_parity.py
// from the Python `letter_heights`, which re-checks it on every run: these
// numbers are HMMER's (hmmlogo.c), not this module's.
describe('heights fixture parity with hmm.py', () => {
  for (const testCase of fixture.cases) {
    const letters = testCase.letters.split('');
    const bg = backgroundFor(letters, testCase.alphabet as LogoAlphabet);
    for (const mode of HEIGHT_MODES) {
      it(`${testCase.name} / ${mode}`, () => {
        const expected = (testCase.modes as Record<string, { heights: number[][]; info: number[] }>)[mode];
        testCase.emissions.forEach((row, i) => {
          const got = columnHeights(row, bg, mode);
          expect(got.info).toBeCloseTo(expected.info[i], 9);
          got.heights.forEach((h, a) => expect(h).toBeCloseTo(expected.heights[i][a], 9));
        });
      });
    }
  }

  it('covers both alphabets and every mode', () => {
    expect(new Set(fixture.cases.map((c) => c.alphabet))).toEqual(new Set(['amino', 'nucleic']));
    for (const c of fixture.cases) expect(Object.keys(c.modes).sort()).toEqual([...HEIGHT_MODES].sort());
  });
});

describe('background', () => {
  it('holds the 20 HMMER amino letters, summing to about 1', () => {
    expect(Object.keys(BACKGROUND_AMINO).sort().join('')).toBe(AMINO_ORDER);
    const total = Object.values(BACKGROUND_AMINO).reduce((s, v) => s + v, 0);
    expect(total).toBeCloseTo(1, 3);
  });

  it('is uniform 1/4 for DNA and RNA, zero for a letter outside the amino alphabet', () => {
    expect(backgroundFor(['A', 'C', 'G', 'U'], 'nucleic')).toEqual([0.25, 0.25, 0.25, 0.25]);
    expect(backgroundFor(['w', 'X'], 'amino')).toEqual([BACKGROUND_AMINO.W, 0]);
  });

  it('detects the alphabet from the letters', () => {
    expect(detectAlphabet('ACGT')).toBe('nucleic');
    expect(detectAlphabet(['a', 'c', 'g', 'u'])).toBe('nucleic');
    expect(detectAlphabet(AMINO_ORDER)).toBe('amino');
    expect(detectAlphabet([])).toBe('amino');
  });
});

describe('columnHeights', () => {
  const bg = backgroundFor(AMINO_ORDER.split(''), 'amino');
  const peaked = AMINO_ORDER.split('').map((l) => (l === 'W' ? 0.9 : 0.1 / 19));

  it('stacks to RE in relent_all and keeps RE but zeroes below-background letters in relent_abovebg', () => {
    const all = columnHeights(peaked, bg, 'relent_all');
    const above = columnHeights(peaked, bg, 'relent_abovebg');
    expect(above.info).toBeCloseTo(all.info, 12);
    const sumAll = all.heights.reduce((s, v) => s + v, 0);
    const sumAbove = above.heights.reduce((s, v) => s + v, 0);
    expect(sumAll).toBeCloseTo(all.info, 12);
    expect(sumAbove).toBeCloseTo(above.info, 12);
    // Only W is above its background here.
    expect(above.heights.filter((h) => h > 0)).toHaveLength(1);
  });

  it('is the raw emission in probability mode', () => {
    const out = columnHeights([0.5, 0.25, 0, -1, Number.NaN], [0.2, 0.2, 0.2, 0.2, 0.2], 'probability');
    expect(out.heights).toEqual([0.5, 0.25, 0, 0, 0]);
    expect(out.info).toBe(0.75);
  });

  it('draws nothing for a letter with no background', () => {
    const out = columnHeights([0.5, 0.5], [0.25, 0], 'relent_all');
    expect(out.heights[1]).toBe(0);
    expect(out.info).toBeCloseTo(0.5 * Math.log2(0.5 / 0.25), 12);
  });
});

describe('logoHeights', () => {
  it('computes every state and orders letters smallest first', () => {
    const emissions = Float64Array.from([0.7, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.7]);
    const bg = backgroundFor(['A', 'C', 'G', 'T'], 'nucleic');
    const mode: HeightMode = 'relent_all';
    const out = logoHeights(emissions, 4, bg, mode);
    expect(out.info).toHaveLength(2);
    expect(out.info[0]).toBeCloseTo(out.info[1], 12);
    expect(out.maxInfo).toBeCloseTo(out.info[0], 12);
    // The tallest letter is drawn last (on top).
    expect(out.order[3]).toBe(0);
    expect(out.order[4 + 3]).toBe(3);
  });

  it('is empty for no letters', () => {
    const out = logoHeights(new Float64Array(0), 0, [], 'probability');
    expect(out.info).toHaveLength(0);
    expect(out.maxInfo).toBe(0);
  });
});
