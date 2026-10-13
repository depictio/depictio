import { describe, expect, it } from 'vitest';
import type { Layout } from 'react-grid-layout';

import type { InteractiveFilter, StoredMetadata } from '../api';
import {
  applyRecordPanels,
  findSidePanels,
  linkedSelectionActive,
  panelExpanded,
  reconcileOverrides,
  recordPanelLinks,
} from './recordPanelLayout';

const item = (i: string, x: number, w: number, y = 0, h = 6): Layout => ({ i, x, y, w, h });

const card = (index: string, linked?: string): StoredMetadata =>
  ({
    index,
    component_type: 'advanced_viz',
    viz_kind: 'record_card',
    config: { viz_kind: 'record_card', id_col: 'sample', linked_component: linked },
  }) as StoredMetadata;

describe('recordPanelLinks', () => {
  it('maps each linked record card to its source and skips the rest', () => {
    const links = recordPanelLinks([
      card('c1', 't1'),
      card('c2'),
      card('c3', 'c3'),
      { index: 't1', component_type: 'table' } as StoredMetadata,
    ]);
    expect([...links]).toEqual([['c1', 't1']]);
  });
});

describe('findSidePanels', () => {
  const links = new Map([['card', 'table']]);

  it('pairs a card touching its source on either side of the same row', () => {
    expect(findSidePanels([item('table', 0, 5), item('card', 5, 3)], links)).toEqual([
      { cardId: 'card', sourceId: 'table', side: 'right' },
    ]);
    expect(findSidePanels([item('card', 0, 3), item('table', 3, 5)], links)).toEqual([
      { cardId: 'card', sourceId: 'table', side: 'left' },
    ]);
  });

  it('ignores a card on another row or with a gap between them', () => {
    expect(findSidePanels([item('table', 0, 5), item('card', 5, 3, 6)], links)).toEqual([]);
    expect(findSidePanels([item('table', 0, 4), item('card', 5, 3)], links)).toEqual([]);
    expect(findSidePanels([item('card', 5, 3)], links)).toEqual([]);
  });
});

describe('applyRecordPanels', () => {
  const other = item('other', 0, 8, 6);

  it('drops a folded right-hand card and gives its source the whole span', () => {
    const layout = [item('table', 0, 5), item('card', 5, 3), other];
    const panels = findSidePanels(layout, new Map([['card', 'table']]));
    expect(applyRecordPanels(layout, panels, () => true)).toEqual([item('table', 0, 8), other]);
  });

  it('drops a folded left-hand card and moves its source to the card edge', () => {
    const layout = [item('card', 0, 3), item('table', 3, 5)];
    const panels = findSidePanels(layout, new Map([['card', 'table']]));
    expect(applyRecordPanels(layout, panels, () => true)).toEqual([item('table', 0, 8)]);
  });

  it('leaves an expanded pair exactly as laid out', () => {
    const layout = [item('table', 0, 5), item('card', 5, 3)];
    const panels = findSidePanels(layout, new Map([['card', 'table']]));
    expect(applyRecordPanels(layout, panels, () => false)).toEqual(layout);
  });

  it('never mutates the layout it was given', () => {
    const layout = [item('table', 0, 5), item('card', 5, 3)];
    const snapshot = JSON.parse(JSON.stringify(layout));
    applyRecordPanels(layout, findSidePanels(layout, new Map([['card', 'table']])), () => true);
    expect(layout).toEqual(snapshot);
  });
});

describe('selection state', () => {
  const pick = (index: string, value: unknown[], source = 'table_selection'): InteractiveFilter =>
    ({ index, value, source }) as InteractiveFilter;

  it('counts only a non-empty selection from the linked tile', () => {
    expect(linkedSelectionActive([pick('table', ['S1'])], 'table')).toBe(true);
    expect(linkedSelectionActive([pick('table', [])], 'table')).toBe(false);
    expect(linkedSelectionActive([pick('other', ['S1'])], 'table')).toBe(false);
    expect(linkedSelectionActive([pick('table', ['S1'], 'interactive')], 'table')).toBe(false);
    expect(linkedSelectionActive(undefined, 'table')).toBe(false);
  });

  it('follows the selection unless the reader toggled', () => {
    expect(panelExpanded(false, undefined)).toBe(false);
    expect(panelExpanded(true, undefined)).toBe(true);
    expect(panelExpanded(true, false)).toBe(false);
    expect(panelExpanded(false, true)).toBe(true);
  });

  it('drops a toggle once its source gains or loses a selection', () => {
    const overrides = { a: false, b: true };
    expect(reconcileOverrides(overrides, { a: true, b: false }, { a: true, b: false })).toBe(
      overrides,
    );
    expect(reconcileOverrides(overrides, { a: true, b: false }, { a: false, b: false })).toEqual({
      b: true,
    });
    expect(reconcileOverrides(overrides, { a: true, b: false }, { a: true, b: true })).toEqual({
      a: false,
    });
  });
});
