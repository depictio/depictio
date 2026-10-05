/**
 * The kind picker's badges, tooltips and the dashboard context it sends to the
 * suggestion endpoint. Run like advancedVizEdit.test.ts (the viewer package has
 * no vitest of its own).
 */
import { describe, expect, it } from 'vitest';
import type {
  AdvancedVizKindDescriptor,
  StoredMetadata,
  VizKindSuggestion,
} from 'depictio-react-core';
import {
  matchBadge,
  partitionKinds,
  suggestionContextFor,
  suggestionTooltip,
} from '../../src/builder/advanced_viz/kindPicker';

const kind = (viz_kind: string, label = viz_kind): AdvancedVizKindDescriptor =>
  ({
    viz_kind,
    label,
    description: '',
    icon: 'tabler:chart-dots',
    required_roles: [],
    roles: {},
    category: 'plot',
    legacy: false,
  }) as unknown as AdvancedVizKindDescriptor;

const suggestion = (
  viz_kind: string,
  score: number,
  extra: Partial<VizKindSuggestion> = {},
): VizKindSuggestion => ({
  viz_kind,
  score,
  role_candidates: {},
  unmet_roles: [],
  weak_roles: [],
  ...extra,
});

const meta = (m: Partial<StoredMetadata> & { index: string; component_type: string }) =>
  m as StoredMetadata;

describe('matchBadge', () => {
  it('names the evidence, never a percentage', () => {
    expect(matchBadge(suggestion('volcano', 1, { match: 'named' }))?.label).toBe('Named match');
    expect(matchBadge(suggestion('scatter_xy', 0.9, { match: 'shape' }))?.label).toBe('Shape match');
    expect(matchBadge(suggestion('record_card', 0.9, { match: 'context' }))?.label).toBe(
      'Fits your selection',
    );
    expect(matchBadge(suggestion('knee_plot', 0.7, { match: 'weak' }))?.label).toBe('Weak');
    for (const m of ['named', 'shape', 'context', 'weak'] as const) {
      expect(matchBadge(suggestion('k', 0.5, { match: m }))?.label).not.toMatch(/%/);
    }
  });

  it('shows nothing when the API sent no match (older backend)', () => {
    expect(matchBadge(suggestion('volcano', 0.9))).toBeNull();
    expect(matchBadge(undefined)).toBeNull();
  });
});

describe('suggestionTooltip', () => {
  it('lists the reasons, then the roles the collection cannot fill', () => {
    const s = suggestion('knee_plot', 0.6, {
      match: 'weak',
      reasons: ['rank: no column named like it'],
      unmet_roles: ['umi_count'],
    });
    expect(suggestionTooltip(s)).toEqual(['rank: no column named like it', 'missing: umi_count']);
  });

  it('is empty without a suggestion', () => {
    expect(suggestionTooltip(undefined)).toEqual([]);
  });
});

describe('partitionKinds with qualitative matches', () => {
  it('still ranks by score, so a shape match can lead a weak domain kind', () => {
    const kinds = [kind('knee_plot'), kind('scatter_xy'), kind('embedding')];
    const { recommended, other } = partitionKinds(
      kinds,
      [
        suggestion('embedding', 1, { match: 'named' }),
        suggestion('scatter_xy', 0.9, { match: 'shape' }),
        suggestion('knee_plot', 0.6, { match: 'weak' }),
      ],
      null,
    );
    expect(recommended.map((r) => r.k.viz_kind)).toEqual(['embedding', 'scatter_xy']);
    expect(other.map((r) => r.k.viz_kind)).toEqual(['knee_plot']);
  });

  it('keeps the current kind pinned whatever its match', () => {
    const { current, recommended } = partitionKinds(
      [kind('record_card'), kind('scatter_xy')],
      [
        suggestion('scatter_xy', 0.9, { match: 'shape' }),
        suggestion('record_card', 0.7, { match: 'weak' }),
      ],
      'record_card',
    );
    expect(current?.k.viz_kind).toBe('record_card');
    expect(matchBadge(current?.suggestion)?.label).toBe('Weak');
    expect(recommended.map((r) => r.k.viz_kind)).toEqual(['scatter_xy']);
  });
});

describe('suggestionContextFor', () => {
  const DASHBOARD: StoredMetadata[] = [
    meta({ index: 'self', component_type: 'advanced_viz', viz_kind: 'record_card', config: {} }),
    meta({
      index: 'tbl',
      component_type: 'table',
      row_selection_enabled: true,
      row_selection_column: 'assembly_id',
    }),
    meta({
      index: 'pca',
      component_type: 'advanced_viz',
      viz_kind: 'embedding',
      config: { selection_enabled: true, sample_id_col: 'sample_id' },
    }),
    meta({
      index: 'man',
      component_type: 'advanced_viz',
      viz_kind: 'manhattan',
      config: { selection_enabled: true },
    }),
    meta({ index: 'tbl-off', component_type: 'table', row_selection_enabled: false }),
  ];

  it('collects the named selection columns and the kinds already on the tab', () => {
    expect(suggestionContextFor(DASHBOARD, 'self')).toEqual({
      selectionColumns: ['assembly_id', 'sample_id'],
      existingKinds: ['embedding', 'manhattan'],
    });
  });

  it('does not count the edited component as its own source', () => {
    const ctx = suggestionContextFor(DASHBOARD, 'pca');
    expect(ctx.selectionColumns).toEqual(['assembly_id']);
    expect(ctx.existingKinds).toEqual(['manhattan', 'record_card']);
  });

  it('is empty on an empty tab', () => {
    expect(suggestionContextFor([], null)).toEqual({ selectionColumns: [], existingKinds: [] });
  });
});
