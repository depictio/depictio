/**
 * A text tile's live values (`values:`) are set in the dashboard YAML only:
 * the text builder lists them but has no field for them, so saving the tile
 * from the builder must carry them over untouched.
 *
 * Run like advancedVizEdit.test.ts (the viewer package has no vitest of its own):
 *   pnpm --filter depictio-react-core exec vitest run --root ../../depictio/viewer tests/builder
 */
import { describe, expect, it, vi } from 'vitest';
import type { StoredMetadata } from 'depictio-react-core';

// The store only needs the dashboard filter reader from the package; the real
// module pulls in every renderer.
vi.mock('depictio-react-core', () => ({ readEditorFilters: () => [] }));

import { buildMetadata } from '../../src/builder/buildMetadata';
import { useBuilderStore } from '../../src/builder/store/useBuilderStore';

const VALUES = {
  share: {
    dc: 'taxonomy',
    column: 'Phylum',
    aggregation: 'top_share',
    weight: 'abundance',
    format: 'percent',
    // Resolved at import; the save must not drop them either.
    dc_id: 'dc-9',
    wf_id: 'wf-1',
  },
  top: { dc: 'taxonomy', column: 'Phylum', aggregation: 'top', weight: 'abundance' },
};

const SAVED: StoredMetadata = {
  index: 'txt-1',
  component_type: 'text',
  title: 'Key results',
  body: '- **{{share}}** of reads are {{top}} [Community](tab:Community)',
  surface: 'card',
  values: VALUES,
};

describe('saving a text tile with live values from the builder', () => {
  it('keeps the values as the YAML declared them', () => {
    const store = useBuilderStore.getState();
    store.init({ mode: 'edit', dashboardId: 'dash-1', componentId: 'txt-1' });
    store.loadExisting(SAVED);
    useBuilderStore.getState().patchConfig({ title: 'Headline results' });

    const saved = buildMetadata(useBuilderStore.getState());
    expect(saved.values).toEqual(VALUES);
    expect(saved.title).toBe('Headline results');
    expect(saved.body).toBe(SAVED.body);
    // A text tile stays unbound itself: the values carry their own data.
    expect(saved.dc_id).toBeUndefined();
  });
});
