import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../../api';
import {
  applyConstraintUpdate,
  axisFilterIndex,
  axisRangeFilter,
  brushFilterUpdates,
  filtersExcludingOwnBrushes,
  parseConstraintUpdate,
  sameBrushes,
  type AxisBrushes,
} from './brushFilters';

const columns = ['reads', 'dup_rate', 'gc'];
const identity = (_column: string, value: number): number => value;

describe('parseConstraintUpdate', () => {
  it('reads a brush plotly wrapped per trace', () => {
    const parsed = parseConstraintUpdate({ 'dimensions[1].constraintrange': [[0.2, 0.8]] });
    expect(parsed.get(1)).toEqual([0.2, 0.8]);
  });

  it('reads a bare pair as well', () => {
    expect(parseConstraintUpdate({ 'dimensions[0].constraintrange': [1, 4] }).get(0)).toEqual([
      1, 4,
    ]);
  });

  it('collapses two windows on one axis to the span covering both', () => {
    const parsed = parseConstraintUpdate({
      'dimensions[2].constraintrange': [
        [
          [1, 2],
          [5, 6],
        ],
      ],
    });
    expect(parsed.get(2)).toEqual([1, 6]);
  });

  it('reads a cleared brush and a zero-width one as no brush', () => {
    expect(parseConstraintUpdate({ 'dimensions[0].constraintrange': [null] }).get(0)).toBeNull();
    expect(parseConstraintUpdate({ 'dimensions[0].constraintrange': [[3, 3]] }).get(0)).toBeNull();
  });

  it('ignores every other restyle key', () => {
    expect(parseConstraintUpdate({ 'line.color': ['red'] }).size).toBe(0);
    expect(parseConstraintUpdate(undefined).size).toBe(0);
  });
});

describe('applyConstraintUpdate', () => {
  it('names the brushed column and inverts the axis scaling', () => {
    const next = applyConstraintUpdate(
      {},
      parseConstraintUpdate({ 'dimensions[0].constraintrange': [[0, 0.5]] }),
      columns,
      // A minmax axis over [0, 1000].
      (_column, value) => value * 1000,
    );
    expect(next).toEqual({ reads: [0, 500] });
  });

  it('keeps the other axes brushed and clears the one that was released', () => {
    const current: AxisBrushes = { reads: [0, 500], gc: [40, 60] };
    const next = applyConstraintUpdate(
      current,
      parseConstraintUpdate({ 'dimensions[2].constraintrange': null }),
      columns,
      identity,
    );
    expect(next).toEqual({ reads: [0, 500] });
    expect(current).toEqual({ reads: [0, 500], gc: [40, 60] });
  });

  it('orders an inverted range and drops a brush on a column that is no longer an axis', () => {
    const next = applyConstraintUpdate(
      { retired: [1, 2] },
      parseConstraintUpdate({ 'dimensions[1].constraintrange': [[0.9, 0.1]] }),
      columns,
      identity,
    );
    expect(next).toEqual({ dup_rate: [0.1, 0.9] });
  });
});

describe('sameBrushes', () => {
  it('compares by column and by bounds', () => {
    expect(sameBrushes({ gc: [1, 2] }, { gc: [1, 2] })).toBe(true);
    expect(sameBrushes({ gc: [1, 2] }, { gc: [1, 3] })).toBe(false);
    expect(sameBrushes({ gc: [1, 2] }, { reads: [1, 2] })).toBe(false);
    expect(sameBrushes({}, {})).toBe(true);
    expect(sameBrushes({ gc: [1, 2] }, {})).toBe(false);
  });
});

describe('brushFilterUpdates', () => {
  const base = { index: 'tile-1', dcId: 'dc-1' };

  it('emits a RangeSlider filter per changed axis, keyed by column', () => {
    const updates = brushFilterUpdates({}, { reads: [0, 500] }, base);
    expect(updates).toEqual([
      {
        index: 'tile-1::reads',
        value: [0, 500],
        column_name: 'reads',
        interactive_component_type: 'RangeSlider',
        source: 'axis_selection',
        metadata: {
          dc_id: 'dc-1',
          column_name: 'reads',
          interactive_component_type: 'RangeSlider',
        },
      },
    ]);
  });

  it('tags the entry as a selection, so a clear-selections pass reaches it', () => {
    const [update] = brushFilterUpdates({}, { reads: [0, 500] }, base);
    expect(update.source).toBe('axis_selection');
    // Cleared entries carry it too: `mergeFiltersBySource` drops the entry
    // for a `(index, source)` pair, so a clear that lost the source would
    // leave the brush filtering the dashboard.
    const [cleared] = brushFilterUpdates({ reads: [0, 500] }, {}, base);
    expect(cleared.source).toBe('axis_selection');
  });

  it('says nothing about the axes that did not move', () => {
    const previous: AxisBrushes = { reads: [0, 500], gc: [40, 60] };
    const next: AxisBrushes = { reads: [0, 500], gc: [45, 60] };
    expect(brushFilterUpdates(previous, next, base).map((f) => f.column_name)).toEqual(['gc']);
  });

  it('clears a released axis with an empty value', () => {
    const updates = brushFilterUpdates({ gc: [40, 60] }, {}, base);
    expect(updates).toHaveLength(1);
    expect(updates[0].index).toBe(axisFilterIndex('tile-1', 'gc'));
    expect(updates[0].value).toEqual([]);
  });

  it('carries the collection, since the viewer cannot look a suffixed index up', () => {
    expect(axisRangeFilter(base, 'gc', [1, 2]).metadata?.dc_id).toBe('dc-1');
  });
});

describe('filtersExcludingOwnBrushes', () => {
  it('drops this tile own entries and keeps everyone else', () => {
    const filters: InteractiveFilter[] = [
      { index: 'tile-1::reads', value: [0, 500], column_name: 'reads' },
      { index: 'tile-1', value: ['S1'], source: 'scatter_selection' },
      { index: 'tile-2::reads', value: [1, 2], column_name: 'reads' },
      { index: 'sidebar-slider', value: [1, 9], column_name: 'gc' },
    ];
    expect(filtersExcludingOwnBrushes(filters, 'tile-1').map((f) => f.index)).toEqual([
      'tile-2::reads',
      'sidebar-slider',
    ]);
  });
});
