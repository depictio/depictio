import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../api';
import { groupsToFilters, type SelectionGroup } from '../../selectionGroups';
import {
  buildValuesMatrix,
  compareCodePoints,
  filterMatrixRows,
  groupStageColor,
  matrixCellLabel,
  matrixSummary,
  resolveStageColumn,
  resolveStageDc,
  splitValues,
  valuesHoverText,
  type ValuesMatrixRow,
} from './funnelStages';

const vals = (values: string[], count = values.length) => ({
  count,
  values,
  truncated: count > values.length,
});

const filterOn = (dcId: string, column: string): InteractiveFilter => ({
  index: `comp-${column}`,
  value: ['x'],
  column_name: column,
  metadata: { dc_id: dcId, column_name: column },
});

const group = (overrides: Partial<SelectionGroup>): SelectionGroup => ({
  id: 'g1',
  name: 'Group 1',
  color: '#1f77b4',
  dcId: 'dc1',
  columnName: 'sample',
  values: ['a'],
  createdAt: 0,
  filterActive: true,
  ...overrides,
});

describe('resolveStageDc', () => {
  it('keeps a pick that is still a candidate', () => {
    expect(resolveStageDc('dc2', filterOn('dc1', 'habitat'), ['dc1', 'dc2'])).toBe('dc2');
  });

  it("falls back to the first filter's DC when the overview charts it", () => {
    expect(resolveStageDc(null, filterOn('dc2', 'habitat'), ['dc1', 'dc2'])).toBe('dc2');
    expect(resolveStageDc('gone', filterOn('dc2', 'habitat'), ['dc1', 'dc2'])).toBe('dc2');
  });

  it('otherwise takes the first candidate', () => {
    expect(resolveStageDc(null, filterOn('dc9', 'habitat'), ['dc1', 'dc2'])).toBe('dc1');
    expect(resolveStageDc(null, undefined, ['dc1'])).toBe('dc1');
  });

  it('trusts the pick or the filter while the candidates are unknown', () => {
    expect(resolveStageDc(null, filterOn('dc9', 'habitat'), [])).toBe('dc9');
    expect(resolveStageDc(null, undefined, [])).toBeNull();
  });
});

describe('resolveStageColumn', () => {
  const first = filterOn('dc1', 'habitat');

  it("uses the filter's column while the schema loads, only on the filter's DC", () => {
    expect(resolveStageColumn(null, first, 'dc1', null)).toBe('habitat');
    expect(resolveStageColumn(null, first, 'dc2', null)).toBeNull();
  });

  it('prefers a valid pick, then the filter column, then the first column', () => {
    expect(resolveStageColumn('depth', first, 'dc1', ['depth', 'habitat'])).toBe('depth');
    expect(resolveStageColumn('gone', first, 'dc1', ['depth', 'habitat'])).toBe('habitat');
    expect(resolveStageColumn(null, first, 'dc2', ['depth', 'habitat'])).toBe('depth');
    expect(resolveStageColumn(null, first, 'dc1', [])).toBeNull();
  });
});

describe('valuesHoverText', () => {
  it('lists the count and every value under the limit', () => {
    expect(valuesHoverText({ count: 2, values: ['a', 'b'], truncated: false })).toBe(
      '2 distinct values<br>a<br>b',
    );
  });

  it('collapses the tail, counting values the server capped away', () => {
    const text = valuesHoverText({ count: 40, values: ['a', 'b', 'c'], truncated: true }, 2);
    expect(text).toBe('40 distinct values<br>a<br>b<br>… and 38 more');
  });

  it('escapes markup and handles a failed stage', () => {
    expect(valuesHoverText({ count: 1, values: ['<b>'], truncated: false })).toBe(
      '1 distinct value<br>&lt;b&gt;',
    );
    expect(valuesHoverText(null)).toBe('No data');
  });
});

describe('splitValues', () => {
  it('never reports a negative remainder', () => {
    expect(splitValues({ count: 1, values: ['a'], truncated: false }, 5)).toEqual({
      shown: ['a'],
      more: 0,
    });
  });
});

