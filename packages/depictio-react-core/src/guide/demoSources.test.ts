import { describe, expect, it } from 'vitest';

import type { FilterSectionSpec, PersistentSection, StoredMetadata } from '../api';
import {
  actionsTileRank,
  analysisCardRank,
  analysisFigureRank,
  analysisSelectableFigureRank,
  analysisTableRank,
  demoSectionsOf,
  excludedOnTab,
  familyOrder,
  figureDrawsGroups,
  foldableSectionsOf,
  groupDisplaysOf,
  pickFilterDemo,
  pickFromFamily,
  pinnedDemoSections,
  siblingDemoSections,
  type GuideDemoSection,
  type GuideFamilyDoc,
  type GuideSectionsDoc,
} from './demoSources';

const meta = (m: Partial<StoredMetadata> & { index: string; component_type: string }) =>
  m as StoredMetadata;

describe('pickFilterDemo', () => {
  const card = meta({ index: 'k', component_type: 'card', dc_id: 'meta' });
  const otherCard = meta({ index: 'k2', component_type: 'card', dc_id: 'taxa' });
  const slider = meta({
    index: 's',
    component_type: 'interactive',
    interactive_component_type: 'RangeSlider',
    dc_id: 'meta',
    column_name: 'depth',
  });
  const city = meta({
    index: 'c',
    component_type: 'interactive',
    interactive_component_type: 'MultiSelect',
    dc_id: 'meta',
    column_name: 'city',
  });

  it('pairs the first card with a categorical filter on its data', () => {
    expect(pickFilterDemo([otherCard, slider, card, city])).toEqual({ card, control: city });
  });

  it('takes any filter on the same data before one elsewhere', () => {
    expect(pickFilterDemo([card, slider])).toEqual({ card, control: slider });
  });

  it('falls back to the first card and filter, or nothing', () => {
    expect(pickFilterDemo([otherCard, city])).toEqual({ card: otherCard, control: city });
    expect(pickFilterDemo([city])).toBeNull();
    expect(pickFilterDemo([card])).toBeNull();
  });
});

describe('foldableSectionsOf', () => {
  const specs: FilterSectionSpec[] = [
    { name: 'Heading', appearance: 'plain' },
    { name: 'Bar', display: 'strip' } as FilterSectionSpec,
    { name: 'Box', appearance: 'box', icon: 'mdi:gauge' },
    { name: 'Empty' },
  ];
  it('keeps the named sections that fold and hold something', () => {
    const tiles = [
      meta({ index: 'a', component_type: 'text', section: 'Heading' }),
      meta({ index: 'b', component_type: 'interactive', section: 'Bar' }),
      meta({ index: 'c', component_type: 'card', section: 'Box' }),
      meta({ index: 'd', component_type: 'figure' }),
    ];
    const out = foldableSectionsOf(tiles, specs);
    expect(out.map((s) => [s.spec.name, s.members.map((m) => m.index)])).toEqual([
      ['Box', ['c']],
    ]);
  });
});

describe('demoSectionsOf', () => {
  const section = (name: string, types: string[]): GuideDemoSection => ({
    spec: { name },
    members: types.map((t, i) => meta({ index: `${name}-${i}`, component_type: t })),
  });
  const intro = section('Intro', ['text']);
  const plots = section('Plots', ['figure', 'figure']);
  const keys = section('Keys', ['card', 'card']);
  const table = section('Table', ['table']);

  it('keeps every section when there are few', () => {
    expect(demoSectionsOf([intro, keys]).map((s) => s.spec.name)).toEqual(['Intro', 'Keys']);
  });

  it('starts at the first section with cards, in canvas order', () => {
    expect(demoSectionsOf([intro, plots, keys, table]).map((s) => s.spec.name)).toEqual([
      'Keys',
      'Table',
    ]);
    // At the end of the tab, the one before it comes along.
    expect(demoSectionsOf([intro, plots, keys]).map((s) => s.spec.name)).toEqual([
      'Plots',
      'Keys',
    ]);
    // None with cards: the first ones.
    expect(demoSectionsOf([intro, plots, table]).map((s) => s.spec.name)).toEqual([
      'Intro',
      'Plots',
    ]);
  });
});

