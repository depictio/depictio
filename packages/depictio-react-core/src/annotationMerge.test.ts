import { describe, expect, it } from 'vitest';

import type { DropMatch } from './annotationInput';
import { planAnnotationMerge, suggestedMergeMode } from './annotationMerge';
import type { DashboardAnnotations } from './sessionAnnotations';

const current = (): DashboardAnnotations => ({
  version: 2,
  columns: [{ id: 'c1', name: 'response', dcId: 'dc1', keyColumn: 'sample', values: { S1: 'yes', S2: 'no' } }],
  activeColumnId: 'c1',
});

const match = (annotations: DropMatch['annotations']): DropMatch => ({
  fileKeyColumn: 'sample',
  annotations,
  matchedRows: 3,
  unmatchedRows: 0,
  unmatchedSample: [],
});

const T = { dcId: 'dc1', keyColumn: 'sample' };

let n = 0;
const ids = () => `new${(n += 1)}`;

describe('planAnnotationMerge', () => {
  it('add columns: new names become local annotations, existing ones are left alone', () => {
    const m = match([
      { name: 'cohort', values: { S1: 'early', S3: 'late' } },
      { name: 'response', values: { S3: 'yes' } },
    ]);
    const { next, report } = planAnnotationMerge(current(), T, m, 'add_columns', ids);
    expect(next.columns.map((c) => [c.name, Boolean(c.local)])).toEqual([
      ['response', false],
      ['cohort', true],
    ]);
    expect(next.columns[0].values).toEqual({ S1: 'yes', S2: 'no' });
    expect(report).toMatchObject({
      newAnnotations: ['cohort'],
      ignored: [{ name: 'response', reason: 'already an annotation' }],
      labels: 2,
      reason: null,
    });
    expect(next.activeColumnId).toBe('c1');
  });

  it('fill missing: only empty labels are written, differing ones are counted and kept', () => {
    const m = match([{ name: 'response', values: { S1: 'no', S2: 'no', S3: 'yes' } }]);
    const { next, report } = planAnnotationMerge(current(), T, m, 'fill_missing', ids);
    expect(next.columns[0].values).toEqual({ S1: 'yes', S2: 'no', S3: 'yes' });
    expect(next.columns[0].local).toBe(true);
    expect(report).toMatchObject({ updatedAnnotations: ['response'], labels: 1, conflicts: 1, reason: null });
  });

  it('replace: the file becomes the whole set, keeping the compared name', () => {
    const m = match([
      { name: 'response', values: { S3: 'yes' } },
      { name: 'cohort', values: { S1: 'early' } },
    ]);
    const { next, report } = planAnnotationMerge(current(), T, m, 'replace', ids);
    expect(next.columns.map((c) => c.name)).toEqual(['response', 'cohort']);
    expect(next.columns.every((c) => c.local)).toBe(true);
    expect(next.columns[0].values).toEqual({ S3: 'yes' });
    expect(next.activeColumnId).toBe(next.columns[0].id);
    expect(report.removedAnnotations).toEqual(['response']);
  });

  it('says why when there is nothing to apply', () => {
    const add = planAnnotationMerge(current(), T, match([{ name: 'response', values: { S9: 'x' } }]), 'add_columns', ids);
    expect(add.report.reason).toMatch(/already an annotation/);
    const fill = planAnnotationMerge(current(), T, match([{ name: 'response', values: { S1: 'yes' } }]), 'fill_missing', ids);
    expect(fill.report.reason).toMatch(/Nothing to fill/);
  });

  it('refuses a result over the caps', () => {
    const many = Array.from({ length: 20 }, (_, i) => ({ name: `a${i}`, values: { S1: 'x' } }));
    expect(planAnnotationMerge(current(), T, match(many), 'add_columns', ids).report.reason).toMatch(/At most 20/);
  });
});

describe('suggestedMergeMode', () => {
  it('fills when the file names only existing annotations, else adds', () => {
    expect(suggestedMergeMode(current(), T, match([{ name: 'response', values: {} }]))).toBe('fill_missing');
    expect(suggestedMergeMode(current(), T, match([{ name: 'cohort', values: {} }]))).toBe('add_columns');
  });
});

describe('planAnnotationMerge across tables', () => {
  const two = (): DashboardAnnotations => ({
    ...current(),
    columns: [
      ...current().columns,
      { id: 'm1', name: 'site', dcId: 'dc2', keyColumn: 'sample_id', values: { A: 'x' } },
    ],
    activeColumnId: 'm1',
  });

  it('writes the target table only and keeps the labels of another table', () => {
    const m = match([{ name: 'cohort', values: { S1: 'early' } }]);
    const { next } = planAnnotationMerge(two(), T, m, 'add_columns', ids);
    expect(next.columns.map((c) => [c.name, c.dcId, c.keyColumn])).toEqual([
      ['response', 'dc1', 'sample'],
      ['site', 'dc2', 'sample_id'],
      ['cohort', 'dc1', 'sample'],
    ]);
    expect(next.activeColumnId).toBe('m1');
  });

  it('replace drops only the target table labels, active elsewhere stays', () => {
    const m = match([{ name: 'cohort', values: { S1: 'early' } }]);
    const { next, report } = planAnnotationMerge(two(), T, m, 'replace', ids);
    expect(next.columns.map((c) => c.name)).toEqual(['site', 'cohort']);
    expect(report.removedAnnotations).toEqual(['response']);
    expect(next.activeColumnId).toBe('m1');
  });

  it('leaves out a file column named like labels of another table', () => {
    const m = match([{ name: 'site', values: { S1: 'y' } }]);
    const { next, report } = planAnnotationMerge(two(), T, m, 'add_columns', ids);
    expect(report.ignored).toEqual([{ name: 'site', reason: 'name used by labels of another table' }]);
    expect(next.columns.filter((c) => c.name === 'site')).toHaveLength(1);
  });
});
