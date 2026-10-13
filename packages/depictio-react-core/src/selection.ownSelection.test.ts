import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from './api';
import { clearedSelectionFilters, genomePosFilterIndex, ownSelection } from './selection';

const f = (
  index: string,
  value: unknown,
  source?: InteractiveFilter['source'],
): InteractiveFilter => ({ index, value, source });

describe('ownSelection', () => {
  it('is empty when the tile has emitted nothing', () => {
    expect(ownSelection([], 'a')).toEqual({ filters: [], count: 0 });
  });

  it('counts the values of the tile own selection, whatever the source', () => {
    for (const source of [
      'scatter_selection',
      'table_selection',
      'map_selection',
      'image_selection',
    ] as const) {
      const own = ownSelection([f('a', ['x', 'y', 'z'], source)], 'a');
      expect(own.count).toBe(3);
      expect(own.filters).toHaveLength(1);
    }
  });

  it('ignores other tiles, cleared entries and plain interactive filters', () => {
    const own = ownSelection(
      [
        f('b', ['x'], 'scatter_selection'),
        f('a', [], 'table_selection'),
        f('a', null, 'scatter_selection'),
        f('a', ['x']),
      ],
      'a',
    );
    expect(own).toEqual({ filters: [], count: 0 });
  });

  it('leaves tree and axis selections to their own tiles', () => {
    const own = ownSelection(
      [f('a', ['t1'], 'tree_selection'), f('a', [1, 2], 'axis_selection')],
      'a',
    );
    expect(own.filters).toHaveLength(0);
  });

  it('takes both halves of a genome region but counts only the chromosomes', () => {
    const own = ownSelection(
      [f('a', ['chr1'], 'genome_selection'), f(genomePosFilterIndex('a'), [10, 20], 'genome_selection')],
      'a',
    );
    expect(own.filters).toHaveLength(2);
    expect(own.count).toBe(1);
  });
});

describe('clearedSelectionFilters', () => {
  it('keeps every key but empties the value', () => {
    const entry: InteractiveFilter = {
      index: 'a',
      value: ['x'],
      source: 'scatter_selection',
      column_name: 'sample',
    };
    expect(clearedSelectionFilters([entry])).toEqual([{ ...entry, value: [] }]);
  });
});