describe('excludedOnTab', () => {
  const pinned: FilterSectionSpec = { name: 'Samples', persistent: true, exclude_tabs: ['Overview'] };

  it('matches a pinned section to the tabs it is kept off, by displayed name', () => {
    expect(excludedOnTab(pinned, 'overview ')).toBe(true);
    expect(excludedOnTab(pinned, 'Quality')).toBe(false);
  });

  it('ignores the list on a section that is not pinned, or without a tab name', () => {
    expect(excludedOnTab({ ...pinned, persistent: false }, 'Overview')).toBe(false);
    expect(excludedOnTab(pinned, '')).toBe(false);
  });
});

describe('pinnedDemoSections', () => {
  const pinned = (
    owner: string,
    name: string,
    types: string[],
    spec: Partial<FilterSectionSpec> = {},
  ): PersistentSection => ({
    kind: 'grid',
    owner_dashboard_id: owner,
    spec: { name, persistent: true, ...spec },
    components: types.map((t, i) => ({
      dashboard_id: owner,
      metadata: meta({ index: `${name}-${i}`, component_type: t, section: name }),
    })),
    layouts: [{ i: `box-${name}` }],
  });
  const table = pinned('main', 'Samples', ['table'], { exclude_tabs: ['Overview'] });
  const keys = pinned('qc', 'Key figures', ['card', 'card']);

  it('leaves out a pinned section the open tab is excluded from', () => {
    expect(pinnedDemoSections([table], 'Overview')).toBeNull();
    expect(pinnedDemoSections([table], 'Quality')?.sections.map((s) => s.spec.name)).toEqual([
      'Samples',
    ]);
  });

  it('prefers the owner whose sections hold cards', () => {
    const shownOnQuality = pinned('main', 'Runs', ['table']);
    const out = pinnedDemoSections([shownOnQuality, keys], 'Quality');
    expect(out?.ownerId).toBe('qc');
    expect(out?.sections.map((s) => s.spec.name)).toEqual(['Key figures']);
    expect(out?.layouts).toEqual([{ i: 'box-Key figures' }]);
  });

  it('skips plain headings, filter bars and filter sections', () => {
    const plain = pinned('main', 'Intro', ['card'], { appearance: 'plain' });
    const bar = pinned('main', 'Bar', ['interactive'], { display: 'strip' });
    const filter: PersistentSection = { ...pinned('main', 'Filters', ['interactive']), kind: 'filter' };
    expect(pinnedDemoSections([plain, bar, filter], 'Quality')).toBeNull();
  });
});

describe('siblingDemoSections', () => {
  const doc = (sections: [string, string[]][], spec: Partial<FilterSectionSpec> = {}) =>
    ({
      stored_metadata: sections.flatMap(([name, types]) =>
        types.map((t, i) => meta({ index: `${name}-${i}`, component_type: t, section: name })),
      ),
      grid_sections: sections.map(([name]) => ({ name, ...spec })),
    }) as GuideSectionsDoc;
  const tables = doc([['Tables', ['table']]]);
  const cards = doc([['Key figures', ['card']]]);
  const nameOf = (id: string) => id;

  it('takes the first sibling whose sections hold cards over an earlier one without', () => {
    const docs: Record<string, GuideSectionsDoc> = { a: tables, b: cards };
    const out = siblingDemoSections(['a', 'b'], (id) => docs[id], nameOf);
    expect(out.status === 'found' && out.dashboardId).toBe('b');
  });

  it('asks for the next tab while none with cards has turned up', () => {
    const docs: Record<string, GuideSectionsDoc | undefined> = { a: tables };
    expect(siblingDemoSections(['a', 'b'], (id) => docs[id], nameOf)).toEqual({
      status: 'pending',
      need: 'b',
    });
  });

  it('falls back to the first sibling with sections, then to none', () => {
    const docs: Record<string, GuideSectionsDoc | null> = { a: null, b: tables, c: doc([]) };
    const out = siblingDemoSections(['a', 'b', 'c'], (id) => docs[id], nameOf);
    expect(out.status === 'found' && out.dashboardId).toBe('b');
    expect(siblingDemoSections(['a', 'c'], (id) => docs[id], nameOf)).toEqual({ status: 'none' });
  });

  it("does not count a tab's pinned section it is excluded from", () => {
    const hidden = doc([['Key figures', ['card']]], { persistent: true, exclude_tabs: ['b'] });
    const docs: Record<string, GuideSectionsDoc> = { b: hidden };
    expect(siblingDemoSections(['b'], (id) => docs[id], nameOf)).toEqual({ status: 'none' });
  });
});

