import { describe, expect, it } from 'vitest';

import {
  buildPedigree,
  layoutPedigree,
  parseDeceased,
  parseIndividualId,
  parseParentId,
  parseSex,
  parseStatus,
  personKey,
  type ColumnarRows,
  type PedigreeColumns,
  type PlacedFamily,
  type PlacedPerson,
} from './pedigreeLayout';

const COLUMNS: PedigreeColumns = {
  individual: 'individual',
  father: 'father',
  mother: 'mother',
  sex: 'sex',
  status: 'status',
  family: null,
  label: null,
  deceased: null,
};
const LIMITS = { maxIndividuals: 300, maxFamilies: 12 };

type Row = {
  individual: string | number;
  father?: string | number | null;
  mother?: string | number | null;
  sex?: string | number;
  status?: string | number;
  family?: string;
  deceased?: string | number;
};

/** Row objects to the columnar frame the fetch returns. */
function frame(rows: Row[]): ColumnarRows {
  const out: ColumnarRows = {
    individual: [],
    father: [],
    mother: [],
    sex: [],
    status: [],
    family: [],
    deceased: [],
  };
  for (const r of rows) {
    out.individual.push(r.individual);
    out.father.push(r.father ?? 0);
    out.mother.push(r.mother ?? 0);
    out.sex.push(r.sex ?? 0);
    out.status.push(r.status ?? 0);
    out.family.push(r.family ?? '');
    out.deceased.push(r.deceased ?? 0);
  }
  return out;
}

function laidOut(rows: Row[], columns: PedigreeColumns = COLUMNS) {
  return layoutPedigree(buildPedigree(frame(rows), columns, LIMITS));
}

function find(family: PlacedFamily, id: string): PlacedPerson {
  const found = family.people.find((p) => p.person.id === id);
  if (!found) throw new Error(`no person ${id}`);
  return found;
}

describe('encodings', () => {
  it('reads sex as PED codes or words', () => {
    expect(parseSex(1)).toBe('male');
    expect(parseSex('1')).toBe('male');
    expect(parseSex('Male')).toBe('male');
    expect(parseSex(2)).toBe('female');
    expect(parseSex('F')).toBe('female');
    expect(parseSex(0)).toBe('unknown');
    expect(parseSex('unknown')).toBe('unknown');
    expect(parseSex(null)).toBe('unknown');
    expect(parseSex('other')).toBe('unknown');
  });

  it('reads status as PED phenotype codes or words', () => {
    expect(parseStatus(2)).toBe('affected');
    expect(parseStatus('affected')).toBe('affected');
    expect(parseStatus(1)).toBe('unaffected');
    expect(parseStatus('Unaffected')).toBe('unaffected');
    expect(parseStatus(0)).toBe('unknown');
    expect(parseStatus(-9)).toBe('unknown');
    expect(parseStatus('-9')).toBe('unknown');
    expect(parseStatus(null)).toBe('unknown');
  });

  it('reads 0, empty, dot and null parents as founders', () => {
    for (const v of [0, '0', '', null, undefined, '.', 'NA', 0.0, '0.0']) {
      expect(parseParentId(v), String(v)).toBeNull();
    }
    expect(parseParentId('dad')).toBe('dad');
    expect(parseParentId(12)).toBe('12');
    expect(parseParentId('12.0')).toBe('12');
  });

  it('keeps identifiers as text, whatever the dtype', () => {
    expect(parseIndividualId(3)).toBe('3');
    expect(parseIndividualId(' HG002 ')).toBe('HG002');
    expect(parseIndividualId(null)).toBe('');
  });

  it('reads a deceased flag', () => {
    expect(parseDeceased(1)).toBe(true);
    expect(parseDeceased('true')).toBe(true);
    expect(parseDeceased('Deceased')).toBe(true);
    expect(parseDeceased(0)).toBe(false);
    expect(parseDeceased('')).toBe(false);
    expect(parseDeceased(null)).toBe(false);
  });
});