describe('buildValuesMatrix', () => {
  const byValue = (rows: ValuesMatrixRow[]) => Object.fromEntries(rows.map((r) => [r.value, r]));

  it('orders rows by how far they survive, then naturally', () => {
    const m = buildValuesMatrix(vals(['T0_R1', 'T0_R2', 'T15_R1', 'T15_R2']), [
      vals(['T0_R1', 'T0_R2', 'T15_R1']),
      vals(['T0_R1', 'T0_R2']),
      vals(['T0_R1']),
    ]);
    expect(m.rows.map((r) => [r.value, r.survives, r.removedAt])).toEqual([
      ['T0_R1', 3, null],
      ['T0_R2', 2, 3],
      ['T15_R1', 1, 2],
      ['T15_R2', 0, 1],
    ]);
    expect(byValue(m.rows).T15_R1.cells).toEqual(['kept', 'kept', 'removed', 'removed']);
    expect(m.counts).toEqual([4, 3, 2, 1]);
    expect(m.removed).toEqual([1, 1, 1]);
    expect(m.unlisted).toBe(0);
    expect(m.hasUnknown).toBe(false);
  });

  it('sorts ties with numbers in numeric order', () => {
    const m = buildValuesMatrix(vals(['S10', 'S2', 'S1']), [vals(['S10', 'S2', 'S1'])]);
    expect(m.rows.map((r) => r.value)).toEqual(['S1', 'S2', 'S10']);
  });

  it('leaves a failed stage unknown until a later stage settles it', () => {
    const m = buildValuesMatrix(vals(['a', 'b', 'c']), [vals(['a', 'b']), null, vals(['a'])]);
    const rows = byValue(m.rows);
    expect(rows.a.cells).toEqual(['kept', 'kept', 'kept', 'kept']);
    expect(rows.b.cells).toEqual(['kept', 'kept', 'unknown', 'removed']);
    expect(rows.b.removedAt).toBe(3);
    expect(rows.c.cells).toEqual(['kept', 'removed', 'removed', 'removed']);
    expect(m.counts).toEqual([3, 2, null, 1]);
    expect(m.removed).toEqual([1, null, null]);
    expect(m.hasUnknown).toBe(true);
  });

  it('stays exact for listed rows when every list is capped the same', () => {
    // Unfiltered {a, b, c, d} and stage {b, c, d}, both capped at two values.
    const m = buildValuesMatrix(vals(['a', 'b'], 4), [vals(['b', 'c'], 3)]);
    expect(m.rows.map((r) => r.value)).toEqual(['b', 'c', 'a']);
    const rows = byValue(m.rows);
    expect(rows.a.cells).toEqual(['kept', 'removed']);
    expect(rows.b.cells).toEqual(['kept', 'kept']);
    expect(rows.c.cells).toEqual(['kept', 'kept']);
    expect(m.unlisted).toBe(1);
    expect(m.hasUnknown).toBe(false);
  });

  it('gives survivors a row when they sort past the unfiltered cap', () => {
    // Thousands of peak ids, the unfiltered list capped at its first three,
    // and a selection keeping two ids that sort after every listed one.
    const m = buildValuesMatrix(vals(['p0001', 'p0002', 'p0003'], 6403), [
      vals(['p5120', 'p6002']),
    ]);
    expect(m.rows.map((r) => [r.value, r.cells])).toEqual([
      ['p5120', ['kept', 'kept']],
      ['p6002', ['kept', 'kept']],
      ['p0001', ['kept', 'removed']],
      ['p0002', ['kept', 'removed']],
      ['p0003', ['kept', 'removed']],
    ]);
    expect(m.counts).toEqual([6403, 2]);
    expect(m.removed).toEqual([6401]);
    expect(m.unlisted).toBe(6398);
    expect(m.hasUnknown).toBe(false);
  });

  it('settles values from one list against a later capped list by sort order', () => {
    const m = buildValuesMatrix(vals(['a', 'b'], 9), [vals(['a', 'c'], 5), vals(['a'], 3)]);
    const rows = byValue(m.rows);
    expect(rows.a.cells).toEqual(['kept', 'kept', 'kept']);
    // b sorts before stage 1's last listed value, so its absence is a removal.
    expect(rows.b.cells).toEqual(['kept', 'removed', 'removed']);
    // c sorts past stage 2's only listed value, so stage 2 may have kept it.
    expect(rows.c.cells).toEqual(['kept', 'kept', 'unknown']);
    expect(m.rows.map((r) => r.value)).toEqual(['a', 'c', 'b']);
    expect(m.unlisted).toBe(6);
  });

  it('compares against a capped list in code point order, like the server', () => {
    // Python sorts U+FFFD before U+1F600; UTF-16 units put the emoji first.
    const replacement = String.fromCodePoint(0xfffd);
    const emoji = String.fromCodePoint(0x1f600);
    expect(replacement < emoji).toBe(false);
    expect(compareCodePoints(replacement, emoji)).toBeLessThan(0);
    expect(compareCodePoints(`a${emoji}`, `a${emoji}b`)).toBeLessThan(0);
    const m = buildValuesMatrix(vals([replacement, emoji]), [vals([replacement], 2)]);
    expect(byValue(m.rows)[emoji].cells).toEqual(['kept', 'unknown']);
  });

  it('marks values past a shorter stage cap unknown', () => {
    const m = buildValuesMatrix(vals(['a', 'b', 'c']), [vals(['a'], 2)]);
    const rows = byValue(m.rows);
    expect(rows.a.cells).toEqual(['kept', 'kept']);
    expect(rows.c.cells).toEqual(['kept', 'unknown']);
    expect(rows.c.removedAt).toBeNull();
    expect(m.hasUnknown).toBe(true);
  });

  it('falls back to the stage lists when the unfiltered list is missing', () => {
    const m = buildValuesMatrix(null, [vals(['b', 'a']), vals(['a'])]);
    expect(m.rows.map((r) => [r.value, r.survives])).toEqual([
      ['a', 2],
      ['b', 1],
    ]);
    expect(m.counts).toEqual([null, 2, 1]);
    expect(m.removed).toEqual([null, 1]);
  });
});

