import { describe, expect, it } from 'vitest';

import type { StoredMetadata } from './api';
import { advancedVizSelectionColumn } from './selection';

const meta = (viz_kind: string, config: Record<string, unknown> = {}): StoredMetadata =>
  ({ index: 'c1', component_type: 'advanced_viz', viz_kind, config }) as unknown as StoredMetadata;

describe('advancedVizSelectionColumn for the protein kinds', () => {
  it('selects by default, on the model defaults', () => {
    expect(advancedVizSelectionColumn(meta('molecule_3d'))).toBe('position');
    expect(advancedVizSelectionColumn(meta('sequence_track'))).toBe('position');
    expect(advancedVizSelectionColumn(meta('msa'))).toBe('seq_id');
  });

  it('follows the bound columns', () => {
    expect(advancedVizSelectionColumn(meta('molecule_3d', { position_col: 'resnum' }))).toBe('resnum');
    expect(advancedVizSelectionColumn(meta('msa', { seq_id_col: 'hit' }))).toBe('hit');
  });

  it('honours an explicit opt-out, and keeps other kinds opt-in', () => {
    expect(advancedVizSelectionColumn(meta('msa', { selection_enabled: false }))).toBeUndefined();
    expect(advancedVizSelectionColumn(meta('scatter_xy', { label_col: 'sample' }))).toBeUndefined();
  });
});
