import { describe, expect, it } from 'vitest';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import type { ColorByState, SelectionGroup } from '../../selectionGroups';
import {
  VALUE_LIST_LIMIT,
  colorBySegmentValue,
  groupPreview,
  groupingActiveStep,
  selectionCapableCount,
  selectionCapableSummary,
  selectionKey,
  selectionPreview,
  truncateValue,
  valueList,
} from './groupingGuide';

const meta = (m: Partial<StoredMetadata> & { index: string; component_type: string }) =>
  m as StoredMetadata;

const scatter = (index: string, enabled = true) =>
  meta({ index, component_type: 'figure', visu_type: 'scatter', selection_enabled: enabled });

describe('selectionCapableCount', () => {
  it('counts only the components a group can be made from', () => {
    const components = [
      scatter('fig-1'),
      // Selection off: the tile emits nothing to save.
      scatter('fig-2', false),
      // Bar charts aggregate; no per-row identity to capture.
      meta({ index: 'fig-3', component_type: 'figure', visu_type: 'bar', selection_enabled: true }),
      meta({ index: 'tab-1', component_type: 'table', row_selection_enabled: true }),
      meta({ index: 'tab-2', component_type: 'table' }),
      meta({ index: 'card-1', component_type: 'card' }),
    ];
    expect(selectionCapableCount(components)).toBe(2);
  });

  it('is zero for a dashboard of passive tiles', () => {
    expect(selectionCapableCount([meta({ index: 'c', component_type: 'card' })])).toBe(0);
  });
});

describe('groupingActiveStep', () => {
  it('stays on step 1 when nothing here can be selected', () => {
    expect(groupingActiveStep(0, false)).toBe(0);
    // Not reachable in practice, but the block must hold even if it were.
    expect(groupingActiveStep(0, true)).toBe(0);
  });

  it('moves to step 2 once the dashboard has selectable tiles', () => {
    expect(groupingActiveStep(3, false)).toBe(1);
  });

  it('moves to step 3 as soon as a selection is live', () => {
    expect(groupingActiveStep(3, true)).toBe(2);
  });
});

describe('selectionCapableSummary', () => {
  it('says why the flow is blocked when no tile can emit a selection', () => {
    expect(selectionCapableSummary(0)).toMatch(/No tile/);
  });

  it('agrees in number with the count it quotes', () => {
    expect(selectionCapableSummary(1)).toMatch(/^1 tile here can\./);
    expect(selectionCapableSummary(4)).toMatch(/^4 tiles here can\./);
  });
});

describe('selectionKey', () => {
  it('keys on the (index, source) pair the dashboard holds selections by', () => {
    expect(selectionKey({ index: 'fig-1', value: [], source: 'scatter_selection' })).toBe(
      'fig-1:scatter_selection',
    );
  });
});

describe('truncateValue', () => {
  it('leaves short values alone', () => {
    expect(truncateValue('SRR123')).toBe('SRR123');
  });

  it('clips long ids to the display cap, ellipsis included', () => {
    const clipped = truncateValue('a'.repeat(40), 10);
    expect(clipped).toBe(`${'a'.repeat(9)}…`);
    expect(clipped).toHaveLength(10);
  });
});

describe('selectionPreview', () => {
  const components = [
    meta({ index: 'fig-1', component_type: 'figure', title: 'PCA of samples' }),
  ];
  const filter = (value: unknown[], extra: Partial<InteractiveFilter> = {}): InteractiveFilter => ({
    index: 'fig-1',
    source: 'scatter_selection',
    column_name: 'sample_id',
    value,
    ...extra,
  });

  it('reports the count, the column and the source tile', () => {
    const preview = selectionPreview(filter(['a', 'b', 'c']), components);
    expect(preview).toMatchObject({
      count: 3,
      columnName: 'sample_id',
      sourceLabel: 'PCA of samples',
      values: { shown: ['a', 'b', 'c'], distinct: 3, total: 3, hidden: 0 },
    });
  });

  it('caps the rendered list and counts the rest', () => {
    const values = Array.from({ length: VALUE_LIST_LIMIT + 5 }, (_, i) => `s${i}`);
    const preview = selectionPreview(filter(values), components);
    expect(preview?.values.shown).toHaveLength(VALUE_LIST_LIMIT);
    expect(preview?.values.shown[0]).toBe('s0');
    expect(preview?.values.hidden).toBe(5);
  });

  it('stringifies the values and keeps them whole', () => {
    // Whole, not truncated: a long id differs from its neighbour in the tail,
    // which is exactly what a clip removes. The list box wraps instead.
    const preview = selectionPreview(filter([1, 'x'.repeat(40)]), components);
    expect(preview?.values.shown[0]).toBe('1');
    expect(preview?.values.shown[1]).toHaveLength(40);
  });

  it('drops the source label when it would only repeat the column', () => {
    // No title on the component, so `filterDisplayLabel` falls back to the
    // column name — "on sample_id from sample_id" helps nobody.
    const preview = selectionPreview(filter(['a']), [
      meta({ index: 'fig-1', component_type: 'figure' }),
    ]);
    expect(preview?.sourceLabel).toBeNull();
  });

  it('resolves the column the same way the save does', () => {
    const preview = selectionPreview(
      filter(['a'], { column_name: undefined, metadata: { selection_column: 'cell_id' } }),
      components,
    );
    expect(preview?.columnName).toBe('cell_id');
  });

  it('returns null for the selections a group cannot be made from', () => {
    expect(selectionPreview(filter([]), components)).toBeNull();
    expect(
      selectionPreview(filter(['a'], { column_name: undefined, metadata: {} }), components),
    ).toBeNull();
    expect(selectionPreview({ index: 'fig-1', value: 'not-an-array' }, components)).toBeNull();
  });
});