describe('pickFromFamily', () => {
  const fig = (index: string, extra: Partial<StoredMetadata> = {}) =>
    meta({ index, component_type: 'figure', visu_type: 'bar', ...extra });
  const scatter = (index: string, column = 'sample_id') =>
    fig(index, { visu_type: 'scatter', selection_enabled: true, selection_column: column });
  const docs: Record<string, GuideFamilyDoc | null | undefined> = {
    here: { stored_metadata: [fig('bar-here')] },
    main: { stored_metadata: [scatter('pcoa')] },
    other: null,
  };
  const docFor = (id: string) => docs[id];

  it('orders the open tab first, then the sidebar', () => {
    expect(familyOrder('b', ['a', 'b', 'c'])).toEqual(['b', 'a', 'c']);
  });

  it("takes the open tab's own before a better one on a sibling", () => {
    expect(pickFromFamily(['here', 'main'], docFor, actionsTileRank('figure'))).toMatchObject({
      status: 'found',
      dashboardId: 'here',
      metadata: { index: 'bar-here' },
    });
  });

  it('asks for the next document while it cannot decide', () => {
    expect(pickFromFamily(['other', 'later'], docFor, actionsTileRank('figure'))).toEqual({
      status: 'pending',
      need: 'later',
    });
    expect(pickFromFamily(['other'], docFor, actionsTileRank('table'))).toEqual({
      status: 'none',
    });
  });

  it('looks across tabs for the best match when asked to', () => {
    const tables: Record<string, GuideFamilyDoc> = {
      a: {
        stored_metadata: [
          meta({
            index: 't-id',
            component_type: 'table',
            row_selection_enabled: true,
            row_selection_column: 'ID',
          }),
        ],
      },
      b: {
        stored_metadata: [
          meta({
            index: 't-sample',
            component_type: 'table',
            row_selection_enabled: true,
            row_selection_column: 'sample_id',
          }),
        ],
      },
    };
    const rank = analysisTableRank(scatter('pcoa'));
    expect(pickFromFamily(['a', 'b'], (id) => tables[id], rank)).toMatchObject({
      metadata: { index: 't-id' },
    });
    expect(
      pickFromFamily(['a', 'b'], (id) => tables[id], rank, { acrossTabs: true }),
    ).toMatchObject({ dashboardId: 'b', metadata: { index: 't-sample' } });
  });
});

