import { describe, expect, it } from 'vitest';

import type { StoredMetadata } from './api';
import {
  boundColumns,
  buildSpotlightIndex,
  componentKindLabel,
  componentTitle,
  foldText,
  groupSpotlightHits,
  humanizeKind,
  searchSpotlight,
  snippetAround,
  stripMarkdown,
  type SpotlightHit,
  type SpotlightTab,
} from './spotlight';

const m = (fields: Partial<StoredMetadata> & { index: string }): StoredMetadata => ({
  component_type: 'figure',
  ...fields,
});

/** The text a hit's title ranges cover. */
const emphasised = (hit: SpotlightHit) =>
  hit.titleRanges.map(([a, b]) => hit.entry.title.slice(a, b));

const titles = (hits: SpotlightHit[]) => hits.map((h) => h.entry.title);

describe('stripMarkdown', () => {
  it('drops block syntax and keeps the words', () => {
    const body = [
      '# Sampling campaign',
      '',
      'Samples were taken at **three** stations.',
      '',
      '- first *cruise*',
      '1. second `cruise`',
      '> a quote',
      '---',
      '::: steps',
      'one step',
      ':::',
    ].join('\n');
    expect(stripMarkdown(body)).toBe(
      'Sampling campaign Samples were taken at three stations. first cruise second cruise a quote one step',
    );
  });

  it('keeps link labels, tab links included, and swatch legends; drops icons', () => {
    expect(
      stripMarkdown(
        'See [the map](tab:Environment (CTD)) or [docs](https://example.org). ' +
          '![](icon:mdi:dna) ![Athens](color:#1a4f8f) station',
      ),
    ).toBe('See the map or docs. Athens station');
  });

  it('reads a pipe table as its cells', () => {
    expect(stripMarkdown('| Site | Depth |\n| --- | ---: |\n| A | 10 |')).toBe(
      'Site · Depth A · 10',
    );
  });

  it('leaves snake_case and lone asterisks alone, removes HTML', () => {
    expect(stripMarkdown('bill_length_mm * 2 <br/> &amp; more')).toBe(
      'bill_length_mm * 2 & more',
    );
  });

  it('handles empty input', () => {
    expect(stripMarkdown('')).toBe('');
    expect(stripMarkdown(undefined)).toBe('');
  });
});

describe('foldText', () => {
  it('lowers case and drops accents without changing length', () => {
    expect(foldText('Écosystème Ölands')).toBe('ecosysteme olands');
    expect(foldText('İstanbul').length).toBe('İstanbul'.length);
  });
});

describe('component labels', () => {
  it('names a chart by its kind and other types by their type', () => {
    expect(componentKindLabel(m({ index: 'a', visu_type: 'sunburst' }))).toBe('Sunburst');
    expect(componentKindLabel(m({ index: 'a', visu_type: 'scatter_3d' }))).toBe('3D scatter');
    expect(
      componentKindLabel(m({ index: 'a', component_type: 'advanced_viz', viz_kind: 'qq' })),
    ).toBe('QQ plot');
    expect(componentKindLabel(m({ index: 'a', component_type: 'card' }))).toBe('Card');
    expect(componentKindLabel(m({ index: 'a', component_type: 'interactive' }))).toBe('Filter');
    expect(humanizeKind('stacked_taxonomy')).toBe('Stacked taxonomy');
    expect(humanizeKind('RangeSlider')).toBe('Range slider');
  });

  it('titles an untitled component the way its tile does', () => {
    expect(
      componentTitle(
        m({
          index: 'a',
          component_type: 'interactive',
          interactive_component_type: 'MultiSelect',
          column_name: 'island',
        }),
      ),
    ).toBe('Select on island');
    expect(
      componentTitle(
        m({ index: 'a', component_type: 'card', aggregation: 'mean', column_name: 'depth' }),
      ),
    ).toBe('Mean of depth');
    expect(
      componentTitle(m({ index: 'a', component_type: 'text', body: '## Methods\n\nWe sampled.' })),
    ).toBe('Methods');
    expect(
      componentTitle(m({ index: 'a', visu_type: 'scatter', dict_kwargs: { x: 'a', y: 'b' } })),
    ).toBe('Scatter of a and b');
  });

  it('collects the columns a component binds', () => {
    expect(
      boundColumns(
        m({
          index: 'a',
          column_name: 'sex',
          dict_kwargs: { x: 'bill', y: 'flipper', color: 'sex', path: ['kingdom', 'phylum'] },
          config: { rank_cols: ['genus'], abundance_col: 'count', title: 'not a column' },
          lat_column: 'lat',
        }),
      ),
    ).toEqual(['sex', 'lat', 'bill', 'flipper', 'kingdom', 'phylum', 'genus', 'count']);
  });
});

const TABS: SpotlightTab[] = [
  {
    id: 'main',
    label: 'Overview',
    description: 'What the study is',
    components: [
      m({ index: 'c1', component_type: 'card', title: 'Samples', column_name: 'sample_id' }),
      m({
        index: 't1',
        component_type: 'text',
        body: '## About\n\nThe **Tara** expedition sampled plankton across the oceans.',
      }),
    ],
  },
  {
    id: 'tax',
    label: 'Taxonomy',
    description: 'Who is there',
    group: 'Community',
    components: [
      m({
        index: 'f1',
        title: 'Community composition',
        visu_type: 'sunburst',
        section: 'Composition',
        dict_kwargs: { path: ['phylum', 'genus'] },
      }),
      m({
        index: 'f2',
        title: 'Read depth per sample',
        subtitle: 'Sequencing effort',
        visu_type: 'bar',
      }),
      m({ index: 'f3', title: 'Metadata overview', visu_type: 'scatter' }),
      m({
        index: 'i1',
        component_type: 'interactive',
        interactive_component_type: 'MultiSelect',
        column_name: 'station',
        section: 'Where',
      }),
    ],
  },
];

