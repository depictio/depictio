import { describe, expect, it } from 'vitest';

import type {
  DashboardSummary,
  FilterSectionSpec,
  PersistentSection,
  StoredMetadata,
} from '../api';
import { buildGuideModel, resolveGuideSettings, tileActions } from './guideModel';

const meta = (m: Partial<StoredMetadata> & { index: string; component_type: string }) =>
  m as StoredMetadata;

const TABS: DashboardSummary[] = [
  { dashboard_id: 'main', title: 'Study', main_tab_name: 'Overview', subtitle: 'The study' },
  {
    dashboard_id: 'map',
    title: 'Sampling',
    parent_dashboard_id: 'main',
    tab_group: 'Samples & data',
    subtitle: ' Where and when ',
  },
  { dashboard_id: 'qc', title: 'QC', parent_dashboard_id: 'main', tab_group: 'Samples & data' },
  { dashboard_id: 'alpha', title: 'Alpha', parent_dashboard_id: 'main', tab_group: 'Analysis' },
  { dashboard_id: 'notes', title: 'Notes', parent_dashboard_id: 'main' },
];

const PANEL_SECTIONS: FilterSectionSpec[] = [
  { name: 'Sample filters', icon: 'mdi:filter-variant', persistent: true },
  { name: 'Campaign design', icon: 'mdi:tune', persistent: true, collapsed: true },
  { name: 'Declared but empty' },
];

const PANEL: StoredMetadata[] = [
  meta({ index: 'f1', component_type: 'interactive', section: 'Sample filters' }),
  meta({ index: 'f2', component_type: 'interactive', section: 'Sample filters' }),
  meta({ index: 'f3', component_type: 'interactive', section: 'Campaign design' }),
  meta({ index: 'f4', component_type: 'interactive', section: 'Local only' }),
  meta({ index: 'f5', component_type: 'interactive' }),
];

const GRID_SECTIONS: FilterSectionSpec[] = [
  { name: 'Key figures', appearance: 'plain' },
  { name: 'Details', icon: 'mdi:table' },
  { name: 'Samples in view', persistent: true, pin: 'bottom' },
];

const COMPONENTS: StoredMetadata[] = [
  meta({ index: 'intro', component_type: 'text' }),
  meta({ index: 'kpi', component_type: 'card', section: 'Key figures' }),
  meta({
    index: 'sites',
    component_type: 'map',
    title: 'Sampling sites',
    selection_enabled: true,
    section: 'Details',
  }),
  meta({
    index: 'pcoa',
    component_type: 'figure',
    title: 'PCoA',
    visu_type: 'scatter',
    selection_enabled: true,
    description: 'Bray-Curtis, first two axes',
    section: 'Details',
  }),
  meta({ index: 'hist', component_type: 'figure', visu_type: 'histogram', selection_enabled: true }),
  meta({ index: 'sheet', component_type: 'table', section: 'Samples in view' }),
];

const base = {
  tabs: TABS,
  currentId: 'map',
  components: COMPONENTS,
  gridSections: GRID_SECTIONS,
  panelComponents: PANEL,
  panelSections: PANEL_SECTIONS,
  analysisAvailable: true,
};

describe('buildGuideModel: tabs', () => {
  it('groups the tabs as the sidebar does and marks the current one', () => {
    const model = buildGuideModel(base);
    expect(model.tabs.count).toBe(5);
    expect(model.tabs.groupNames).toEqual(['Samples & data', 'Analysis']);
    expect(model.tabs.groups.map((g) => g.group)).toEqual([null, 'Samples & data', 'Analysis']);
    // Main tab and the ungrouped child lead, with no heading.
    expect(model.tabs.groups[0].tabs.map((t) => t.label)).toEqual(['Overview', 'Notes']);
    expect(model.tabs.current?.label).toBe('Sampling');
    expect(model.tabs.current?.subtitle).toBe('Where and when');
    expect(model.tabs.groups[1].tabs[1].subtitle).toBeNull();
    expect(model.tabs.groups[0].tabs[0].isMain).toBe(true);
  });
});

