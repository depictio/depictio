import { describe, expect, it } from 'vitest';

import { extraStatRows } from './SecondaryMetrics';

const rows = [
  { name: 'median', value: 4 },
  { name: 'max', value: 9 },
  { name: '__breakdown__', value: {} },
  { name: 'box_plot_stats', value: {} },
];

describe('extraStatRows: a card lists its aggregations under any strip', () => {
  it('lists the scalar aggregations under a breakdown, QC or box strip', () => {
    for (const layout of ['top_n', 'donut', 'threshold', 'histogram', 'box_plot'] as const) {
      expect(extraStatRows(rows as never, layout, false).map((r) => r.name)).toEqual([
        'median',
        'max',
      ]);
    }
  });

  it('adds nothing where the strip already is the stat list', () => {
    for (const layout of ['vertical', 'compact', 'grid'] as const) {
      expect(extraStatRows(rows as never, layout, false)).toEqual([]);
    }
  });

  it('keeps a headline card to its one strip', () => {
    expect(extraStatRows(rows as never, 'top_n', true)).toEqual([]);
  });

  it('does not list twice when a meter falls back to the stat list', () => {
    expect(extraStatRows(rows as never, 'gauge', false, 3, null)).toEqual([]);
    expect(extraStatRows(rows as never, 'gauge', false, 3, 10)).toHaveLength(2);
  });
});