describe('buildPedigree', () => {
  it('keeps one person per identifier and counts the repeats', () => {
    const input = buildPedigree(
      frame([
        { individual: 'a', sex: 1 },
        { individual: 'a', sex: 2 },
        { individual: 'b', sex: 2 },
        { individual: '' },
      ]),
      COLUMNS,
      LIMITS,
    );
    expect(input.families).toHaveLength(1);
    expect(input.families[0].people.map((p) => p.id)).toEqual(['a', 'b']);
    expect(input.families[0].people[0].sex).toBe('male');
    expect(input.duplicates).toBe(1);
  });

  it('labels a person by the label column, else by its identifier', () => {
    const rows = frame([{ individual: 'a' }, { individual: 'b' }]);
    rows.name = ['Anna', ''];
    const input = buildPedigree(rows, { ...COLUMNS, label: 'name' }, LIMITS);
    expect(input.families[0].people.map((p) => p.label)).toEqual(['Anna', 'b']);
  });

  it('carries the table row, for the hover', () => {
    const input = buildPedigree(
      frame([{ individual: 'a', sex: 2, status: 2 }]),
      COLUMNS,
      LIMITS,
    );
    expect(input.families[0].people[0].row).toMatchObject({
      individual: 'a',
      sex: 2,
      status: 2,
    });
  });

  it('keeps whole families and counts the ones the guards leave out', () => {
    const rows = frame([
      { individual: 'a1', family: 'A' },
      { individual: 'a2', family: 'A' },
      { individual: 'b1', family: 'B' },
      { individual: 'c1', family: 'C' },
    ]);
    const byFamilies = buildPedigree(rows, { ...COLUMNS, family: 'family' }, {
      maxIndividuals: 300,
      maxFamilies: 2,
    });
    expect(byFamilies.families.map((f) => f.id)).toEqual(['A', 'B']);
    expect(byFamilies.hiddenFamilies).toBe(1);
    const bySize = buildPedigree(rows, { ...COLUMNS, family: 'family' }, {
      maxIndividuals: 3,
      maxFamilies: 12,
    });
    expect(bySize.families.map((f) => f.id)).toEqual(['A', 'B']);
    expect(bySize.hiddenIndividuals).toBe(1);
    // The first family is kept even when it alone passes the guard
    const tiny = buildPedigree(rows, { ...COLUMNS, family: 'family' }, {
      maxIndividuals: 1,
      maxFamilies: 12,
    });
    expect(tiny.families.map((f) => f.id)).toEqual(['A']);
  });
});

describe('layoutPedigree: a trio', () => {
  const layout = laidOut([
    { individual: 'dad', sex: 1, status: 1 },
    { individual: 'mum', sex: 2, status: 1 },
    { individual: 'kid', father: 'dad', mother: 'mum', sex: 1, status: 2 },
  ]);
  const family = layout.families[0];

  it('puts the parents on the first row and the child under them', () => {
    expect(find(family, 'dad').generation).toBe(0);
    expect(find(family, 'mum').generation).toBe(0);
    expect(find(family, 'kid').generation).toBe(1);
    expect(find(family, 'kid').y).toBeGreaterThan(find(family, 'dad').y);
    expect(find(family, 'dad').y).toBe(find(family, 'mum').y);
  });

  it('centres the child under the couple, the father on the left', () => {
    const dad = find(family, 'dad');
    const mum = find(family, 'mum');
    const kid = find(family, 'kid');
    expect(dad.x).toBeLessThan(mum.x);
    expect(kid.x).toBeCloseTo((dad.x + mum.x) / 2);
  });

  it('draws a couple line, a drop, a sibship bar and a tick per child', () => {
    const kinds = family.lines.map((l) => l.kind).sort();
    expect(kinds).toEqual(['child', 'couple', 'drop', 'sibship']);
    const couple = family.lines.find((l) => l.kind === 'couple')!;
    const dad = find(family, 'dad');
    const mum = find(family, 'mum');
    // Between the two symbols, stopping at their borders
    expect(couple.x1).toBeGreaterThan(dad.x);
    expect(couple.x2).toBeLessThan(mum.x);
    expect(couple.y1).toBe(dad.y);
    const drop = family.lines.find((l) => l.kind === 'drop')!;
    expect(drop.x1).toBeCloseTo((dad.x + mum.x) / 2);
    expect(drop.y1).toBe(dad.y);
    const tick = family.lines.find((l) => l.kind === 'child')!;
    expect(tick.x1).toBeCloseTo(find(family, 'kid').x);
    expect(tick.y2).toBeLessThan(find(family, 'kid').y);
  });

  it('has a size that holds every symbol', () => {
    expect(layout.width).toBeGreaterThan(0);
    for (const p of family.people) {
      expect(p.x).toBeGreaterThan(0);
      expect(p.x).toBeLessThan(layout.width);
      expect(p.y).toBeLessThan(layout.height);
    }
  });

  it('keeps sex and status on the placed person', () => {
    expect(find(family, 'kid').person.sex).toBe('male');
    expect(find(family, 'kid').person.status).toBe('affected');
    expect(find(family, 'mum').person.sex).toBe('female');
    expect(find(family, 'mum').person.status).toBe('unaffected');
  });
});

