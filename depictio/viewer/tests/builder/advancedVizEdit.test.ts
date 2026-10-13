/**
 * Editing an existing advanced_viz component must open on the kind it was
 * saved with, whatever the bound collection's fit scores say.
 *
 * Regression: the picker ranked the saved kind among all the others, so a
 * scatter_xy or record_card scoring under the "Recommended" bar sank into the
 * collapsed "Other visualisations" and the builder appeared to have guessed a
 * sunburst or a knee plot instead.
 *
 * Lives outside `src/` because the viewer package has no vitest of its own:
 * run it with the react-core install, rooted here, e.g.
 *   pnpm --filter depictio-react-core exec vitest run --root ../../depictio/viewer tests/builder
 */
import { describe, expect, it, vi } from 'vitest';
import type { AdvancedVizKindDescriptor, VizKindSuggestion } from 'depictio-react-core';

// The store only needs the dashboard filter reader from the package; the real
// module pulls in every renderer.
vi.mock('depictio-react-core', () => ({ readEditorFilters: () => [] }));

import { useBuilderStore } from '../../src/builder/store/useBuilderStore';
import { partitionKinds } from '../../src/builder/advanced_viz/kindPicker';

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

const KINDS = [
  kind('sunburst', 'Sunburst'),
  kind('knee_plot', 'Knee plot'),
  kind('scatter_xy', 'Scatter (X/Y)'),
  kind('record_card', 'Record card'),
  kind('volcano', 'Volcano plot'),
];

// Scores shaped like the live rnasplice collections: the saved kinds sit under
// the 0.8 "Recommended" bar while unrelated kinds clear it.
const SUGGESTIONS: VizKindSuggestion[] = [
  { viz_kind: 'sunburst', score: 0.95, role_candidates: {}, unmet_roles: [], weak_roles: [] },
  { viz_kind: 'knee_plot', score: 0.9, role_candidates: {}, unmet_roles: [], weak_roles: [] },
  { viz_kind: 'volcano', score: 0.6, role_candidates: {}, unmet_roles: [], weak_roles: [] },
  { viz_kind: 'scatter_xy', score: 0.55, role_candidates: {}, unmet_roles: [], weak_roles: ['x', 'y'] },
  { viz_kind: 'record_card', score: 0.7, role_candidates: {}, unmet_roles: [], weak_roles: [] },
];

function hydrate(vizKind: string, config: Record<string, unknown>) {
  const store = useBuilderStore.getState();
  store.init({ mode: 'edit', dashboardId: 'dash-1', componentId: `c-${vizKind}` });
  // The stored shape: `viz_kind` at the top level and inside the config blob.
  store.loadExisting({
    index: `c-${vizKind}`,
    component_type: 'advanced_viz',
    wf_id: 'wf-1',
    dc_id: 'dc-1',
    viz_kind: vizKind,
    config: { viz_kind: vizKind, ...config },
  });
  return (useBuilderStore.getState().config as { viz_kind?: string }).viz_kind ?? null;
}

describe.each([
  ['scatter_xy', { x_col: 'dim_1', y_col: 'dim_2', label_col: 'sample_id' }],
  ['record_card', { id_col: 'gene_id', title_col: 'gene_name', selection_source: 'any' }],
])('editing a saved %s', (vizKind, config) => {
  it('keeps the saved kind selected', () => {
    expect(hydrate(vizKind, config)).toBe(vizKind);
  });

  it('pins the saved kind as current, ahead of higher-scoring recommendations', () => {
    const selected = hydrate(vizKind, config);
    const { current, recommended, other } = partitionKinds(KINDS, SUGGESTIONS, selected);
    expect(current?.k.viz_kind).toBe(vizKind);
    expect(recommended.map((r) => r.k.viz_kind)).toEqual(['sunburst', 'knee_plot']);
    const offered = [...recommended, ...other].map((r) => r.k.viz_kind);
    expect(offered).not.toContain(vizKind);
  });

  it('keeps the saved kind before the scores arrive and while a search hides it', () => {
    const selected = hydrate(vizKind, config);
    expect(partitionKinds(KINDS, null, selected).current?.k.viz_kind).toBe(vizKind);
    expect(partitionKinds(KINDS, SUGGESTIONS, selected, 'volcano').current?.k.viz_kind).toBe(
      vizKind,
    );
  });
});

describe('partitionKinds with nothing selected', () => {
  it('ranks every kind and pins none', () => {
    const { current, recommended, other } = partitionKinds(KINDS, SUGGESTIONS, null);
    expect(current).toBeNull();
    expect(recommended.map((r) => r.k.viz_kind)).toEqual(['sunburst', 'knee_plot']);
    expect(other.map((r) => r.k.viz_kind)).toEqual(['record_card', 'volcano', 'scatter_xy']);
  });
});