describe('the Analysis demo picks', () => {
  const lassoScatter = (extra: Partial<StoredMetadata> = {}) =>
    meta({
      index: 'f',
      component_type: 'figure',
      visu_type: 'scatter',
      selection_enabled: true,
      selection_column: 'sample_id',
      ...extra,
    });
  const view = (viz_kind: string, config: Record<string, unknown> = {}) =>
    meta({
      index: viz_kind,
      component_type: 'advanced_viz',
      viz_kind,
      config: { viz_kind, ...config },
    });
  const embedding = view('embedding', { sample_id_col: 'sample_id', selection_enabled: true });
  const rarefaction = view('rarefaction', { sample_id_col: 'sample_id' });

  it('wants a figure that draws the groups overlaid and split, and takes a lasso', () => {
    expect(analysisFigureRank(lassoScatter())).toBe(0);
    // Drawn both ways, the groups made in a table: before a lasso that only
    // colours them, which is what an ordination does.
    const box = meta({ index: 'b', component_type: 'figure', visu_type: 'box' });
    expect(analysisFigureRank(box)).toBe(1);
    expect(analysisFigureRank(rarefaction)).toBe(1);
    expect(analysisFigureRank(embedding)).toBe(2);
    expect(analysisFigureRank(embedding)! > analysisFigureRank(rarefaction)!).toBe(true);
  });

  it('leaves out what draws no group and takes no lasso', () => {
    // A heatmap is drawn whole from its frame, a stacked bar overlaid is a sum.
    expect(
      analysisFigureRank(meta({ index: 'h', component_type: 'figure', visu_type: 'heatmap' })),
    ).toBeNull();
    expect(analysisFigureRank(view('stacked_taxonomy', { sample_id_col: 'sample_id' }))).toBeNull();
    expect(analysisFigureRank(view('phylogenetic'))).toBeNull();
    expect(analysisFigureRank(meta({ index: 't', component_type: 'table' }))).toBeNull();
  });

  it('puts a code figure that never draws the groups last', () => {
    const code = (code_content: string) => lassoScatter({ mode: 'code', code_content });
    expect(analysisFigureRank(code('px.scatter(df, **depictio_group_kwargs)'))).toBe(0);
    expect(analysisFigureRank(code('px.scatter(df, color="city")'))).toBe(3);
    // No lasso, and code that spreads no group: nothing to show in any step.
    const box = meta({ index: 'c', component_type: 'figure', mode: 'code', code_content: '' });
    expect(analysisFigureRank(box)).toBeNull();
  });

  it('falls back to a figure that takes a lasso, whatever it draws', () => {
    expect(analysisSelectableFigureRank(rarefaction)).toBeNull();
    expect(analysisSelectableFigureRank(embedding)).toBe(2);
    expect(analysisSelectableFigureRank(lassoScatter())).toBe(0);
  });

  it('says how a figure draws the groups, by the rules it is drawn by', () => {
    expect(groupDisplaysOf(lassoScatter())).toEqual({ overlay: true, split: true });
    expect(groupDisplaysOf(embedding)).toEqual({ overlay: true, split: false });
    expect(groupDisplaysOf(rarefaction)).toEqual({ overlay: true, split: true });
    expect(groupDisplaysOf(meta({ index: 't', component_type: 'table' }))).toEqual({
      overlay: false,
      split: false,
    });
    const figure = (visu_type: string) => meta({ index: 'g', component_type: 'figure', visu_type });
    expect(figureDrawsGroups(figure('scatter_geo'))).toBe(false);
    expect(figureDrawsGroups(figure('Heatmap'))).toBe(false);
    expect(figureDrawsGroups(figure('violin'))).toBe(true);
  });

  it("wants a table keyed on the figure's points, and one that reaches them for no lasso", () => {
    const table = (index: string, row_selection_column: string, dc_id: string) =>
      meta({
        index,
        component_type: 'table',
        row_selection_enabled: true,
        row_selection_column,
        dc_id,
      });
    const curves = { ...rarefaction, dc_id: 'curves' } as StoredMetadata;
    const forCurves = analysisTableRank(curves);
    expect(forCurves(table('alpha', 'sample_id', 'alpha'))).toBe(0);
    expect(forCurves(table('own', 'run', 'curves'))).toBe(1);
    expect(forCurves(table('meta', 'ID', 'meta'))).toBeNull();
    // A figure that takes a lasso makes its own groups: any table adds a way.
    const forLasso = analysisTableRank({ ...embedding, dc_id: 'ord' } as StoredMetadata);
    expect(forLasso(table('alpha', 'sample_id', 'alpha'))).toBe(0);
    expect(forLasso(table('meta', 'ID', 'meta'))).toBe(2);
    expect(analysisTableRank(null)(table('meta', 'ID', 'meta'))).toBe(0);
    expect(forLasso(meta({ index: 'x', component_type: 'table' }))).toBeNull();
  });

  it('prefers a card on the same data, and one that is not a count', () => {
    const rank = analysisCardRank(['alpha']);
    const card = (aggregation: string, dc_id: string) =>
      rank(meta({ index: 'c', component_type: 'card', aggregation, dc_id }));
    expect(card('median', 'alpha')).toBe(0);
    expect(card('nunique', 'alpha')).toBe(1);
    expect(card('median', 'meta')).toBe(2);
    expect(card('count', 'meta')).toBe(3);
  });
});