describe('filterMatrixRows', () => {
  const { rows } = buildValuesMatrix(vals(['T0_R1', 't15_r1', 'X']), [vals(['T0_R1'])]);

  it('matches case-insensitively and ignores surrounding spaces', () => {
    expect(filterMatrixRows(rows, ' r1 ').map((r) => r.value)).toEqual(['T0_R1', 't15_r1']);
    expect(filterMatrixRows(rows, '')).toBe(rows);
  });
});

describe('matrixCellLabel', () => {
  const columns = ['All data', '+sample', '+protocol', '+group'];
  const { rows } = buildValuesMatrix(vals(['T15_R1']), [
    vals(['T15_R1']),
    vals([]),
    vals([]),
  ]);

  it('names the stage that removed the value on every removed cell', () => {
    expect(matrixCellLabel(rows[0], 0, columns)).toBe('T15_R1 in All data');
    expect(matrixCellLabel(rows[0], 1, columns)).toBe('T15_R1 kept after +sample');
    expect(matrixCellLabel(rows[0], 2, columns)).toBe('T15_R1 removed by +protocol');
    expect(matrixCellLabel(rows[0], 3, columns)).toBe('T15_R1 removed by +protocol');
  });
});

describe('matrixSummary', () => {
  it('pairs the unfiltered count with what the last stage leaves', () => {
    expect(matrixSummary([4, 3, 1])).toBe('4 values → 1 remains');
    expect(matrixSummary([1, 0])).toBe('1 value → 0 remain');
    expect(matrixSummary([null, 2, null])).toBe('? values → ? remain');
  });
});

describe('groupStageColor', () => {
  it("returns the group's color for its projected filter", () => {
    const groups = [group({})];
    const [projected] = groupsToFilters(groups);
    expect(groupStageColor(projected, groups)).toBe('#1f77b4');
  });

  it('returns null for ordinary filters and for merged groups', () => {
    const groups = [group({}), group({ id: 'g2', name: 'Group 2', color: '#ff7f0e' })];
    const [merged] = groupsToFilters(groups);
    expect(groupStageColor(merged, groups)).toBeNull();
    expect(groupStageColor(filterOn('dc1', 'sample'), groups)).toBeNull();
  });
});