describe('searchSpotlight', () => {
  const index = buildSpotlightIndex(TABS);

  it('indexes every tab and every component', () => {
    expect(index.filter((e) => e.kind === 'tab')).toHaveLength(2);
    expect(index.filter((e) => e.kind === 'component')).toHaveLength(6);
  });

  it('lists the tabs for an empty query', () => {
    expect(titles(searchSpotlight(index, '  '))).toEqual(['Overview', 'Taxonomy']);
  });

  it('ranks a prefix and a word start above a match inside a word', () => {
    // "Data…" nowhere; "Metadata" holds it inside a word, which ranks last.
    const hits = searchSpotlight(index, 'comp');
    expect(titles(hits)[0]).toBe('Community composition');
    const ranked = titles(searchSpotlight(index, 'over'));
    expect(ranked.indexOf('Overview')).toBeLessThan(ranked.indexOf('Metadata overview'));
  });

  it('weights a title above a body', () => {
    const hits = searchSpotlight(index, 'sample');
    // Title prefix ("Samples") beats a title word start beats a body hit.
    expect(titles(hits).slice(0, 2)).toEqual(['Samples', 'Read depth per sample']);
    expect(titles(hits)).toContain('About');
    expect(titles(hits).indexOf('About')).toBeGreaterThan(1);
  });

  it('finds a text tile by its prose, with the match in the snippet', () => {
    const [hit] = searchSpotlight(index, 'plankton');
    expect(hit.entry.index).toBe('t1');
    expect(hit.snippet?.field).toBe('body');
    const [a, b] = hit.snippet!.ranges[0];
    expect(hit.snippet!.text.slice(a, b)).toBe('plankton');
  });

  it('finds components by kind, column and section', () => {
    expect(searchSpotlight(index, 'sunburst')[0].entry.index).toBe('f1');
    expect(searchSpotlight(index, 'genus')[0].entry.index).toBe('f1');
    expect(searchSpotlight(index, 'genus')[0].snippet).toMatchObject({
      field: 'column',
      text: 'genus',
    });
    expect(searchSpotlight(index, 'where')[0].entry.index).toBe('i1');
    expect(searchSpotlight(index, 'filter')[0].entry.title).toBe('Select on station');
  });

  it('needs every word, and emphasises each in the title', () => {
    const hits = searchSpotlight(index, 'read sample');
    expect(titles(hits)).toEqual(['Read depth per sample']);
    expect(emphasised(hits[0])).toEqual(['Read', 'sample']);
    expect(searchSpotlight(index, 'read plankton')).toEqual([]);
  });

  it('ignores case and accents', () => {
    expect(titles(searchSpotlight(index, 'TAXONOMÝ'))[0]).toBe('Taxonomy');
  });

  it('does not match one or two letters inside a word', () => {
    // "ta" starts "Tara" (a word start) but is only inside "Metadata".
    const hits = searchSpotlight(index, 'ta');
    expect(titles(hits)).toContain('About');
    expect(titles(hits)).not.toContain('Metadata overview');
  });

  it('shows the description as context when the title held the match', () => {
    const [hit] = searchSpotlight(index, 'read depth');
    expect(hit.snippet).toEqual({ field: 'subtitle', text: 'Sequencing effort', ranges: [] });
  });

  it('finds a tab by its description and group', () => {
    expect(searchSpotlight(index, 'who')[0].entry.key).toBe('tab:tax');
    expect(searchSpotlight(index, 'community').map((h) => h.entry.key)).toContain('tab:tax');
  });

  it('indexes a tab whose components are still loading by name only', () => {
    const partial = buildSpotlightIndex([{ id: 'x', label: 'Later' }]);
    expect(partial).toHaveLength(1);
    expect(titles(searchSpotlight(partial, 'lat'))).toEqual(['Later']);
  });
});

describe('groupSpotlightHits', () => {
  const index = buildSpotlightIndex(TABS);
  const order = TABS.map((t) => ({ id: t.id, label: t.label }));

  it('puts the current tab first and the tab entry first in its group', () => {
    const groups = groupSpotlightHits(searchSpotlight(index, 'o'), order, 'tax');
    expect(groups.map((g) => g.tabId)).toEqual(['tax', 'main']);
    expect(groups[0].isCurrent).toBe(true);
    const tax = groupSpotlightHits(searchSpotlight(index, 'community'), order, 'main');
    expect(tax[0].hits[0].entry.kind).toBe('tab');
  });

  it('caps a group and counts the rest', () => {
    const groups = groupSpotlightHits(searchSpotlight(index, ''), order, null, 1);
    expect(groups.every((g) => g.hits.length === 1)).toBe(true);
    const many = groupSpotlightHits(searchSpotlight(index, 'figure'), order, 'tax', 2);
    expect(many[0].hits).toHaveLength(2);
    expect(many[0].more).toBe(1);
  });
});

describe('snippetAround', () => {
  it('keeps a short text whole', () => {
    expect(snippetAround('short text', [[0, 5]])).toEqual({ text: 'short text', ranges: [[0, 5]] });
  });

  it('cuts a long text around the match and moves the range with it', () => {
    const text = `${'lorem ipsum '.repeat(10)}needle ${'dolor sit '.repeat(10)}`.trim();
    const at = text.indexOf('needle');
    const cut = snippetAround(text, [[at, at + 6]], 50);
    expect(cut.text.startsWith('…')).toBe(true);
    expect(cut.text.endsWith('…')).toBe(true);
    const [a, b] = cut.ranges[0];
    expect(cut.text.slice(a, b)).toBe('needle');
  });
});
