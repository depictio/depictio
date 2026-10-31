import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from './api';
import { markSelectedPoints, standingSelectionValues } from './standingSelection';

const pick = (index: string, source: string, value: string[], dc = 'dc1', column = 'sample'): InteractiveFilter =>
  ({ index, source, value, column_name: column, metadata: { dc_id: dc } }) as unknown as InteractiveFilter;

describe('standingSelectionValues', () => {
  const own = { index: 'fig', dcId: 'dc1', column: 'sample' };

  it('reads the pick of the tile itself', () => {
    expect(standingSelectionValues([pick('fig', 'scatter_selection', ['S1'])], own)).toEqual(new Set(['S1']));
  });

  it('follows a pick on the same column of the same collection from another tile', () => {
    expect(standingSelectionValues([pick('tbl', 'table_selection', ['S2'])], own)).toEqual(new Set(['S2']));
  });

  it('ignores sidebar filters, other columns, other collections and cleared picks', () => {
    const filters = [
      pick('side', '', ['S3']),
      pick('tbl', 'table_selection', ['G1'], 'dc1', 'gene'),
      pick('other', 'table_selection', ['S4'], 'dc2'),
      pick('fig', 'scatter_selection', []),
    ];
    expect(standingSelectionValues(filters, own)).toBeNull();
  });
});

describe('markSelectedPoints', () => {
  it('selects the matching points of every trace that carries ids', () => {
    const data = [
      { customdata: [['S1'], ['S2']] },
      { customdata: [['S2'], ['S1'], ['S3']] },
      { x: [0, 1] },
    ];
    const out = markSelectedPoints(data, new Set(['S1']), 0);
    expect(out[0]).toMatchObject({ selectedpoints: [0] });
    expect(out[1]).toMatchObject({ selectedpoints: [1] });
    expect(out[2]).toBe(data[2]);
  });
});
