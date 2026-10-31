import { describe, expect, it } from 'vitest';

import { CHROMOSOME_PALETTE, chromosomeColourMap } from './chromosomeColours';

describe('chromosomeColourMap', () => {
  it('colours a chromosome by its place in the genome, whatever else is there', () => {
    const map = chromosomeColourMap(['chr10', 'chr2', 'chrX', 'chr2', 'chr1']);
    expect([...map.keys()]).toEqual(['chr1', 'chr2', 'chr10', 'chrX']);
    expect(map.get('chr1')).toBe(CHROMOSOME_PALETTE[0]);
    expect(map.get('chr10')).toBe(CHROMOSOME_PALETTE[9 % CHROMOSOME_PALETTE.length]);
    expect(map.get('chrX')).toBe(CHROMOSOME_PALETTE[22 % CHROMOSOME_PALETTE.length]);
    // A tile keeping a few loci gives chr17 the colour the full genome gives it.
    expect(chromosomeColourMap(['17']).get('17')).toBe(
      chromosomeColourMap(['chr1', 'chr2', 'chr17']).get('chr17'),
    );
  });
});
