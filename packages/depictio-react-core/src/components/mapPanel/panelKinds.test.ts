import { describe, expect, it } from 'vitest';

import type { FloatingComponent, InteractiveFilter, StoredMetadata } from '../../api';
import { residueRangeFilters } from '../../selection';
import {
  FLOATING_VIZ_KINDS,
  PANEL_KINDS,
  floatingPanelKindOf,
  isFloatingComponent,
  partitionFloating,
} from './panelKinds';
import { clearSelectionFilters, selectionCount } from './panelSelection';

const meta = (m: Partial<StoredMetadata> & { index: string; component_type: string }) =>
  m as StoredMetadata;

const floating = (m: StoredMetadata, tab = 'tab-a'): FloatingComponent => ({
  dashboard_id: tab,
  metadata: m,
});

describe('floatingPanelKindOf', () => {
  it('sends a floating map to the map panel', () => {
    expect(floatingPanelKindOf({ component_type: 'map', placement: 'floating' })).toBe('map');
  });

  it('sends a floating molecule_3d to the structure panel', () => {
    expect(
      floatingPanelKindOf({
        component_type: 'advanced_viz',
        placement: 'floating',
        viz_kind: 'molecule_3d',
      }),
    ).toBe('structure');
  });

  it('leaves a grid tile on the grid whatever it is', () => {
    expect(floatingPanelKindOf({ component_type: 'map', placement: 'grid' })).toBeNull();
    expect(floatingPanelKindOf({ component_type: 'map' })).toBeNull();
    expect(
      floatingPanelKindOf({
        component_type: 'advanced_viz',
        placement: 'grid',
        viz_kind: 'molecule_3d',
      }),
    ).toBeNull();
  });

  it('keeps an advanced viz of another kind on the grid, even marked floating', () => {
    // The server refuses to serve it as floating, so the grid has to keep it.
    expect(
      floatingPanelKindOf({
        component_type: 'advanced_viz',
        placement: 'floating',
        viz_kind: 'volcano',
      }),
    ).toBeNull();
    expect(
      floatingPanelKindOf({ component_type: 'advanced_viz', placement: 'floating' }),
    ).toBeNull();
  });

  it('knows no other floating type', () => {
    expect(floatingPanelKindOf({ component_type: 'figure', placement: 'floating' })).toBeNull();
    // An interactive control's placements are its own ('left' or 'top').
    expect(floatingPanelKindOf({ component_type: 'interactive', placement: 'top' })).toBeNull();
  });

  it('is what isFloatingComponent reports', () => {
    expect(isFloatingComponent({ component_type: 'map', placement: 'floating' })).toBe(true);
    expect(isFloatingComponent({ component_type: 'table' })).toBe(false);
  });

  it('allows exactly the kinds the model allows', () => {
    // depictio/models/components/constants.py: FLOATING_ADVANCED_VIZ_KINDS
    expect([...FLOATING_VIZ_KINDS]).toEqual(['molecule_3d']);
  });
});

describe('partitionFloating', () => {
  it('splits the family by panel and keeps tab order within each', () => {
    const map1 = floating(meta({ index: 'm1', component_type: 'map', placement: 'floating' }), 'a');
    const fold = floating(
      meta({
        index: 'f1',
        component_type: 'advanced_viz',
        placement: 'floating',
        viz_kind: 'molecule_3d',
      }),
      'a',
    );
    const map2 = floating(meta({ index: 'm2', component_type: 'map', placement: 'floating' }), 'b');
    const out = partitionFloating([map1, fold, map2]);
    expect(out.map.map((c) => c.metadata.index)).toEqual(['m1', 'm2']);
    expect(out.structure.map((c) => c.metadata.index)).toEqual(['f1']);
  });

  it('drops what no panel can hold rather than guessing one', () => {
    const odd = floating(
      meta({
        index: 'v1',
        component_type: 'advanced_viz',
        placement: 'floating',
        viz_kind: 'volcano',
      }),
    );
    expect(partitionFloating([odd])).toEqual({ map: [], structure: [] });
  });

  it('is empty for an empty family', () => {
    expect(partitionFloating([])).toEqual({ map: [], structure: [] });
  });
});

describe('PANEL_KINDS', () => {
  it('keeps the map panel under the key it has always used', () => {
    expect(PANEL_KINDS.map.storagePrefix).toBe('depictio:map-panel:');
  });

  it('gives each kind its own storage entry, so both panels coexist', () => {
    expect(PANEL_KINDS.structure.storagePrefix).not.toBe(PANEL_KINDS.map.storagePrefix);
    expect(PANEL_KINDS.structure.storagePrefix).toBe('depictio:structure-panel:');
  });

  it('starts the two floating cards in different corners', () => {
    expect(PANEL_KINDS.map.anchor.bottom).toBeDefined();
    expect(PANEL_KINDS.structure.anchor.top).toBeDefined();
    expect(PANEL_KINDS.structure.anchor.bottom).toBeUndefined();
  });

  it('keeps the map card at its original compact size', () => {
    expect(PANEL_KINDS.map.compact).toEqual({ width: 360, height: 280 });
  });
});

describe('panel selection', () => {
  const pick = (index: string, entity: string | null = 'P1'): InteractiveFilter[] =>
    residueRangeFilters(index, {
      entityColumn: entity ? 'entity' : null,
      positionColumn: 'position',
      entity,
      start: 12,
      end: 20,
      dcId: 'dc-1',
    });

  it('counts a map by the values it filters on', () => {
    const filters: InteractiveFilter[] = [
      { index: 'm1', value: ['a', 'b', 'c'], source: 'map_selection' },
      { index: 'other', value: ['x'], source: 'map_selection' },
    ];
    expect(selectionCount('map', filters, 'm1')).toBe(3);
    expect(selectionCount('map', filters, 'm2')).toBe(0);
  });

  it('counts a residue pick as one selection, entity half or not', () => {
    expect(selectionCount('structure', pick('f1'), 'f1')).toBe(1);
    expect(selectionCount('structure', pick('f1', null), 'f1')).toBe(1);
    expect(selectionCount('structure', pick('f1'), 'f2')).toBe(0);
    expect(selectionCount('structure', [], 'f1')).toBe(0);
  });

  it('does not read a residue pick as a map selection', () => {
    expect(selectionCount('map', pick('f1'), 'f1')).toBe(0);
  });

  it('clears a map with one empty map_selection entry', () => {
    const filters: InteractiveFilter[] = [
      { index: 'm1', value: ['a'], source: 'map_selection' },
    ];
    expect(clearSelectionFilters('map', filters, 'm1')).toEqual([
      { index: 'm1', value: [], source: 'map_selection' },
    ]);
  });

  it('clears nothing when there is nothing selected', () => {
    expect(clearSelectionFilters('map', [], 'm1')).toEqual([]);
    expect(clearSelectionFilters('structure', [], 'f1')).toEqual([]);
  });

  it('clears both halves of a residue pick', () => {
    const cleared = clearSelectionFilters('structure', pick('f1'), 'f1');
    expect(cleared.map((f) => f.index).sort()).toEqual(['f1', 'f1::res']);
    expect(cleared.every((f) => Array.isArray(f.value) && f.value.length === 0)).toBe(true);
    expect(cleared.every((f) => f.source === 'residue_selection')).toBe(true);
  });
});
