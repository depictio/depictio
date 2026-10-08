import { describe, expect, it } from 'vitest';

import {
  buildRowAnnotationMap,
  EMPTY_ROW_ANNOTATIONS,
  exportColumnKeys,
  markedRowsFromSelection,
  rowAnnotationContentKey,
  rowAnnotationBadge,
  rowAnnotationClasses,
} from './tableRows';
import type { Annotation, RenderableAnnotation } from './types';
import { MAX_POINT_IDS } from './types';

function item(
  id: string,
  number: number | null,
  annotation: Partial<Annotation> & Pick<Annotation, 'geometry'>,
): RenderableAnnotation {
  return {
    id,
    number,
    annotation: { kind: 'points', label: id, ...annotation } as Annotation,
  };
}

const rows = (column: string, ids: Array<string | number>) =>
  ({ geometry: { kind: 'points', column, ids } }) as const;

describe('buildRowAnnotationMap', () => {
  it('is empty without a row-id column', () => {
    expect(buildRowAnnotationMap([item('a', 1, rows('id', [1]))], undefined).size).toBe(0);
  });

  it('maps stringified ids to colour, number and badge numbers', () => {
    const map = buildRowAnnotationMap([item('a', 2, { ...rows('id', [1, 'x']), color: 'blue' })], 'id');
    expect(map.get('1')).toEqual({ id: 'a', color: 'blue', number: 2, highlighted: false, numbers: [2] });
    expect(map.get('x')?.id).toBe('a');
  });

  it('defaults to yellow and ignores unknown colours', () => {
    const map = buildRowAnnotationMap(
      [
        item('a', 1, rows('id', [1])),
        item('b', 2, { ...rows('id', [2]), color: 'chartreuse' as never }),
      ],
      'id',
    );
    expect(map.get('1')?.color).toBe('yellow');
    expect(map.get('2')?.color).toBe('yellow');
  });

  it('ignores other columns, coordinates and non-point geometries', () => {
    const map = buildRowAnnotationMap(
      [
        item('a', 1, rows('other', [1])),
        item('b', 2, { geometry: { kind: 'points', coords: [{ x: 1, y: 2 }] } }),
        item('c', 3, { kind: 'range', geometry: { kind: 'x_range', x0: 0, x1: 1 } }),
      ],
      'id',
    );
    expect(map.size).toBe(0);
  });

  it('gives an overlapped row to the lowest number, listing every badge', () => {
    const map = buildRowAnnotationMap(
      [
        item('late', 3, { ...rows('id', [1, 2]), color: 'red' }),
        item('none', null, { ...rows('id', [1]), color: 'gray' }),
        item('early', 1, { ...rows('id', [1]), color: 'teal' }),
      ],
      'id',
    );
    expect(map.get('1')).toMatchObject({ id: 'early', color: 'teal', numbers: [1, 3] });
    expect(map.get('2')).toMatchObject({ id: 'late', numbers: [3] });
  });

  it('lets the focused annotation claim its rows', () => {
    const map = buildRowAnnotationMap(
      [item('a', 1, rows('id', [1])), item('b', 2, { ...rows('id', [1]), color: 'grape' })],
      'id',
      'b',
    );
    expect(map.get('1')).toMatchObject({ id: 'b', color: 'grape', highlighted: true, numbers: [1, 2] });
  });
});

describe('row classes and badge', () => {
  it('builds classes per palette name and flags the focused one', () => {
    expect(rowAnnotationClasses(undefined)).toEqual([]);
    expect(
      rowAnnotationClasses({ id: 'a', color: 'blue', number: 1, highlighted: true, numbers: [1] }),
    ).toEqual(['depictio-row-annotated', 'depictio-row-annotated-blue', 'depictio-row-annotated-active']);
  });
  it('renders circled numbers', () => {
    expect(rowAnnotationBadge(undefined)).toBe('');
    expect(
      rowAnnotationBadge({ id: 'a', color: 'blue', number: 1, highlighted: false, numbers: [1, 3] }),
    ).toBe('①③');
  });
});

describe('markedRowsFromSelection', () => {
  it('collects distinct ids from the row-id column', () => {
    expect(
      markedRowsFromSelection([{ id: 1 }, { id: 'b' }, { id: 1 }, { id: null }, null, { other: 3 }], 'id'),
    ).toEqual({ kind: 'points', column: 'id', ids: [1, 'b'] });
  });
  it('is null for an empty selection', () => {
    expect(markedRowsFromSelection([], 'id')).toBeNull();
    expect(markedRowsFromSelection([{ id: NaN }], 'id')).toBeNull();
  });
  it('caps the ids', () => {
    const many = Array.from({ length: MAX_POINT_IDS + 10 }, (_, i) => ({ id: i }));
    expect(markedRowsFromSelection(many, 'id')?.ids).toHaveLength(MAX_POINT_IDS);
  });
});

describe('row annotation map identity', () => {
  it('returns the shared empty map when nothing applies', () => {
    expect(buildRowAnnotationMap([], 'id')).toBe(EMPTY_ROW_ANNOTATIONS);
    expect(buildRowAnnotationMap([item('a', 1, rows('id', [1]))], null)).toBe(EMPTY_ROW_ANNOTATIONS);
    expect(buildRowAnnotationMap([item('a', 1, rows('other', [1]))], 'id', 'a')).toBe(
      EMPTY_ROW_ANNOTATIONS,
    );
  });
});

describe('rowAnnotationContentKey', () => {
  const items = [item('a', 1, rows('id', [1, 2])), item('b', 2, rows('other', [3]))];
  it('is empty when no annotation marks rows of the column', () => {
    expect(rowAnnotationContentKey([], 'id')).toBe('');
    expect(rowAnnotationContentKey(items, null)).toBe('');
    expect(rowAnnotationContentKey(items, 'missing', 'a')).toBe('');
  });
  it('ignores a focused thread that marks no row of this table', () => {
    expect(rowAnnotationContentKey(items, 'id', 'b')).toBe(rowAnnotationContentKey(items, 'id', null));
    expect(rowAnnotationContentKey(items, 'id', 'zzz')).toBe(rowAnnotationContentKey(items, 'id'));
    expect(rowAnnotationContentKey(items, 'id', 'a')).not.toBe(rowAnnotationContentKey(items, 'id'));
  });
  it('is equal for equal content in new arrays and changes with the rows', () => {
    const copy = [item('a', 1, rows('id', [1, 2])), item('b', 2, rows('other', [3]))];
    expect(rowAnnotationContentKey(copy, 'id')).toBe(rowAnnotationContentKey(items, 'id'));
    const moved = [item('a', 1, rows('id', [1, 4]))];
    expect(rowAnnotationContentKey(moved, 'id')).not.toBe(rowAnnotationContentKey(items, 'id'));
    const recolored = [item('a', 1, { ...rows('id', [1, 2]), color: 'blue' })];
    expect(rowAnnotationContentKey(recolored, 'id')).not.toBe(rowAnnotationContentKey(items, 'id'));
  });
});

describe('exportColumnKeys', () => {
  it('drops the badge column and keeps the displayed order', () => {
    expect(exportColumnKeys(['__badge', 'b', 'a'], '__badge')).toEqual(['b', 'a']);
  });
  it('is null when the badge column is not displayed', () => {
    expect(exportColumnKeys(['b', 'a'], '__badge')).toBeNull();
  });
});
