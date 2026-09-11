import { describe, expect, it } from 'vitest';

import { dotSizeKey, dotSizes } from './dotSizes';

/** fraction_of_reads from the atacseq ataqv chromosome-counts fixture: the
 *  shape that exposed the bug, a share spread over ~25 reference sequences and
 *  so never anywhere near 1.0. */
const READ_SHARES = [0.0104, 0.0234, 0.0417, 0.0769, 0.0926, 0.0966];

describe('dotSizes', () => {
  it('spends the configured range on data that never approaches 1.0', () => {
    const sizes = dotSizes(READ_SHARES, 3, 26);
    // The regression, in numbers: mapping these linearly onto [0, 1] produced
    // 3.2 px to 5.2 px, 9% of the 23 px the tile asked for.
    expect(Math.min(...sizes)).toBeGreaterThan(9);
    expect(Math.max(...sizes)).toBeCloseTo(26, 5);
    expect(Math.max(...sizes) - Math.min(...sizes)).toBeGreaterThan(14);
  });

  it('puts the value on the area, not the diameter', () => {
    // Four times the value is twice the diameter, so four times the ink.
    const [small, big] = dotSizes([0.25, 1], 0, 40);
    expect(small).toBeCloseTo(20, 5);
    expect(big).toBeCloseTo(40, 5);
  });

  it('leaves a genuine unit domain where it was', () => {
    // Data that does reach 1.0 normalises to itself, so the single-cell reading
    // of frac_expressing keeps its endpoints and only gains the area mapping.
    const sizes = dotSizes([0, 0.5, 1], 2, 22);
    expect(sizes[0]).toBeCloseTo(2, 5);
    expect(sizes[2]).toBeCloseTo(22, 5);
  });

  it('maps zero and negatives to the floor rather than a hole', () => {
    expect(dotSizes([0, -1, 4], 5, 25)).toEqual([5, 5, 25]);
  });

  it('falls back to the floor when nothing is positive', () => {
    expect(dotSizes([0, 0, 0], 4, 30)).toEqual([4, 4, 4]);
    expect(dotSizes([], 4, 30)).toEqual([]);
  });

  it('survives a max below the min without inverting', () => {
    expect(dotSizes([1, 2], 20, 10)).toEqual([20, 20]);
  });

  it('treats non-numeric cells as zero', () => {
    const sizes = dotSizes([null, undefined, 'x', 9], 3, 23);
    expect(sizes.slice(0, 3)).toEqual([3, 3, 3]);
    expect(sizes[3]).toBeCloseTo(23, 5);
  });
});

describe('dotSizeKey', () => {
  it('anchors the top circle on the data peak', () => {
    const [first] = dotSizeKey(READ_SHARES, 3, 26);
    expect(first.value).toBeCloseTo(0.0966, 5);
    expect(first.diameter).toBeCloseTo(26, 5);
  });

  it('steps down by quarters so the diameters step down by halves', () => {
    // The scale is on the area, so quartering the value halves the circle. That
    // is what makes the row of circles look evenly spaced.
    const key = dotSizeKey([1], 0, 40, 3);
    expect(key.map((e) => e.value)).toEqual([1, 0.25, 0.0625]);
    expect(key.map((e) => e.diameter)).toEqual([40, 20, 10]);
  });

  it('reports the diameters the plot actually drew', () => {
    // The guarantee that makes the key a key: same function, same numbers.
    const key = dotSizeKey(READ_SHARES, 3, 26);
    const drawn = dotSizes(
      key.map((e) => e.value),
      3,
      26,
    );
    expect(key.map((e) => e.diameter)).toEqual(drawn);
  });

  it('has nothing to explain when there is no scale', () => {
    expect(dotSizeKey([], 3, 26)).toEqual([]);
    expect(dotSizeKey([0, 0], 3, 26)).toEqual([]);
    expect(dotSizeKey(READ_SHARES, 3, 26, 0)).toEqual([]);
  });
});