describe('groupPreview', () => {
  const group = (patch: Partial<SelectionGroup> = {}): SelectionGroup => ({
    id: 'g1',
    name: 'Soil',
    color: '#E24A33',
    columnName: 'sample_id',
    values: ['s1', 's2', 's3'],
    createdAt: 0,
    filterActive: false,
    ...patch,
  });

  it('says what the group is made of', () => {
    const p = groupPreview(group(), []);
    expect(p.count).toBe(3);
    expect(p.columnName).toBe('sample_id');
    expect(p.values.shown).toEqual(['s1', 's2', 's3']);
    expect(p.values.hidden).toBe(0);
  });

  it('names the dataset the selection was drawn on', () => {
    const components = [
      { dc_id: 'dc1', data_collection_tag: 'samples' } as unknown as StoredMetadata,
    ];
    expect(groupPreview(group({ dcId: 'dc1' }), components).datasetLabel).toBe('samples');
  });

  it('leaves the dataset unnamed rather than printing an id', () => {
    // A bare ObjectId says nothing a reader can act on, and the column name
    // already carries the useful half on a single-dataset dashboard.
    expect(groupPreview(group({ dcId: 'dc-unknown' }), []).datasetLabel).toBeNull();
    expect(groupPreview(group(), []).datasetLabel).toBeNull();
  });

  it('caps a long group and counts the rest', () => {
    const values = Array.from({ length: VALUE_LIST_LIMIT + 30 }, (_, i) => `s${i}`);
    const p = groupPreview(group({ values }), []);
    expect(p.values.shown).toHaveLength(VALUE_LIST_LIMIT);
    expect(p.values.hidden).toBe(30);
    expect(p.count).toBe(VALUE_LIST_LIMIT + 30);
  });

  it('keeps a long value whole, as the pending form does', () => {
    const p = groupPreview(group({ values: ['x'.repeat(60)] }), []);
    expect(p.values.shown[0]).toBe('x'.repeat(60));
  });

  it('survives a group with no values', () => {
    const p = groupPreview(group({ values: [] }), []);
    expect(p.count).toBe(0);
    expect(p.values.shown).toEqual([]);
    expect(p.values.distinct).toBe(0);
  });
});

describe('colorBySegmentValue', () => {
  const none: ColorByState = { kind: 'none' };

  it('follows the active override', () => {
    expect(colorBySegmentValue(none, false)).toBe('none');
    expect(colorBySegmentValue({ kind: 'groups' }, false)).toBe('groups');
    expect(colorBySegmentValue({ kind: 'column', columnName: 'species' }, false)).toBe('column');
  });

  it('holds the column segment while no column has been named yet', () => {
    // Picking "A column" leaves the override off until a column is chosen.
    // Reading `colorBy.kind` alone snapped the control back to "Nothing" on
    // click, which is indistinguishable from the segment not working.
    expect(colorBySegmentValue(none, true)).toBe('column');
  });

  it('lets a real override win over a stale pending flag', () => {
    expect(colorBySegmentValue({ kind: 'groups' }, true)).toBe('groups');
    expect(colorBySegmentValue({ kind: 'column', columnName: 'g' }, true)).toBe('column');
  });
});

describe('valueList', () => {
  it('collapses the duplicates a lasso produces', () => {
    // Several points of one sample is the normal case, not an edge case: a
    // lasso over a scatter of per-read rows catches the same sample dozens of
    // times, and listing it dozens of times is what made the preview useless.
    const v = valueList(['s1', 's2', 's1', 's1', 's3']);
    expect(v.shown).toEqual(['s1', 's2', 's3']);
    expect(v.distinct).toBe(3);
    expect(v.total).toBe(5);
    expect(v.hidden).toBe(0);
  });

  it('keeps first-seen order rather than sorting', () => {
    expect(valueList(['zeta', 'alpha', 'mu']).shown).toEqual(['zeta', 'alpha', 'mu']);
  });

  it('caps what it renders and says how many it left', () => {
    const v = valueList(Array.from({ length: 30 }, (_, i) => `s${i}`), 10);
    expect(v.shown).toHaveLength(10);
    expect(v.distinct).toBe(30);
    expect(v.hidden).toBe(20);
  });

  it('counts an empty selection as nothing rather than failing', () => {
    expect(valueList([])).toEqual({ shown: [], distinct: 0, total: 0, hidden: 0 });
  });
});
