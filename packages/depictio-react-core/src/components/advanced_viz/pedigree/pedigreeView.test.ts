import { describe, expect, it } from 'vitest';

import type { PedigreeFamily, Person } from './pedigreeLayout';
import { hasAffected, personLabel, spacedLayout, visibleFamilies } from './pedigreeView';

function person(id: string, status: Person['status'], placeholder = false): Person {
  return {
    key: id,
    id,
    family: 'f',
    fatherKey: null,
    motherKey: null,
    sex: 'female',
    status,
    deceased: false,
    label: `label-${id}`,
    row: {},
    placeholder,
  };
}

const families: PedigreeFamily[] = [
  { id: 'A', people: [person('a1', 'unaffected'), person('a2', 'affected')] },
  { id: 'B', people: [person('b1', 'unaffected'), person('b2', 'unknown')] },
  { id: 'C', people: [person('c1', 'unaffected'), person('c2', 'affected', true)] },
];

describe('hasAffected', () => {
  it('counts a real affected member, not a placeholder', () => {
    expect(hasAffected(families[0])).toBe(true);
    expect(hasAffected(families[1])).toBe(false);
    expect(hasAffected(families[2])).toBe(false);
  });
});

describe('visibleFamilies', () => {
  it('shows every family by default', () => {
    expect(visibleFamilies(families, {}).map((f) => f.id)).toEqual(['A', 'B', 'C']);
  });
  it('focuses one family, and falls back to all when it is gone', () => {
    expect(visibleFamilies(families, { focus: 'B' }).map((f) => f.id)).toEqual(['B']);
    expect(visibleFamilies(families, { focus: 'Z' }).map((f) => f.id)).toEqual(['A', 'B', 'C']);
  });
  it('keeps affected families only, alone or with a focus', () => {
    expect(visibleFamilies(families, { affectedOnly: true }).map((f) => f.id)).toEqual(['A']);
    expect(visibleFamilies(families, { focus: 'B', affectedOnly: true })).toEqual([]);
  });
});

describe('personLabel', () => {
  it('writes the label column or the identifier', () => {
    expect(personLabel({ id: 'x', label: 'proband' }, 'label')).toBe('proband');
    expect(personLabel({ id: 'x', label: 'proband' }, 'id')).toBe('x');
  });
});

describe('spacedLayout', () => {
  it('keeps the requested spacing when it clears the symbol and its label', () => {
    expect(spacedLayout(28, 96, 18)).toEqual({ symbol: 28, rowHeight: 96 });
  });
  it('widens the spacing when a big symbol would touch the next generation', () => {
    expect(spacedLayout(48, 60, 18)).toEqual({ symbol: 48, rowHeight: 90 });
  });
});
