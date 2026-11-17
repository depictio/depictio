import { describe, expect, it } from 'vitest';

import { hoverColumnList, hoverRow, hoverTemplateLines } from './hoverColumns';

describe('hoverColumnList', () => {
  it('keeps the order and drops blanks and repeats', () => {
    expect(hoverColumnList(['GENE', '', 'AA', 'GENE'])).toEqual(['GENE', 'AA']);
  });

  it('tolerates no list', () => {
    expect(hoverColumnList(undefined)).toEqual([]);
    expect(hoverColumnList(null)).toEqual([]);
  });
});

describe('hoverRow', () => {
  it('reads one row across the columns, blanking missing values', () => {
    const columns = [['a', 'b'], [1, null], [undefined, 'z']];
    expect(hoverRow(columns, 0)).toEqual(['a', 1, '']);
    expect(hoverRow(columns, 1)).toEqual(['b', '', 'z']);
    expect(hoverRow([], 0)).toEqual([]);
  });
});

describe('hoverTemplateLines', () => {
  it('numbers the lines from the first free customdata slot', () => {
    expect(hoverTemplateLines(['GENE', 'DP'], 3)).toBe(
      '<br>GENE: %{customdata[3]}<br>DP: %{customdata[4]}',
    );
    expect(hoverTemplateLines([], 3)).toBe('');
  });
});