describe('layoutPedigree: founders only', () => {
  const layout = laidOut([
    { individual: 'a', sex: 1 },
    { individual: 'b', sex: 2 },
    { individual: 'c', sex: 0 },
  ]);
  const family = layout.families[0];

  it('puts everyone on the first row, side by side, with no lines', () => {
    expect(family.people.every((p) => p.generation === 0)).toBe(true);
    const xs = family.people.map((p) => p.x).sort((a, b) => a - b);
    expect(new Set(xs).size).toBe(3);
    expect(xs[1] - xs[0]).toBeGreaterThan(0);
    expect(family.lines).toEqual([]);
    expect(family.generations).toBe(1);
  });

  it('draws nothing for an empty table', () => {
    const empty = layoutPedigree(buildPedigree({}, COLUMNS, LIMITS));
    expect(empty.families).toEqual([]);
    expect(empty.width).toBe(0);
    expect(empty.height).toBe(0);
  });
});

describe('layoutPedigree: several generations', () => {
  const layout = laidOut([
    { individual: 'gf', sex: 1 },
    { individual: 'gm', sex: 2 },
    { individual: 'dad', father: 'gf', mother: 'gm', sex: 1 },
    { individual: 'aunt', father: 'gf', mother: 'gm', sex: 2 },
    // marries into the family, with parents of her own that the table lacks
    { individual: 'mum', sex: 2 },
    { individual: 'kid1', father: 'dad', mother: 'mum', sex: 2, status: 2 },
    { individual: 'kid2', father: 'dad', mother: 'mum', sex: 1 },
  ]);
  const family = layout.families[0];

  it('assigns one row per generation', () => {
    expect(find(family, 'gf').generation).toBe(0);
    expect(find(family, 'dad').generation).toBe(1);
    expect(find(family, 'aunt').generation).toBe(1);
    expect(find(family, 'kid1').generation).toBe(2);
    expect(family.generations).toBe(3);
  });

  it('lowers a founder who marries in to the row of her partner', () => {
    expect(find(family, 'mum').generation).toBe(1);
    expect(find(family, 'mum').y).toBe(find(family, 'dad').y);
  });

  it('keeps the siblings in table order, and centred under their parents', () => {
    expect(find(family, 'dad').x).toBeLessThan(find(family, 'aunt').x);
    expect(find(family, 'kid1').x).toBeLessThan(find(family, 'kid2').x);
    const mid = (find(family, 'dad').x + find(family, 'mum').x) / 2;
    expect((find(family, 'kid1').x + find(family, 'kid2').x) / 2).toBeCloseTo(mid);
  });

  it('never stacks two symbols on one spot', () => {
    const seen = new Set(family.people.map((p) => `${p.x}:${p.y}`));
    expect(seen.size).toBe(family.people.length);
    const row = family.people.filter((p) => p.generation === 1).map((p) => p.x).sort((a, b) => a - b);
    for (let i = 1; i < row.length; i += 1) expect(row[i] - row[i - 1]).toBeGreaterThanOrEqual(64);
  });

  it('draws two sibships', () => {
    expect(family.lines.filter((l) => l.kind === 'drop')).toHaveLength(2);
    expect(family.lines.filter((l) => l.kind === 'couple')).toHaveLength(2);
    expect(family.lines.filter((l) => l.kind === 'child')).toHaveLength(4);
  });
});

describe('layoutPedigree: a person with two partners', () => {
  const family = laidOut([
    { individual: 'm1', sex: 2 },
    { individual: 'dad', sex: 1 },
    { individual: 'm2', sex: 2 },
    { individual: 'c1', father: 'dad', mother: 'm1' },
    { individual: 'c2', father: 'dad', mother: 'm2' },
  ]).families[0];

  it('sits between the partners, so no couple line crosses a symbol', () => {
    const [m1, dad, m2] = ['m1', 'dad', 'm2'].map((id) => find(family, id).x);
    expect(dad).toBeGreaterThan(Math.min(m1, m2));
    expect(dad).toBeLessThan(Math.max(m1, m2));
    expect(find(family, 'c1').generation).toBe(1);
    expect(find(family, 'c2').generation).toBe(1);
    expect(family.lines.filter((l) => l.kind === 'couple')).toHaveLength(2);
  });

  it('groups the children of each couple on the side of their mother', () => {
    const side = (id: string) => Math.sign(find(family, id).x - find(family, 'dad').x);
    expect(side('m1')).toBe(-side('m2'));
    expect(side('c1')).toBe(side('m1'));
    expect(side('c2')).toBe(side('m2'));
  });
});

