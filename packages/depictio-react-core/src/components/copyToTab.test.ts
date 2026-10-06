import { describe, expect, it } from 'vitest';

import type { DashboardData, StoredMetadata } from '../api';
import { canCopyToTab, copyComponentToTab } from './copyToTab';

const card: StoredMetadata = {
  index: 'src-1',
  component_type: 'card',
  title: 'Samples',
  tag: 'ov-samples',
  section: 'Key figures',
  aggregation: 'count',
  column_name: 'sample',
  dict_kwargs: { x: 'a' },
  _id: 'mongo-id',
} as StoredMetadata;

const sourceLayout = [
  { i: 'box-src-1', x: 4, y: 2, w: 3, h: 2 },
  { i: 'box-other', x: 0, y: 0, w: 4, h: 2 },
];

function tab(over: Partial<DashboardData> = {}): DashboardData {
  return {
    dashboard_id: 'target',
    stored_metadata: [
      { index: 't-1', component_type: 'figure', tag: 'ov-samples-copy' },
      { index: 't-2', component_type: 'interactive', section: 'Filters only' },
    ] as StoredMetadata[],
    right_panel_layout_data: [
      { i: 'box-t-1', x: 0, y: 0, w: 12, h: 4 },
      { i: 'box-t-3', x: 0, y: 4, w: 6, h: 3 },
    ],
    ...over,
  };
}

const copy = (target: DashboardData, source: StoredMetadata = card, layout: unknown = sourceLayout) =>
  copyComponentToTab({ source, sourceLayoutData: layout, target, newId: 'new-1' });

describe('canCopyToTab', () => {
  it('offers the grid types and holds back filters and floating maps', () => {
    expect(canCopyToTab({ component_type: 'text' })).toBe(true);
    expect(canCopyToTab({ component_type: 'card' })).toBe(true);
    expect(canCopyToTab({ component_type: 'map', placement: 'grid' })).toBe(true);
    expect(canCopyToTab({ component_type: 'interactive' })).toBe(false);
    expect(canCopyToTab({ component_type: 'map', placement: 'floating' })).toBe(false);
    expect(canCopyToTab({ component_type: 'something-new' })).toBe(false);
  });
});

describe('copyComponentToTab', () => {
  it('gives the copy a new index and a free tag, and keeps every other field', () => {
    const { component } = copy(tab({ grid_sections: [{ name: 'Key figures' }] }));
    expect(component.index).toBe('new-1');
    // `ov-samples-copy` is taken on the target, so the next one is used.
    expect(component.tag).toBe('ov-samples-copy-2');
    expect(component).not.toHaveProperty('_id');
    const { index: _i, tag: _t, _id: _m, ...rest } = card as Record<string, unknown>;
    expect(component).toMatchObject(rest);
  });

  it('shares no nested object with the source, and leaves both documents alone', () => {
    const target = tab();
    const before = JSON.stringify(target);
    const { component } = copy(target);
    expect(component.dict_kwargs).toEqual(card.dict_kwargs);
    expect(component.dict_kwargs).not.toBe(card.dict_kwargs);
    expect(JSON.stringify(target)).toBe(before);
    expect(card.index).toBe('src-1');
  });

  it('keeps a section the target declares', () => {
    expect(copy(tab({ grid_sections: [{ name: 'Key figures' }] })).component.section).toBe(
      'Key figures',
    );
  });

  it('keeps a section the target only uses', () => {
    const target = tab();
    target.stored_metadata!.push({
      index: 't-4',
      component_type: 'text',
      section: 'Key figures',
    } as StoredMetadata);
    expect(copy(target).component.section).toBe('Key figures');
  });

  it('drops a section the target lacks, or has only in its filter panel', () => {
    expect(copy(tab()).component).not.toHaveProperty('section');
    const filtersOnly = { ...card, section: 'Filters only' } as StoredMetadata;
    expect(copy(tab(), filtersOnly).component).not.toHaveProperty('section');
  });

  it('places the copy under everything, with the source size and column', () => {
    const { dashboard } = copy(tab());
    const layout = dashboard.right_panel_layout_data as { i: string }[];
    expect(layout).toHaveLength(3);
    expect(layout[2]).toEqual({ i: 'box-new-1', x: 4, y: 7, w: 3, h: 2 });
    const metadata = dashboard.stored_metadata!;
    expect(metadata[metadata.length - 1].index).toBe('new-1');
  });

  it('falls back to a default size, at the top of an empty tab', () => {
    const { dashboard } = copy(tab({ right_panel_layout_data: [] }), card, []);
    expect(dashboard.right_panel_layout_data).toEqual([
      { i: 'box-new-1', x: 0, y: 0, w: 6, h: 4 },
    ]);
  });

  it('appends to each breakpoint of a breakpoint-keyed layout at its own bottom', () => {
    const { dashboard } = copy(
      tab({
        right_panel_layout_data: {
          lg: [{ i: 'box-t-1', x: 0, y: 0, w: 12, h: 4 }],
          sm: [{ i: 'box-t-1', x: 0, y: 0, w: 6, h: 9 }],
        },
      }),
    );
    const layout = dashboard.right_panel_layout_data as Record<string, { i: string; y: number }[]>;
    expect(layout.lg[1]).toMatchObject({ i: 'box-new-1', y: 4 });
    expect(layout.sm[1]).toMatchObject({ i: 'box-new-1', y: 9 });
  });

  it('leaves the tag alone when the source has none', () => {
    const { component } = copy(tab(), { ...card, tag: undefined } as StoredMetadata);
    expect(component.tag).toBeUndefined();
  });
});
