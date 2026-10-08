/**
 * Which dashboard components a record card can be linked to. Run like
 * advancedVizEdit.test.ts (the viewer package has no vitest of its own).
 */
import { describe, expect, it } from 'vitest';
import type { StoredMetadata } from 'depictio-react-core';
import { findEmitter, selectionEmitters } from '../../src/builder/advanced_viz/recordCardLink';

const meta = (m: Partial<StoredMetadata> & { index: string; component_type: string }) =>
  m as StoredMetadata;

const DASHBOARD: StoredMetadata[] = [
  meta({ index: 'card-self', component_type: 'advanced_viz', viz_kind: 'record_card', config: {} }),
  meta({
    index: 'tbl-uuid',
    component_type: 'table',
    title: 'Cross-tool calls per gene',
    row_selection_enabled: true,
    row_selection_column: 'gene_id',
  }),
  meta({ index: 'tbl-off', component_type: 'table', row_selection_enabled: false }),
  meta({
    index: 'fig-1',
    component_type: 'figure',
    visu_type: 'scatter',
    selection_enabled: true,
    selection_column: 'gene_name',
  }),
  meta({ index: 'fig-bar', component_type: 'figure', visu_type: 'bar', selection_enabled: true }),
  meta({
    index: 'rs-sp-av-pca',
    tag: 'rs-sp-av-pca',
    component_type: 'advanced_viz',
    viz_kind: 'embedding',
    config: { selection_enabled: true, sample_id_col: 'sample_id' },
  }),
  meta({
    index: 'manhattan-unnamed',
    component_type: 'advanced_viz',
    viz_kind: 'manhattan',
    config: { selection_enabled: true },
  }),
  meta({
    index: 'upset',
    component_type: 'advanced_viz',
    viz_kind: 'upset_plot',
    config: { selection_enabled: true },
  }),
  meta({ index: 'map-1', component_type: 'map', selection_enabled: true }),
];

describe('selectionEmitters', () => {
  const emitters = selectionEmitters(DASHBOARD, 'card-self');

  it('lists only components that emit a source the card honours, minus itself', () => {
    expect(emitters.map((e) => [e.index, e.source, e.column])).toEqual([
      ['tbl-uuid', 'table_selection', 'gene_id'],
      ['fig-1', 'scatter_selection', 'gene_name'],
      ['rs-sp-av-pca', 'scatter_selection', 'sample_id'],
    ]);
  });

  it('labels by title, falling back to tag then index', () => {
    expect(emitters.map((e) => e.label)).toEqual([
      'Cross-tool calls per gene',
      'fig-1',
      'rs-sp-av-pca',
    ]);
  });
});

describe('findEmitter', () => {
  const emitters = selectionEmitters(DASHBOARD, 'card-self');

  it('matches a stored tag or a resolved index', () => {
    expect(findEmitter(emitters, 'rs-sp-av-pca')?.index).toBe('rs-sp-av-pca');
    expect(findEmitter(emitters, 'tbl-uuid')?.index).toBe('tbl-uuid');
  });

  it('returns undefined for an unset or unknown link', () => {
    expect(findEmitter(emitters, null)).toBeUndefined();
    expect(findEmitter(emitters, 'gone')).toBeUndefined();
  });
});