describe('buildGuideModel: sections', () => {
  it('lists the sections that fold, leaving plain headings out', () => {
    const model = buildGuideModel(base);
    expect(model.sections.foldable.map((s) => s.name)).toEqual(['Details', 'Samples in view']);
    expect(model.sections.pinned.map((s) => s.name)).toEqual(['Samples in view']);
  });

  it('places sections pinned from other tabs at their edge', () => {
    const fanned: PersistentSection[] = [
      {
        kind: 'grid',
        owner_dashboard_id: 'main',
        owner_tab_title: 'Overview',
        spec: { name: 'Metadata', persistent: true, pin: 'top' },
        components: [
          { dashboard_id: 'main', metadata: meta({ index: 'm1', component_type: 'card' }) },
        ],
        layouts: [],
      },
      {
        kind: 'grid',
        owner_dashboard_id: 'main',
        spec: { name: 'Empty', persistent: true },
        components: [],
        layouts: [],
      },
    ];
    const model = buildGuideModel({ ...base, fannedOutSections: fanned });
    expect(model.sections.foldable.map((s) => s.name)).toEqual([
      'Metadata',
      'Details',
      'Samples in view',
    ]);
    expect(model.sections.fannedOut).toHaveLength(1);
    expect(model.sections.fannedOut[0].fromTab).toBe('Overview');
  });
});

describe('buildGuideModel: filters', () => {
  it('buckets the panel controls as the panel does', () => {
    const model = buildGuideModel(base);
    expect(model.filters.sections.map((s) => [s.name, s.controls])).toEqual([
      ['Sample filters', 2],
      ['Campaign design', 1],
      ['Local only', 1],
    ]);
    expect(model.filters.unsectioned).toBe(1);
    expect(model.filters.total).toBe(5);
    expect(model.filters.persistent.map((s) => s.name)).toEqual([
      'Sample filters',
      'Campaign design',
    ]);
  });

  it('lists where a selection filters, the floating map last', () => {
    const model = buildGuideModel({
      ...base,
      floating: [
        {
          dashboard_id: 'main',
          metadata: meta({
            index: 'float',
            component_type: 'map',
            placement: 'floating',
            selection_enabled: true,
            title: 'All sites',
          }),
        },
      ],
    });
    // The histogram is selection-enabled but aggregates: no lasso there.
    expect(model.selection.map((s) => [s.title, s.kind, s.floating])).toEqual([
      ['Sampling sites', 'map', false],
      ['PCoA', 'figure', false],
      ['All sites', 'map', true],
    ]);
    expect(model.mapPanel).toBe(true);
  });
});

describe('buildGuideModel: actions', () => {
  it('counts the chrome actions the tiles here carry, in chrome order', () => {
    const model = buildGuideModel(base);
    expect(model.actions.map((a) => [a.key, a.count])).toEqual([
      ['group', 2],
      ['description', 1],
      ['metadata', 6],
      ['fullscreen', 4],
      ['download', 1],
      ['reset', 2],
    ]);
    expect(model.analysis).toEqual({ available: true, selectable: 2 });
    expect(model.editActions).toEqual([]);
  });

  it('drops the group action where the surface has no Analysis', () => {
    const model = buildGuideModel({ ...base, analysisAvailable: false });
    expect(model.actions.some((a) => a.key === 'group')).toBe(false);
    expect(model.analysis.available).toBe(false);
  });

  it("adds the editor's tile menu in edit mode", () => {
    const model = buildGuideModel({ ...base, mode: 'edit' });
    expect(model.editActions.map((a) => [a.key, a.count])).toEqual([
      ['drag', 6],
      ['edit', 6],
      ['duplicate', 3],
      ['move-section', 6],
      ['copy-tab', 6],
      ['font-size', 2],
      ['delete', 6],
    ]);
  });

  it('reads one tile the way ComponentChrome draws it', () => {
    const table = meta({ index: 't', component_type: 'table', row_selection_enabled: true });
    expect(tileActions(table, { analysisAvailable: true })).toEqual([
      'group',
      'metadata',
      'fullscreen',
      'download',
      'reset',
    ]);
    expect(tileActions(meta({ index: 'c', component_type: 'card' }), { analysisAvailable: true }))
      .toEqual(['metadata']);
  });
});

describe('resolveGuideSettings', () => {
  const main = { dashboard_id: 'main', show_guide: false, guide_intro: '  Hello  ' };
  const child = { dashboard_id: 'c', parent_dashboard_id: 'main', show_guide: true };

  it('reads the main tab, wherever the reader is', () => {
    expect(resolveGuideSettings(child, [main, child])).toEqual({
      enabled: false,
      intro: 'Hello',
      mainTabId: 'main',
    });
  });

  it('reads the open document on the main tab itself', () => {
    expect(resolveGuideSettings({ ...main, show_guide: true }, [main, child]).enabled).toBe(true);
  });

  it('is on, with no intro, when nothing says otherwise', () => {
    expect(resolveGuideSettings({ dashboard_id: 'c', parent_dashboard_id: 'p' }, [])).toEqual({
      enabled: true,
      intro: '',
      mainTabId: 'p',
    });
    expect(resolveGuideSettings(null, []).enabled).toBe(true);
  });
});
