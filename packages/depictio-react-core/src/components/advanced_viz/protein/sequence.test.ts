import { describe, expect, it } from 'vitest';

import {
  isPlddtLabel,
  looksLikeSecondaryStructure,
  normaliseResidues,
  runsOf,
  secondaryStructureOf,
  stackVariants,
  stripSpan,
  valueExtent,
} from './sequence';

describe('residues', () => {
  it('sorts by position and keeps the first of a duplicate', () => {
    const out = normaliseResidues([
      { position: 3, letter: 'C' },
      { position: 1, letter: 'A' },
      { position: 3, letter: 'X' },
    ]);
    expect(out.map((r) => [r.position, r.letter])).toEqual([
      [1, 'A'],
      [3, 'C'],
    ]);
  });

  it('spans every lane and starts the axis at residue 1', () => {
    expect(stripSpan([{ position: 5 }], [{ start: 2, end: 40 }], [{ position: 60 }])).toEqual({
      min: 1,
      max: 60,
    });
    expect(stripSpan([])).toBeNull();
  });

  it('reads the value extent, ignoring missing values', () => {
    expect(valueExtent([{ position: 1, value: 40 }, { position: 2, value: null }, { position: 3, value: 95 }])).toEqual([40, 95]);
    expect(valueExtent([{ position: 1 }])).toBeNull();
  });
});

describe('secondary structure', () => {
  it('maps DSSP letters and words to classes', () => {
    expect(secondaryStructureOf('H')).toBe('helix');
    expect(secondaryStructureOf('e')).toBe('strand');
    expect(secondaryStructureOf('Coil')).toBe('coil');
    expect(secondaryStructureOf('missense')).toBeNull();
  });

  it('detects a structure lane only when every value is a class and one is structured', () => {
    expect(looksLikeSecondaryStructure(['C', 'H', 'H', null, 'E'])).toBe(true);
    expect(looksLikeSecondaryStructure(['C', 'C'])).toBe(false);
    expect(looksLikeSecondaryStructure(['H', 'Pkinase'])).toBe(false);
  });

  it('builds runs that break on a value change or a numbering gap', () => {
    const residues = [1, 2, 3, 5, 6].map((p, i) => ({ position: p, category: ['H', 'H', 'E', 'E', 'E'][i] }));
    expect(runsOf(residues, (r) => r.category ?? null)).toEqual([
      { start: 1, end: 2, value: 'H' },
      { start: 3, end: 3, value: 'E' },
      { start: 5, end: 6, value: 'E' },
    ]);
  });
});

describe('variants and labels', () => {
  it('stacks variants by position in order', () => {
    const out = stackVariants([
      { position: 175, label: 'R175H' },
      { position: 12 },
      { position: 175, label: 'R175C' },
    ]);
    expect(out.map((s) => [s.position, s.variants.length])).toEqual([
      [12, 1],
      [175, 2],
    ]);
  });

  it('recognises a pLDDT lane title', () => {
    expect(isPlddtLabel('pLDDT')).toBe(true);
    expect(isPlddtLabel('mean plddt')).toBe(true);
    expect(isPlddtLabel('score')).toBe(false);
    expect(isPlddtLabel(null)).toBe(false);
  });
});
