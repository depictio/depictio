import { describe, expect, it } from 'vitest';

import type { StoredMetadata } from './api';
import { advancedVizSelectionColumn } from './selection';

const meta = (viz_kind: string, config: Record<string, unknown> = {}): StoredMetadata =>
  ({ index: 'c1', component_type: 'advanced_viz', viz_kind, config }) as unknown as StoredMetadata;

/** The residue kinds that pick on the position column. */
const POSITION_KINDS = [
  'molecule_3d',
  'sequence_track',
  'hmm_logo',
  'secondary_structure',
  'pae_matrix',
  'ramachandran',
];

describe('advancedVizSelectionColumn for the protein kinds', () => {
  it('selects by default, on the model defaults', () => {
    for (const kind of POSITION_KINDS) {
      expect(advancedVizSelectionColumn(meta(kind)), kind).toBe('position');
    }
    expect(advancedVizSelectionColumn(meta('msa'))).toBe('seq_id');
    expect(advancedVizSelectionColumn(meta('domain_architecture'))).toBe('label');
  });

  it('follows the bound columns', () => {
    for (const kind of POSITION_KINDS) {
      expect(advancedVizSelectionColumn(meta(kind, { position_col: 'resnum' })), kind).toBe('resnum');
    }
    expect(advancedVizSelectionColumn(meta('msa', { seq_id_col: 'hit' }))).toBe('hit');
    expect(advancedVizSelectionColumn(meta('domain_architecture', { label_col: 'family' }))).toBe(
      'family',
    );
    expect(
      advancedVizSelectionColumn(
        meta('domain_architecture', { label_col: 'family', selection_column: 'domain_id' }),
      ),
    ).toBe('domain_id');
  });

  it('honours an explicit opt-out, and keeps other kinds opt-in', () => {
    expect(advancedVizSelectionColumn(meta('msa', { selection_enabled: false }))).toBeUndefined();
    for (const kind of [...POSITION_KINDS, 'domain_architecture']) {
      expect(
        advancedVizSelectionColumn(meta(kind, { selection_enabled: false })),
        kind,
      ).toBeUndefined();
    }
    expect(advancedVizSelectionColumn(meta('scatter_xy', { label_col: 'sample' }))).toBeUndefined();
  });
});