describe('actionsTileRank', () => {
  it('keeps floating maps for last and skips empty text', () => {
    const rank = actionsTileRank('map');
    expect(
      rank(
        meta({
          index: 'm',
          component_type: 'map',
          placement: 'floating',
          selection_enabled: true,
        }),
      ),
    ).toBe(2);
    expect(rank(meta({ index: 'm', component_type: 'map', selection_enabled: true }))).toBe(0);
    const text = actionsTileRank('text');
    expect(text(meta({ index: 't', component_type: 'text', body: '' }))).toBeNull();
    expect(text(meta({ index: 't', component_type: 'text', body: 'See [it](tab:Alpha)' }))).toBe(0);
  });

  it('puts selection before a link to a tab on a figure', () => {
    const figure = actionsTileRank('figure');
    const scatter = { component_type: 'figure', visu_type: 'scatter', selection_enabled: true };
    expect(figure(meta({ index: 'a', ...scatter, link: 'tab:Alpha' }))).toBe(0);
    expect(figure(meta({ index: 'b', ...scatter }))).toBe(1);
    expect(figure(meta({ index: 'c', component_type: 'figure', link: 'tab:Alpha' }))).toBe(2);
    expect(figure(meta({ index: 'd', component_type: 'figure' }))).toBe(3);
  });

  it('shows a MultiQC plot before the General Statistics table', () => {
    const multiqc = actionsTileRank('multiqc');
    const tile = (extra: Record<string, unknown>) =>
      meta({ index: 'q', component_type: 'multiqc', ...extra } as never);
    expect(multiqc(tile({ selected_module: 'fastqc', selected_plot: 'Sequence Counts' }))).toBe(0);
    expect(multiqc(tile({ selected_module: 'general_stats', selected_plot: 'general_stats' }))).toBe(1);
    expect(multiqc(tile({ multiqc_module: 'general_stats' }))).toBe(1);
    expect(multiqc(tile({ is_general_stats: true }))).toBe(1);
    expect(multiqc(meta({ index: 'f', component_type: 'figure' }))).toBeNull();
    // In the family, a plot wins wherever it sits after the table.
    const docs: Record<string, GuideFamilyDoc> = {
      qc: {
        stored_metadata: [
          tile({ index: 'gs', selected_module: 'general_stats', selected_plot: 'general_stats' }),
          tile({ index: 'bars', selected_module: 'cutadapt', selected_plot: 'Filtered Reads' }),
        ],
      },
    };
    expect(pickFromFamily(['qc'], (id) => docs[id], multiqc)).toMatchObject({
      status: 'found',
      metadata: { index: 'bars' },
    });
  });

  it('picks a second advanced view for its rows, of another kind where it can', () => {
    const view = (index: string, viz_kind: string) =>
      meta({ index, component_type: 'advanced_viz', viz_kind });
    const first = view('tree', 'phylogenetic');
    const second = actionsTileRank('advanced_viz', { secondTo: first });
    expect(second(first)).toBeNull();
    expect(second(view('tree-2', 'phylogenetic'))).toBeNull();
    expect(second(view('volcano', 'volcano'))).toBe(0);
    expect(second(view('heatmap', 'complex_heatmap'))).toBe(2);
    expect(second(meta({ index: 'f', component_type: 'figure' }))).toBeNull();

    const embedding = view('pcoa', 'embedding');
    const besides = actionsTileRank('advanced_viz', { secondTo: embedding });
    expect(besides(view('pcoa-2', 'embedding'))).toBe(1);
    expect(besides(view('upset', 'upset_plot'))).toBe(0);
  });
});
