import { describe, expect, it } from 'vitest';

import {
  annotationColumnBudget,
  deriveAnnotationGroups,
  distinctLabels,
  sameGroups,
} from './annotationGroups';
import type { DashboardAnnotations } from './annotations';
import type { SelectionGroup } from './selectionGroups';

const PALETTE = ['#a', '#b', '#c', '#d'];

const annotations = (values: Record<string, string>, active: string | null = 'c1'): DashboardAnnotations => ({
  version: 1,
  dcId: 'dc1',
  keyColumn: 'sample',
  columns: [
    { id: 'c1', name: 'response', values },
    { id: 'c2', name: 'batch', values: { S1: 'b1', S2: 'b2' } },
  ],
  activeColumnId: active,
});

const lasso: SelectionGroup = {
  id: 'grp-1',
  name: 'Lasso',
  color: '#a',
  dcId: 'dc1',
  columnName: 'sample',
  values: ['S9'],
  createdAt: 1,
  filterActive: true,
};

describe('deriveAnnotationGroups', () => {
  it('makes one group per distinct label, keyed on the key column', () => {
    const out = deriveAnnotationGroups(annotations({ S1: 'yes', S2: 'no', S3: 'yes' }), [], PALETTE, 5);
    expect(out.map((g) => [g.name, g.values, g.columnName, g.dcId])).toEqual([
      ['no', ['S2'], 'sample', 'dc1'],
      ['yes', ['S1', 'S3'], 'sample', 'dc1'],
    ]);
    expect(out.every((g) => g.annotationColumnId === 'c1' && !g.filterActive)).toBe(true);
  });

  it('leaves lasso and table groups untouched and avoids their colours', () => {
    const out = deriveAnnotationGroups(annotations({ S1: 'yes' }), [lasso], PALETTE, 5);
    expect(out[0]).toBe(lasso);
    expect(out[1].color).toBe('#b');
  });

  it('keeps a label colour and filter toggle across recomputation', () => {
    const first = deriveAnnotationGroups(annotations({ S1: 'yes', S2: 'no' }), [], PALETTE, 5);
    const toggled = first.map((g) => (g.name === 'yes' ? { ...g, filterActive: true, color: '#d' } : g));
    const next = deriveAnnotationGroups(annotations({ S1: 'yes', S2: 'yes', S3: 'maybe' }), toggled, PALETTE, 9);
    const yes = next.find((g) => g.name === 'yes')!;
    expect(yes).toMatchObject({ color: '#d', filterActive: true, values: ['S1', 'S2'], createdAt: 5 });
    expect(next.map((g) => g.name)).toEqual(['maybe', 'yes']);
  });

  it('replaces the groups of another annotation when the active one changes', () => {
    const first = deriveAnnotationGroups(annotations({ S1: 'yes' }), [lasso], PALETTE);
    const out = deriveAnnotationGroups({ ...annotations({ S1: 'yes' }), activeColumnId: 'c2' }, first, PALETTE);
    expect(out.map((g) => g.name)).toEqual(['Lasso', 'b1', 'b2']);
  });

  it('drops derived groups when nothing is active', () => {
    const first = deriveAnnotationGroups(annotations({ S1: 'yes' }), [lasso], PALETTE);
    expect(deriveAnnotationGroups(annotations({ S1: 'yes' }, null), first)).toEqual([lasso]);
    expect(deriveAnnotationGroups(null, first)).toEqual([lasso]);
  });

  it('renames a label that collides with another group or with "Other"', () => {
    const out = deriveAnnotationGroups(annotations({ S1: 'Lasso', S2: 'Other' }), [lasso], PALETTE);
    expect(out.slice(1).map((g) => [g.name, g.annotationLabel])).toEqual([
      ['Lasso 2', 'Lasso'],
      ['Other 2', 'Other'],
    ]);
  });

  it('derives nothing past the server group cap', () => {
    const many = Object.fromEntries(Array.from({ length: 25 }, (_, i) => [`S${i}`, `L${i}`]));
    expect(deriveAnnotationGroups(annotations(many), [lasso])).toEqual([lasso]);
  });
});

describe('annotationColumnBudget', () => {
  const column = (n: number) => ({
    id: 'c1',
    name: 'r',
    values: Object.fromEntries(Array.from({ length: n }, (_, i) => [`S${i}`, `L${i}`])),
  });
  it('counts the other groups against the 24 the server keeps', () => {
    expect(annotationColumnBudget(column(24), [])).toEqual({ ok: true });
    expect(annotationColumnBudget(column(24), [lasso]).ok).toBe(false);
    expect(annotationColumnBudget(column(23), [lasso])).toEqual({ ok: true });
    const r = annotationColumnBudget(column(25), []);
    expect(r.ok === false && r.reason).toMatch(/at most 24 groups/);
  });
  it('ignores groups the column itself derived', () => {
    const derived = { ...lasso, annotationColumnId: 'c1' };
    expect(annotationColumnBudget(column(24), [derived])).toEqual({ ok: true });
  });
  it('refuses an empty column', () => {
    expect(annotationColumnBudget(column(0), []).ok).toBe(false);
  });
});

describe('helpers', () => {
  it('sorts labels naturally', () => {
    expect(distinctLabels({ id: 'c', name: 'n', values: { a: 'L10', b: 'L2', c: 'L2' } })).toEqual(['L2', 'L10']);
  });
  it('sameGroups compares content', () => {
    const a = deriveAnnotationGroups(annotations({ S1: 'yes' }), [], PALETTE, 1);
    const b = deriveAnnotationGroups(annotations({ S1: 'yes' }), a, PALETTE, 2);
    expect(sameGroups(a, b)).toBe(true);
    const c = deriveAnnotationGroups(annotations({ S1: 'yes', S2: 'yes' }), a, PALETTE, 2);
    expect(sameGroups(a, c)).toBe(false);
  });
});
