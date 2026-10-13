import { describe, expect, it } from 'vitest';

import type { DashboardData, StoredMetadata } from '../api';
import {
  canHighlight,
  findHighlightSource,
  highlightMetadata,
  highlightOnTab,
  highlightSourceRef,
  highlightStyleRequest,
  resolveHighlightTab,
} from './highlightTile';
import type { TabLinkResolver, TabLinkTarget } from './tabLinks';
import { tabLinkKey } from './tabLinks';

const ALPHA_ID = '6ac39c1b0395845c79494761';
const UUID = '49f7c43c-8cd9-44fe-91f7-e3cb554fdca5';

const alphaLink: TabLinkTarget = {
  href: `/dashboard/${ALPHA_ID}`,
  dashboardId: ALPHA_ID,
  label: 'Alpha Diversity',
};

/** A resolver over one tab, answering to its name and its id. */
const resolve: TabLinkResolver = (name) =>
  [tabLinkKey('Alpha Diversity'), ALPHA_ID].includes(tabLinkKey(name)) ? alphaLink : null;

const plateau = {
  index: 'trec-fig-alpha-plateau',
  component_type: 'figure',
  title: 'Faith PD at the deepest rarefaction depth, per locality',
  visu_type: 'scatter',
  dc_id: 'dc-alpha',
  wf_id: 'wf-1',
  mode: 'code',
  code_content: 'fig = px.scatter(df)',
  selection_enabled: true,
  selection_column: 'sample',
  tag: 'alpha-plateau',
  section: 'Rarefaction',
  subtitle: 'per locality',
} as StoredMetadata;

const depth = {
  index: UUID,
  component_type: 'figure',
  title: 'Is the rarefaction depth enough?',
} as StoredMetadata;

const rarefaction = {
  index: 'alpha-rarefaction-multi',
  component_type: 'advanced_viz',
  title: 'Rarefaction curves',
} as StoredMetadata;

const filter = { index: 'f-1', component_type: 'interactive', title: 'Locality' } as StoredMetadata;

const alphaTab = [plateau, depth, rarefaction, filter];

const highlight = {
  index: 'hl-1',
  component_type: 'highlight',
  source_tab: 'Alpha Diversity',
  source_component: 'trec-fig-alpha-plateau',
  section: 'At a glance',
} as StoredMetadata;

describe('canHighlight', () => {
  it('takes figures and advanced visualisations only', () => {
    expect(canHighlight(plateau)).toBe(true);
    expect(canHighlight(rarefaction)).toBe(true);
    expect(canHighlight(filter)).toBe(false);
    expect(canHighlight({ component_type: 'highlight' })).toBe(false);
  });
});

describe('resolveHighlightTab', () => {
  it('finds the tab by name, with its link', () => {
    expect(resolveHighlightTab({ source_tab: ' alpha  diversity ' }, resolve)).toEqual({
      dashboardId: ALPHA_ID,
      link: alphaLink,
    });
  });

  it('prefers the id, which survives a rename', () => {
    const r = resolveHighlightTab({ source_tab: 'Old name', source_dashboard_id: ALPHA_ID }, resolve);
    expect(r.dashboardId).toBe(ALPHA_ID);
    expect(r.link).toBe(alphaLink);
  });

  it('falls back to the name when the id is unknown, as after a re-import', () => {
    const r = resolveHighlightTab(
      { source_tab: 'Alpha Diversity', source_dashboard_id: '000000000000000000000000' },
      resolve,
    );
    expect(r.dashboardId).toBe(ALPHA_ID);
  });

  it('uses a written id as is when no tab answers to it', () => {
    expect(resolveHighlightTab({ source_dashboard_id: 'abc' }, null)).toEqual({
      dashboardId: 'abc',
      link: null,
    });
    expect(resolveHighlightTab({ source_tab: ALPHA_ID.toUpperCase() }, null).dashboardId).toBe(
      ALPHA_ID.toUpperCase(),
    );
  });

  it('has nothing to go on for an unknown name', () => {
    expect(resolveHighlightTab({ source_tab: 'Nowhere' }, resolve)).toEqual({
      dashboardId: null,
      link: null,
    });
    expect(resolveHighlightTab({}, resolve).dashboardId).toBeNull();
  });
});

describe('findHighlightSource', () => {
  it('finds the figure by index', () => {
    expect(findHighlightSource(alphaTab, 'trec-fig-alpha-plateau')).toEqual({
      ok: true,
      component: plateau,
    });
  });

  it('else by title, ignoring case and spacing', () => {
    const r = findHighlightSource(alphaTab, '  is the  RAREFACTION depth enough? ');
    expect(r.ok && r.component).toBe(depth);
  });

  it('prefers a figure when a filter has the same title', () => {
    const same = { ...filter, title: 'Rarefaction curves' } as StoredMetadata;
    const r = findHighlightSource([same, rarefaction], 'Rarefaction curves');
    expect(r.ok && r.component).toBe(rarefaction);
  });

  it('reports a component a highlight cannot show', () => {
    expect(findHighlightSource(alphaTab, 'f-1')).toEqual({
      ok: false,
      reason: 'unsupported',
      component: filter,
    });
  });

  it('reports a missing one', () => {
    expect(findHighlightSource(alphaTab, 'gone')).toEqual({ ok: false, reason: 'missing' });
    expect(findHighlightSource(alphaTab, '')).toEqual({ ok: false, reason: 'missing' });
    expect(findHighlightSource(undefined, 'x')).toEqual({ ok: false, reason: 'missing' });
  });
});

