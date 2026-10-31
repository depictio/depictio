import { describe, expect, it } from 'vitest';

import { buildPedigree } from '../pedigree/pedigreeLayout';
import {
  assignGenotypeColumns,
  carriersFromLong,
  carriersFromRow,
  findProband,
  genotypeClass,
  moreAlternate,
  parseProbandFlag,
  symbolFill,
} from './familyData';

describe('genotypeClass', () => {
  it('reads allele calls', () => {
    expect(genotypeClass('0/0')).toBe('ref');
    expect(genotypeClass('0|0')).toBe('ref');
    expect(genotypeClass('0/1')).toBe('het');
    expect(genotypeClass('1|0')).toBe('het');
    expect(genotypeClass('1/2')).toBe('het');
    expect(genotypeClass('1/1')).toBe('hom_alt');
    expect(genotypeClass('2/2')).toBe('hom_alt');
    expect(genotypeClass('1')).toBe('hom_alt');
    expect(genotypeClass('0')).toBe('ref');
  });
  it('reads the classes a caller writes', () => {
    expect(genotypeClass('HOM_ALT')).toBe('hom_alt');
    expect(genotypeClass('Het')).toBe('het');
    expect(genotypeClass('hom_ref')).toBe('ref');
    expect(genotypeClass('ref')).toBe('ref');
    expect(genotypeClass('missing')).toBe('missing');
  });
  it('reads a number as a dosage of alternate alleles', () => {
    expect([0, 1, 2].map(genotypeClass)).toEqual(['ref', 'het', 'hom_alt']);
  });
  it('calls anything with a missing allele, or nothing readable, missing', () => {
    for (const v of ['./.', '0/.', '.', '', null, undefined, 'NA', 'weird', Number.NaN]) {
      expect(genotypeClass(v), String(v)).toBe('missing');
    }
  });
});

describe('symbolFill', () => {
  it('fills hom-alt solid, het half, ref open and missing grey', () => {
    expect(symbolFill('hom_alt')).toBe('full');
    expect(symbolFill('het')).toBe('half');
    expect(symbolFill('ref')).toBe('empty');
    expect(symbolFill('missing')).toBe('grey');
  });
  it('greys a person with no call at all', () => {
    expect(symbolFill(undefined)).toBe('grey');
    expect(symbolFill(null)).toBe('grey');
  });
});

describe('moreAlternate', () => {
  it('keeps the call that carries more alternate allele', () => {
    expect(moreAlternate('ref', 'het')).toBe('het');
    expect(moreAlternate('hom_alt', 'het')).toBe('hom_alt');
    expect(moreAlternate('missing', 'ref')).toBe('ref');
    expect(moreAlternate('het', 'missing')).toBe('het');
  });
});

const trio = buildPedigree(
  {
    sample: ['kid', 'mum', 'dad', 'sis'],
    father: ['dad', '0', '0', 'dad'],
    mother: ['mum', '0', '0', 'mum'],
    sex: [1, 2, 1, 2],
    status: [2, 1, 1, 1],
    role: ['proband', '', '', ''],
  },
  { individual: 'sample', father: 'father', mother: 'mother', sex: 'sex', status: 'status' },
  { maxIndividuals: 50, maxFamilies: 5 },
);
const people = trio.families[0].people;
const keyOf = (id: string) => people.find((p) => p.id === id)!.key;

describe('findProband', () => {
  it('takes the flagged person', () => {
    const flagged = buildPedigree(
      {
        sample: ['a', 'b', 'c'],
        father: ['0', '0', 'a'],
        mother: ['0', '0', 'b'],
        sex: [1, 2, 1],
        status: [2, 1, 2],
        p: [1, 0, 0],
      },
      { individual: 'sample', father: 'father', mother: 'mother', sex: 'sex', status: 'status' },
      { maxIndividuals: 50, maxFamilies: 5 },
    ).families[0].people;
    // 'a' is flagged though 'c' is the affected child
    expect(findProband(flagged, 'p')).toBe(flagged[0].key);
  });
  it('guesses the affected child when nobody is flagged', () => {
    expect(findProband(people, null)).toBe(keyOf('kid'));
    expect(findProband(people, 'role')).toBe(keyOf('kid'));
  });
  it('is null when nobody is affected', () => {
    const none = buildPedigree(
      { sample: ['a'], father: ['0'], mother: ['0'], sex: [1], status: [1] },
      { individual: 'sample', father: 'father', mother: 'mother', sex: 'sex', status: 'status' },
      { maxIndividuals: 50, maxFamilies: 5 },
    ).families[0].people;
    expect(findProband(none, null)).toBeNull();
  });
});

describe('parseProbandFlag', () => {
  it('reads the words a samplesheet uses', () => {
    for (const v of [1, '1', true, 'yes', 'Proband', 'index']) expect(parseProbandFlag(v)).toBe(true);
    for (const v of [0, '0', '', null, 'mother', false]) expect(parseProbandFlag(v)).toBe(false);
  });
});

