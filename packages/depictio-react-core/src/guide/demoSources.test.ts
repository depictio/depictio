import { describe, expect, it } from 'vitest';

import type { FilterSectionSpec, StoredMetadata } from '../api';
import {
  actionsTileRank,
  analysisCardRank,
  analysisFigureRank,
  analysisTableRank,
  demoSectionsOf,
  familyOrder,
  foldableSectionsOf,
  pickFilterDemo,
  pickFromFamily,
  type GuideDemoSection,
  type GuideFamilyDoc,
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
  it('wants a figure a lasso can make a group on', () => {
    expect(
      analysisFigureRank(
        meta({
          index: 'f',
          component_type: 'figure',
          visu_type: 'scatter',
          selection_enabled: true,
          selection_column: 'sample_id',
        }),
      ),
    ).toBe(0);
    expect(
      analysisFigureRank(meta({ index: 'f', component_type: 'figure', visu_type: 'box' })),
    ).toBeNull();
  });

  it('puts a code figure that never draws the groups last', () => {
    const scatter = (code_content: string) =>
      meta({
        index: 'f',
        component_type: 'figure',
        visu_type: 'scatter',
        mode: 'code',
        code_content,
        selection_enabled: true,
        selection_column: 'sample_id',
      });
    expect(
      analysisFigureRank(scatter('px.scatter(df, x="a", y="b", **depictio_group_kwargs)')),
    ).toBe(0);
    expect(analysisFigureRank(scatter('px.scatter(df, x="a", y="b", color="city")'))).toBe(2);
    expect(
      analysisFigureRank(
        meta({
          index: 'e',
          component_type: 'advanced_viz',
          viz_kind: 'embedding',
          config: { viz_kind: 'embedding', sample_id_col: 'sample_id', selection_enabled: true },
        }),
      ),
    ).toBe(1);
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
