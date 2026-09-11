import { describe, expect, it } from 'vitest';

import { looksContinuous, MAX_DISCRETE_COLOUR_VALUES } from './colourScales';

describe('looksContinuous', () => {
  it('reads a float column as a measurement however few values it has', () => {
    // The chipseq fingerprint scatter: eight IP libraries, eight AUC ratios.
    // Under a distinct-count rule alone this drew eight qualitative swatches
    // labelled with the raw floats and ignored the configured colour scale.
    const aucRatios = [0.31786, 0.34048, 0.36481, 0.42467, 0.584614, 0.584699, 0.708222, 0.721931];
    expect(looksContinuous(aucRatios)).toBe(true);
  });

  it('keeps a short integer column categorical', () => {
    // Run ids, replicate numbers, support counts: whole numbers that a
    // qualitative palette reads better than a gradient.
    expect(looksContinuous([1, 2, 3, 4, 2, 3])).toBe(false);
  });

  it('reads a long integer column as a measurement', () => {
    const many = Array.from({ length: MAX_DISCRETE_COLOUR_VALUES + 1 }, (_, i) => i * 10);
    expect(looksContinuous(many)).toBe(true);
  });

  it('rejects a column with any non-numeric entry', () => {
    expect(looksContinuous([0.5, 0.25, 'EZH2_IP'])).toBe(false);
  });

  it('ignores blanks rather than counting them as values', () => {
    expect(looksContinuous([null, undefined, '', 0.5, 0.75])).toBe(true);
    expect(looksContinuous([null, undefined, ''])).toBe(false);
  });

  it('is false for an empty column', () => {
    expect(looksContinuous([])).toBe(false);
  });
});