describe('layoutPedigree: two families', () => {
  const rows: Row[] = [
    { individual: 'a-dad', family: 'A', sex: 1 },
    { individual: 'a-mum', family: 'A', sex: 2 },
    { individual: 'a-kid', family: 'A', father: 'a-dad', mother: 'a-mum' },
    { individual: 'b-dad', family: 'B', sex: 1 },
    { individual: 'b-mum', family: 'B', sex: 2 },
    { individual: 'b-kid', family: 'B', father: 'b-dad', mother: 'b-mum' },
    { individual: 'b-kid2', family: 'B', father: 'b-dad', mother: 'b-mum' },
  ];
  const layout = laidOut(rows, { ...COLUMNS, family: 'family' });

  it('draws one band per family, side by side, without overlap', () => {
    expect(layout.families.map((f) => f.id)).toEqual(['A', 'B']);
    const [a, b] = layout.families;
    expect(a.x).toBe(0);
    expect(b.x).toBeGreaterThanOrEqual(a.x + a.width);
    for (const p of a.people) {
      expect(p.x).toBeGreaterThan(a.x);
      expect(p.x).toBeLessThan(a.x + a.width);
    }
    for (const p of b.people) {
      expect(p.x).toBeGreaterThan(b.x);
      expect(p.x).toBeLessThan(b.x + b.width);
    }
    expect(layout.width).toBeGreaterThanOrEqual(b.x + b.width);
  });

  it('shares one height across the families', () => {
    expect(layout.height).toBeGreaterThan(0);
    for (const f of layout.families) {
      for (const p of f.people) expect(p.y).toBeLessThan(layout.height);
    }
  });

  it('resolves a parent inside its own family only', () => {
    const same = laidOut(
      [
        { individual: 'x', family: 'A', sex: 1 },
        { individual: 'kid', family: 'B', father: 'x' },
      ],
      { ...COLUMNS, family: 'family' },
    );
    const b = same.families.find((f) => f.id === 'B')!;
    // 'x' is not in family B, so B holds a placeholder for it
    expect(b.people.find((p) => p.person.id === 'x')?.person.placeholder).toBe(true);
    expect(b.people.find((p) => p.person.id === 'kid')?.generation).toBe(1);
  });
});

describe('layoutPedigree: a parent named but missing from the table', () => {
  const layout = laidOut([
    { individual: 'kid', father: 'dad', mother: 'mum', sex: 2, status: 2 },
    { individual: 'sib', father: 'dad', mother: 'mum', sex: 1 },
  ]);
  const family = layout.families[0];

  it('adds a placeholder of the sex the role implies', () => {
    const dad = find(family, 'dad');
    const mum = find(family, 'mum');
    expect(dad.person.placeholder).toBe(true);
    expect(dad.person.sex).toBe('male');
    expect(dad.person.status).toBe('unknown');
    expect(mum.person.sex).toBe('female');
    expect(find(family, 'kid').person.placeholder).toBe(false);
  });

  it('still joins the children to the couple', () => {
    expect(find(family, 'dad').generation).toBe(0);
    expect(find(family, 'kid').generation).toBe(1);
    expect(family.lines.map((l) => l.kind).sort()).toEqual([
      'child',
      'child',
      'couple',
      'drop',
      'sibship',
    ]);
  });

  it('handles a single known parent with a drop from under its label', () => {
    const single = laidOut([
      { individual: 'mum', sex: 2 },
      { individual: 'kid', mother: 'mum' },
    ]).families[0];
    const drop = single.lines.find((l) => l.kind === 'drop')!;
    expect(drop.x1).toBe(find(single, 'mum').x);
    expect(drop.y1).toBeGreaterThan(find(single, 'mum').y);
    expect(single.lines.some((l) => l.kind === 'couple')).toBe(false);
  });
});

describe('layoutPedigree: malformed tables', () => {
  it('draws a person who is their own parent as a founder', () => {
    const family = laidOut([{ individual: 'a', father: 'a', mother: 'a' }]).families[0];
    expect(family.people).toHaveLength(1);
    expect(find(family, 'a').generation).toBe(0);
  });

  it('breaks a loop of descent instead of recursing forever', () => {
    const family = laidOut([
      { individual: 'a', father: 'b' },
      { individual: 'b', father: 'a' },
    ]).families[0];
    expect(family.people).toHaveLength(2);
    const gens = family.people.map((p) => p.generation).sort();
    expect(gens[0]).toBe(0);
    for (const p of family.people) expect(Number.isFinite(p.x)).toBe(true);
  });

  it('places a couple of two founders who each have another partner', () => {
    const family = laidOut([
      { individual: 'f', sex: 1 },
      { individual: 'm', sex: 2 },
      { individual: 'k', father: 'f', mother: 'm' },
      { individual: 'm2', sex: 2 },
      { individual: 'k2', father: 'f', mother: 'm2' },
    ]).families[0];
    expect(family.people).toHaveLength(5);
    expect(new Set(family.people.map((p) => `${p.x}:${p.y}`)).size).toBe(5);
  });
});

describe('personKey', () => {
  it('separates families', () => {
    expect(personKey('A', 'x')).not.toBe(personKey('B', 'x'));
  });
});