describe('highlightSourceRef', () => {
  it('names a figure by a readable index', () => {
    expect(highlightSourceRef(plateau, alphaTab)).toBe('trec-fig-alpha-plateau');
  });

  it('names a figure with a UUID index by its title, which a re-import keeps', () => {
    expect(highlightSourceRef(depth, alphaTab)).toBe('Is the rarefaction depth enough?');
  });

  it('keeps the UUID when the title is missing or shared', () => {
    const untitled = { ...depth, title: '' } as StoredMetadata;
    expect(highlightSourceRef(untitled, [untitled])).toBe(UUID);
    const twin = { ...depth, index: 'other' } as StoredMetadata;
    expect(highlightSourceRef(depth, [depth, twin])).toBe(UUID);
  });
});

describe('highlightMetadata', () => {
  it('renders the source under the highlight’s identity, minimal by default', () => {
    const m = highlightMetadata(highlight, plateau);
    expect(m.index).toBe('hl-1');
    expect(m.section).toBe('At a glance');
    expect(m.component_type).toBe('figure');
    expect(m.dc_id).toBe('dc-alpha');
    expect(m.code_content).toBe('fig = px.scatter(df)');
    expect(m.figure_style).toBe('minimal');
    expect(m.title).toBe(plateau.title);
    expect(m.subtitle).toBe('per locality');
    expect(m.tag).toBeUndefined();
  });

  it('turns the figure’s selection off', () => {
    expect(highlightMetadata(highlight, plateau).selection_enabled).toBe(false);
  });

  it('lets the highlight set its own look', () => {
    const own = {
      ...highlight,
      title: 'Faith PD',
      subtitle: 'deepest depth',
      icon_name: 'mdi:chart-scatter-plot',
      icon_color: 'teal',
      figure_style: 'default',
      hide_legend: true,
    } as StoredMetadata;
    const m = highlightMetadata(own, plateau);
    expect([m.title, m.subtitle, m.icon_name, m.icon_color]).toEqual([
      'Faith PD',
      'deepest depth',
      'mdi:chart-scatter-plot',
      'teal',
    ]);
    expect(m.figure_style).toBe('default');
    expect(m.hide_legend).toBe(true);
  });

  it('draws an advanced visualisation in the highlight style too', () => {
    const m = highlightMetadata(highlight, rarefaction);
    expect(m.component_type).toBe('advanced_viz');
    expect(m.figure_style).toBe('minimal');
    expect(m.index).toBe('hl-1');
  });
});

describe('highlightStyleRequest', () => {
  it('asks for the style, and drops the plot title the header shows', () => {
    expect(highlightStyleRequest(highlightMetadata(highlight, plateau))).toEqual({
      figure_style: 'minimal',
      header_title: true,
      hide_legend: false,
    });
    const untitled = highlightMetadata(highlight, { ...plateau, title: '' } as StoredMetadata);
    expect(highlightStyleRequest(untitled).header_title).toBe(false);
  });
});

describe('highlightOnTab', () => {
  const landing: DashboardData = {
    dashboard_id: 'landing',
    stored_metadata: [{ index: 'card-1', component_type: 'card' }] as StoredMetadata[],
    right_panel_layout_data: [{ i: 'box-card-1', x: 0, y: 0, w: 12, h: 3 }],
  };

  it('adds a highlight that points back at the figure, sized like it', () => {
    const { dashboard, component } = highlightOnTab({
      source: depth,
      sourceComponents: alphaTab,
      sourceDashboardId: ALPHA_ID,
      sourceTabName: 'Alpha Diversity',
      sourceLayoutData: [{ i: `box-${UUID}`, x: 6, y: 9, w: 6, h: 7 }],
      target: landing,
      newId: 'hl-new',
    });
    expect(component).toMatchObject({
      index: 'hl-new',
      component_type: 'highlight',
      source_tab: 'Alpha Diversity',
      source_dashboard_id: ALPHA_ID,
      source_component: 'Is the rarefaction depth enough?',
    });
    // Unset: the tile follows the source's title and is drawn minimal.
    expect(component.title).toBeUndefined();
    expect(component.figure_style).toBeUndefined();
    expect(dashboard.stored_metadata?.map((m) => m.index)).toEqual(['card-1', 'hl-new']);
    expect(dashboard.right_panel_layout_data).toEqual([
      { i: 'box-card-1', x: 0, y: 0, w: 12, h: 3 },
      { i: 'box-hl-new', x: 6, y: 3, w: 6, h: 7 },
    ]);
    // The tab highlighted from is not touched.
    expect(alphaTab).toHaveLength(4);
  });
});
