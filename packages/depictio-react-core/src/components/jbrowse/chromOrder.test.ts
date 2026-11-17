import { describe, expect, it } from 'vitest';

import { naturalChromOrder } from './chromOrder';

const order = (xs: string[]) => naturalChromOrder(xs.map((refName) => ({ refName }))).map((r) => r.refName);
const shuffled = (xs: string[]) => [...xs].reverse();

describe('naturalChromOrder', () => {
  it('human (UCSC, by size): numbers, then X, Y, then the mitochondrion', () => {
    expect(order(['chr1', 'chr2', 'chr7', 'chrX', 'chr8', 'chr20', 'chrY', 'chr19', 'chr22', 'chr21', 'chrM'])).toEqual([
      'chr1', 'chr2', 'chr7', 'chr8', 'chr19', 'chr20', 'chr21', 'chr22', 'chrX', 'chrY', 'chrM',
    ]);
  });

  it('Ensembl names without a prefix', () => {
    expect(order(['MT', 'X', '10', '2', 'Y', '1'])).toEqual(['1', '2', '10', 'X', 'Y', 'MT']);
  });

  it('fly: arms after their number, then X, Y, M', () => {
    const fly = ['chr2L', 'chr2R', 'chr3L', 'chr3R', 'chr4', 'chrX', 'chrY', 'chrM'];
    expect(order(shuffled(fly))).toEqual(fly);
  });

  it('yeast: roman I to XVI, then the mitochondrion', () => {
    const yeast = ['chrI', 'chrII', 'chrIII', 'chrIV', 'chrV', 'chrVI', 'chrVII', 'chrVIII', 'chrIX', 'chrX',
      'chrXI', 'chrXII', 'chrXIII', 'chrXIV', 'chrXV', 'chrXVI', 'chrM'];
    expect(order(['chrIV', 'chrXV', 'chrVII', 'chrXII', 'chrXVI', 'chrXIII', 'chrII', 'chrXIV', 'chrX', 'chrXI',
      'chrV', 'chrVIII', 'chrIX', 'chrIII', 'chrVI', 'chrI', 'chrM'])).toEqual(yeast);
  });

  it('worm: roman I to V, then X as the sex chromosome, then MtDNA', () => {
    const worm = ['I', 'II', 'III', 'IV', 'V', 'X', 'MtDNA'];
    expect(order(shuffled(worm))).toEqual(worm);
  });

  it('plants and birds: chloroplast after the mitochondrion, W and Z after the numbers', () => {
    expect(order(['ChrC', 'ChrM', 'Chr5', 'Chr1', 'Chr3', 'Chr2', 'Chr4'])).toEqual([
      'Chr1', 'Chr2', 'Chr3', 'Chr4', 'Chr5', 'ChrM', 'ChrC',
    ]);
    expect(order(['Z', 'W', '28', '1', 'MT'])).toEqual(['1', '28', 'W', 'Z', 'MT']);
  });

  it('keeps the other contigs last, in natural order', () => {
    expect(order(['chrUn_gl000220', 'chr10_gl000192_random', 'chr2', 'chr1_gl000191_random', 'chr1'])).toEqual([
      'chr1', 'chr2', 'chr1_gl000191_random', 'chr10_gl000192_random', 'chrUn_gl000220',
    ]);
  });
});
