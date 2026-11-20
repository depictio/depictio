/** `_resolve_multiqc_sample_filter`'s set algebra (it used to be a union). */
import { describe, expect, it } from 'vitest';

import { intersectSampleConstraints } from '../src/multiqcSamples';

describe('intersectSampleConstraints', () => {
  it('is null without a constraint (the figure renders unfiltered)', () => {
    expect(intersectSampleConstraints([])).toBeNull();
  });
  it('intersects: a second filter narrows, never widens', () => {
    expect(intersectSampleConstraints([['a', 'b', 'c'], ['b', 'c', 'd']])).toEqual(['b', 'c']);
  });
  it('a constraint that matched nothing empties the figure', () => {
    expect(intersectSampleConstraints([['a', 'b'], []])).toEqual([]);
  });
  it('expands canonical ids to report variants before intersecting', () => {
    const expansion = { S1: ['S1_R1', 'S1_R2'], S2: ['S2_R1'] };
    expect(intersectSampleConstraints([['S1', 'S2'], ['S1_R2', 'S2_R1']], expansion)).toEqual([
      'S1_R2',
      'S2_R1',
    ]);
  });
});
