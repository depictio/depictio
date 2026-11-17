import { describe, expect, it } from 'vitest';

import { buildPedigree } from './pedigreeLayout';
import { fitScale, probandKeyOf, romanNumeral } from './probands';

const columns = { individual: 'id', father: 'fa', mother: 'mo', sex: 'sex', status: 'st', family: 'fam' };
const limits = { maxIndividuals: 100, maxFamilies: 10 };

function people(rows: Record<string, unknown[]>, family = '') {
  const built = buildPedigree(rows, columns, limits);
  return built.families.find((f) => f.id === family)!.people;
}

// A family of five: grandparents (I), a carrier mother and her partner (II),
// an affected child and an unaffected one (III).
const grand = {
  fam: ['f', 'f', 'f', 'f', 'f', 'f'],
  id: ['gf', 'gm', 'mo', 'fa', 'kid', 'sib'],
  fa: ['0', '0', 'gf', '0', 'fa', 'fa'],
  mo: ['0', '0', 'gm', '0', 'mo', 'mo'],
  sex: [1, 2, 2, 1, 2, 1],
  st: [1, 1, 2, 1, 2, 1],
};

describe('probandKeyOf', () => {
  it('prefers the flagged individual', () => {
    const ps = people({ ...grand, flag: [0, 0, 0, 0, 0, 1] }, 'f');
    expect(probandKeyOf(ps, 'flag')).toBe(ps.find((p) => p.id === 'sib')!.key);
  });

  it('without a flag takes an affected child with no children of their own', () => {
    const ps = people(grand, 'f');
    // `mo` is affected and a child, but a parent too: `kid` is the proband.
    expect(probandKeyOf(ps, null)).toBe(ps.find((p) => p.id === 'kid')!.key);
    // A flag column nobody sets falls back the same way.
    expect(probandKeyOf(ps.map((p) => ({ ...p, row: { flag: 0 } })), 'flag')).toBe(
      ps.find((p) => p.id === 'kid')!.key,
    );
  });

  it('falls back to an affected founder, and to nobody', () => {
    const solo = people({ fam: ['f'], id: ['a'], fa: ['0'], mo: ['0'], sex: [1], st: [2] }, 'f');
    expect(probandKeyOf(solo, null)).toBe(solo[0].key);
    const healthy = people({ fam: ['f'], id: ['a'], fa: ['0'], mo: ['0'], sex: [1], st: [1] }, 'f');
    expect(probandKeyOf(healthy, null)).toBeNull();
  });

  it('never marks a placeholder parent', () => {
    // A trio whose mother is only named: the affected child is the proband.
    const ps = people({ fam: ['f'], id: ['c'], fa: ['0'], mo: ['m'], sex: [1], st: [2] }, 'f');
    expect(ps.some((p) => p.placeholder)).toBe(true);
    expect(probandKeyOf(ps, null)).toBe(ps.find((p) => p.id === 'c')!.key);
  });
});

describe('romanNumeral', () => {
  it('writes generation numerals', () => {
    expect([1, 2, 3, 4, 5, 9, 14].map(romanNumeral)).toEqual(['I', 'II', 'III', 'IV', 'V', 'IX', 'XIV']);
    expect(romanNumeral(0)).toBe('');
    expect(romanNumeral(Number.NaN)).toBe('');
  });
});

describe('fitScale', () => {
  const content = { contentW: 300, contentH: 200 };

  it('grows a small tree to the room, up to the maximum', () => {
    expect(fitScale({ ...content, availW: 600, availH: 600 })).toBeCloseTo(2, 5);
    expect(fitScale({ ...content, availW: 3000, availH: 3000 })).toBe(2);
  });

  it('is limited by the tighter side', () => {
    expect(fitScale({ ...content, availW: 900, availH: 300 })).toBeCloseTo(1.5, 5);
  });

  it('shrinks a large tree to the room, never below the minimum', () => {
    expect(fitScale({ ...content, availW: 240, availH: 400 })).toBeCloseTo(0.8, 5);
    expect(fitScale({ ...content, availW: 30, availH: 20 })).toBe(0.5);
  });

  it('is 1 before the tile has a size', () => {
    expect(fitScale({ ...content, availW: 0, availH: 0 })).toBe(1);
    expect(fitScale({ contentW: 0, contentH: 0, availW: 100, availH: 100 })).toBe(1);
  });
});

describe('one proband rule for the pedigree tile and the ranked table popover', () => {
  it('is the same function', async () => {
    const { findProband } = await import('../ranked_table/familyData');
    expect(findProband).toBe(probandKeyOf);
  });
  it('prefers an affected child with no children of their own', async () => {
    const { findProband } = await import('../ranked_table/familyData');
    // The mother is affected and herself a child of the grandparents: the old
    // popover rule took her, the tile took the child, and the roles disagreed.
    const ps = people(grand, 'f');
    expect(findProband(ps, null)).toBe(ps.find((p) => p.id === 'kid')!.key);
  });
});
