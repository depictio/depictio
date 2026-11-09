import { describe, expect, it } from 'vitest';

import type { DropMatch } from './annotationInput';
import { planAnnotationMerge, suggestedMergeMode } from './annotationMerge';
import type { DashboardAnnotations } from './sessionAnnotations';

const current = (): DashboardAnnotations => ({
  version: 1,
  dcId: 'dc1',
  keyColumn: 'sample',
  columns: [{ id: 'c1', name: 'response', values: { S1: 'yes', S2: 'no' } }],
  activeColumnId: 'c1',
});

const match = (annotations: DropMatch['annotations']): DropMatch => ({
  fileKeyColumn: 'sample',
  annotations,
  matchedRows: 3,
  unmatchedRows: 0,
  unmatchedSample: [],
});

let n = 0;
const ids = () => `new${(n += 1)}`;

describe('planAnnotationMerge', () => {
  it('add columns: new names become local annotations, existing ones are left alone', () => {
    const m = match([
      { name: 'cohort', values: { S1: 'early', S3: 'late' } },
      { name: 'response', values: { S3: 'yes' } },
    ]);
    const { next, report } = planAnnotationMerge(current(), m, 'add_columns', ids);
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
    const { next, report } = planAnnotationMerge(current(), m, 'fill_missing', ids);
    expect(next.columns[0].values).toEqual({ S1: 'yes', S2: 'no', S3: 'yes' });
    expect(next.columns[0].local).toBe(true);
    expect(report).toMatchObject({ updatedAnnotations: ['response'], labels: 1, conflicts: 1, reason: null });
  });

  it('replace: the file becomes the whole set, keeping the compared name', () => {
    const m = match([
      { name: 'response', values: { S3: 'yes' } },
      { name: 'cohort', values: { S1: 'early' } },
    ]);
    const { next, report } = planAnnotationMerge(current(), m, 'replace', ids);
    expect(next.columns.map((c) => c.name)).toEqual(['response', 'cohort']);
    expect(next.columns.every((c) => c.local)).toBe(true);
    expect(next.columns[0].values).toEqual({ S3: 'yes' });
    expect(next.activeColumnId).toBe(next.columns[0].id);
    expect(report.removedAnnotations).toEqual(['response']);
  });

  it('says why when there is nothing to apply', () => {
    const add = planAnnotationMerge(current(), match([{ name: 'response', values: { S9: 'x' } }]), 'add_columns', ids);
    expect(add.report.reason).toMatch(/already an annotation/);
    const fill = planAnnotationMerge(current(), match([{ name: 'response', values: { S1: 'yes' } }]), 'fill_missing', ids);
    expect(fill.report.reason).toMatch(/Nothing to fill/);
  });

  it('refuses a result over the caps', () => {
    const many = Array.from({ length: 20 }, (_, i) => ({ name: `a${i}`, values: { S1: 'x' } }));
    expect(planAnnotationMerge(current(), match(many), 'add_columns', ids).report.reason).toMatch(/At most 20/);
  });
});

describe('suggestedMergeMode', () => {
  it('fills when the file names only existing annotations, else adds', () => {
    expect(suggestedMergeMode(current(), match([{ name: 'response', values: {} }]))).toBe('fill_missing');
    expect(suggestedMergeMode(current(), match([{ name: 'cohort', values: {} }]))).toBe('add_columns');
  });
});