describe('genotype columns on the row', () => {
  const kid = keyOf('kid');
  it('maps an identifier or a role to a person', () => {
    const map = assignGenotypeColumns(people, kid, {
      proband: 'gt_p',
      mother: 'gt_m',
      father: 'gt_f',
      sis: 'gt_s',
      ghost: 'gt_x',
    });
    expect(map.get(kid)).toBe('gt_p');
    expect(map.get(keyOf('mum'))).toBe('gt_m');
    expect(map.get(keyOf('dad'))).toBe('gt_f');
    expect(map.get(keyOf('sis'))).toBe('gt_s');
    expect(map.size).toBe(4);
  });

  it('keeps one entry per person when an identifier and a role name the same one', () => {
    const map = assignGenotypeColumns(people, keyOf('kid'), { kid: 'a', proband: 'b' });
    expect(map.get(keyOf('kid'))).toBe('b'); // same person; the later entry replaces
    expect(map.size).toBe(1);
  });

  it('reads each person’s call off the row', () => {
    const row: Record<string, unknown> = { gt_p: '0/1', gt_m: '0/1', gt_f: '0/0' };
    const carriers = carriersFromRow(
      people,
      kid,
      { proband: 'gt_p', mother: 'gt_m', father: 'gt_f' },
      (c) => row[c],
    );
    expect(carriers.get(kid)).toBe('het');
    expect(carriers.get(keyOf('mum'))).toBe('het');
    expect(carriers.get(keyOf('dad'))).toBe('ref');
    expect(carriers.has(keyOf('sis'))).toBe(false);
  });

  it('cannot resolve a role without a proband', () => {
    expect(assignGenotypeColumns(people, null, { proband: 'x', mother: 'y' }).size).toBe(0);
  });
});

describe('genotypes from a long table', () => {
  it('maps individuals, keeps the most alternate call and ignores strangers', () => {
    const carriers = carriersFromLong(
      people,
      {
        sample: ['kid', 'mum', 'dad', 'kid', 'stranger'],
        gt_class: ['het', 'het', 'ref', 'hom_alt', 'hom_alt'],
      },
      { individual: 'sample', genotype: 'gt_class' },
    );
    expect(carriers.get(keyOf('kid'))).toBe('hom_alt');
    expect(carriers.get(keyOf('mum'))).toBe('het');
    expect(carriers.get(keyOf('dad'))).toBe('ref');
    expect(carriers.has(keyOf('sis'))).toBe(false);
    expect(carriers.size).toBe(3);
  });
});

describe('genotype labels', () => {
  it('reads labels any case, with spaces, dashes or underscores', () => {
    const hom = ['Hom alt', 'HOM ALT', 'hom-alt', 'hom_alt', 'Homozygous alt', 'homozygous alternate', 'Homozygous'];
    for (const v of hom) expect(genotypeClass(v), v).toBe('hom_alt');
    for (const v of ['Het', 'heterozygous', 'Heterozygous alt', 'HET']) {
      expect(genotypeClass(v), v).toBe('het');
    }
    for (const v of ['Hom ref', 'hom-ref', 'Homozygous ref', 'homozygous reference', 'Wild type', 'REF']) {
      expect(genotypeClass(v), v).toBe('ref');
    }
    for (const v of ['No call', 'no-call', 'Missing', 'Unknown']) expect(genotypeClass(v), v).toBe('missing');
  });
});

describe('who is missing', () => {
  const kid = keyOf('kid');
  const long = {
    sample: ['kid', 'mum'],
    gt_class: ['Het', 'Hom alt'],
  };
  const columns = { individual: 'sample', genotype: 'gt_class' };

  it('leaves people with no row as no call by default', () => {
    const c = carriersFromLong(people, long, columns);
    expect(c.has(keyOf('dad'))).toBe(false);
    expect(c.get(kid)).toBe('het');
    expect(c.get(keyOf('mum'))).toBe('hom_alt');
  });

  it('draws people with no row as reference for a table of carriers only', () => {
    const c = carriersFromLong(people, long, columns, 'ref');
    expect(c.get(keyOf('dad'))).toBe('ref');
    expect(c.get(keyOf('sis'))).toBe('ref');
    // the rows that exist are untouched
    expect(c.get(kid)).toBe('het');
    expect(c.get(keyOf('mum'))).toBe('hom_alt');
  });

  it('keeps a real no call as missing even with missingAs ref', () => {
    const c = carriersFromLong(
      people,
      { sample: ['kid', 'mum'], gt_class: ['./.', 'Het'] },
      columns,
      'ref',
    );
    expect(c.get(kid)).toBe('missing');
  });

  it('reads an empty cell of the row by missingAs', () => {
    const row: Record<string, unknown> = { gt_p: '0/1', gt_m: null, gt_f: '' };
    const map = { proband: 'gt_p', mother: 'gt_m', father: 'gt_f' };
    const byDefault = carriersFromRow(people, kid, map, (c) => row[c]);
    expect(byDefault.get(keyOf('mum'))).toBe('missing');
    const asRef = carriersFromRow(people, kid, map, (c) => row[c], 'ref');
    expect(asRef.get(keyOf('mum'))).toBe('ref');
    expect(asRef.get(keyOf('dad'))).toBe('ref');
    expect(asRef.get(kid)).toBe('het');
  });
});
