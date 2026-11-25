import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { parseManifest, type BundleManifest } from '../src/manifest';
import {
  compactPanelSections,
  componentFor,
  familyTabs,
  formatTileRef,
  groupMountVerdict,
  parseTileRefs,
  reportCategorySource,
  restoreReportBasemaps,
  tabDoc,
  tileMountVerdict,
} from '../src/reportMount';

const FIXTURE = join(__dirname, '..', 'fixtures', 'manifest-basic.json');
const TABS_FIXTURE = join(__dirname, '..', 'fixtures', 'manifest-tabs.json');
const TAB = 'f1x70000000000000000c0de';

/** The shared fixture opens ungrouped here: its `initial_grouping` pins the
 *  contract in manifest.test.ts, and is its own case below. */
function fixture(): BundleManifest {
  const m = parseManifest(JSON.parse(readFileSync(FIXTURE, 'utf-8')));
  m.initial_grouping = null;
  return m;
}

describe('parseTileRefs', () => {
  it('reads one ref, several, and drops malformed tokens', () => {
    expect(parseTileRefs(`${TAB}:comp-card-1`)).toEqual([{ tabId: TAB, index: 'comp-card-1' }]);
    expect(parseTileRefs(` a:1  b:2\n c:3 `).map((r) => r.index)).toEqual(['1', '2', '3']);
    expect(parseTileRefs('no-colon :lead trail: ok:x')).toEqual([{ tabId: 'ok', index: 'x' }]);
    expect(parseTileRefs(null)).toEqual([]);
  });

  it('splits on the first colon only (an index may carry one)', () => {
    expect(parseTileRefs('tab:a:b')).toEqual([{ tabId: 'tab', index: 'a:b' }]);
  });

  it('reads back what formatTileRef writes', () => {
    const refs = [
      { tabId: TAB, index: 'comp-card-1' },
      { tabId: 'tab', index: 'a:b' },
    ];
    expect(parseTileRefs(refs.map(formatTileRef).join(' '))).toEqual(refs);
  });
});

describe('familyTabs / tabDoc', () => {
  it('a single-tab bundle is its one dashboard', () => {
    const m = fixture();
    m.tabs = [];
    expect(familyTabs(m).map((t) => t.id)).toEqual([m.dashboard.id]);
    expect(tabDoc(m, m.dashboard.id)).toBe(m.dashboard.doc);
    expect(tabDoc(m, 'elsewhere')).toBeNull();
  });

  it('a family is its tabs, each with its own document', () => {
    const m = parseManifest(JSON.parse(readFileSync(TABS_FIXTURE, 'utf-8')));
    expect(familyTabs(m)).toBe(m.tabs);
    for (const tab of m.tabs) expect(tabDoc(m, tab.id)).toBe(tab.doc);
  });
});

describe('tileMountVerdict', () => {
  it('mounts a live tile', () => {
    expect(tileMountVerdict(fixture(), { tabId: TAB, index: 'comp-text-1' })).toEqual({
      mount: true,
    });
  });

  it('mounts a frozen tile only while the report opens on the default state', () => {
    const m = fixture();
    expect(tileMountVerdict(m, { tabId: TAB, index: 'comp-figure-1' }).mount).toBe(true);
    m.initial_filters = [{ index: 'comp-interactive-1', value: ['Adelie'] }];
    const verdict = tileMountVerdict(m, { tabId: TAB, index: 'comp-figure-1' });
    expect(verdict.mount).toBe(false);
    expect(verdict.mount === false && verdict.reason).toMatch(/default state/);
    // A live tile follows the filters, so the initial state does not matter.
    expect(tileMountVerdict(m, { tabId: TAB, index: 'comp-text-1' }).mount).toBe(true);
  });

  it('keeps a frozen tile\'s fallback when the report opens coloured or filtered by groups', () => {
    const m = parseManifest(JSON.parse(readFileSync(FIXTURE, 'utf-8')));
    const ref = { tabId: TAB, index: 'comp-figure-1' };
    // colour-by on: the frozen figure was drawn without it
    expect(m.initial_grouping?.color_by.kind).toBe('groups');
    const verdict = tileMountVerdict(m, ref);
    expect(verdict.mount === false && verdict.reason).toMatch(/selection groups/);
    // groups that only sit there change nothing a frozen tile shows
    m.initial_grouping!.color_by = { kind: 'none' };
    expect(tileMountVerdict(m, ref).mount).toBe(true);
    // ... until one of them filters
    m.initial_grouping!.groups[0].filter_active = true;
    expect(tileMountVerdict(m, ref).mount).toBe(false);
    // a live tile follows the groups itself
    expect(tileMountVerdict(m, { tabId: TAB, index: 'comp-text-1' }).mount).toBe(true);
  });

  it('keeps the fallback for an omitted tile, naming the reason', () => {
    const m = fixture();
    m.tiers['comp-card-1'] = { tier: 'omitted', detail: 'needs the server' };
    expect(tileMountVerdict(m, { tabId: TAB, index: 'comp-card-1' })).toEqual({
      mount: false,
      reason: 'needs the server',
    });
  });

  it('keeps the fallback for a tab or a component the manifest does not hold', () => {
    const m = fixture();
    expect(tileMountVerdict(m, { tabId: 'other', index: 'comp-card-1' }).mount).toBe(false);
    expect(tileMountVerdict(m, { tabId: TAB, index: 'nope' }).mount).toBe(false);
    delete m.tiers['comp-text-1'];
    expect(tileMountVerdict(m, { tabId: TAB, index: 'comp-text-1' }).mount).toBe(false);
  });

  it('resolves components per tab of a family', () => {
    const m = parseManifest(JSON.parse(readFileSync(TABS_FIXTURE, 'utf-8')));
    for (const tab of m.tabs) {
      const meta = (tab.doc.stored_metadata as { index: string }[] | undefined) ?? [];
      for (const comp of meta) {
        expect(componentFor(m, { tabId: tab.id, index: comp.index })).not.toBeNull();
      }
    }
  });
});

describe('groupMountVerdict', () => {
  it('mounts a card row whole or not at all', () => {
    const m = fixture();
    const row = [
      { tabId: TAB, index: 'comp-card-1' },
      { tabId: TAB, index: 'comp-text-1' },
    ];
    expect(groupMountVerdict(m, row).mount).toBe(true);
    m.tiers['comp-card-1'] = { tier: 'omitted' };
    const verdict = groupMountVerdict(m, row);
    expect(verdict.mount).toBe(false);
    expect(verdict.mount === false && verdict.reason).toMatch(/^comp-card-1:/);
    expect(groupMountVerdict(m, []).mount).toBe(false);
  });
});

function tabsFixture(): BundleManifest {
  return parseManifest(JSON.parse(readFileSync(TABS_FIXTURE, 'utf-8')));
}

describe('reportCategorySource', () => {
  it("lays a child tab's own colours over the main tab's", () => {
    const m = tabsFixture();
    const [main, child] = m.tabs;
    main.doc.category_colors = { Kingdom: { Archaea: '#7048e8', Bacteria: '#000000' } };
    child.doc.category_colors = { Kingdom: { Bacteria: '#1098ad' } };
    const src = reportCategorySource(m, child.id) as Record<string, unknown>;
    expect(src.inherited_category_colors).toEqual(main.doc.category_colors);
    expect(src.category_colors).toEqual({ Kingdom: { Bacteria: '#1098ad' } });
    // The main tab inherits nothing from itself.
    const own = reportCategorySource(m, main.id) as Record<string, unknown>;
    expect(own.category_colors).toEqual(main.doc.category_colors);
    expect(own.inherited_category_colors).toBeNull();
    expect(reportCategorySource(m, 'not-a-tab')).toBeNull();
  });
});

describe('restoreReportBasemaps', () => {
  it("gives a frozen map the dashboard's basemap back", () => {
    const m = tabsFixture();
    m.tabs[0].doc.stored_metadata = [
      { index: 'map-1', component_type: 'map', map_style: 'carto-positron' },
      { index: 'map-2', component_type: 'map', map_style: 'white-bg' },
    ];
    const blank = () => ({
      kind: 'map',
      filter_state: [],
      payload: { figure: { data: [], layout: { map: { style: 'white-bg' } } } },
    });
    m.frozen['map-1'] = blank();
    m.frozen['map-2'] = blank();
    expect(restoreReportBasemaps(m)).toBe(1);
    const style = (k: string) =>
      (m.frozen[k].payload.figure as { layout: { map: { style: string } } }).layout.map.style;
    expect(style('map-1')).toBe('carto-positron');
    // The author chose a blank basemap: it stays blank.
    expect(style('map-2')).toBe('white-bg');
  });
});

describe('compactPanelSections', () => {
  const components = [
    { index: 'f1', section: 'Sample filters' },
    { index: 'f2', section: 'Environment' },
    { index: 'f3', section: 'Key figures' },
  ];
  it('folds every section but one narrowing the exported view', () => {
    const out = compactPanelSections(
      [
        { name: 'Sample filters', collapsed: false },
        { name: 'Environment', collapsed: false },
      ],
      components,
      new Set(['f2']),
      [{ name: 'Key figures', appearance: 'plain', filter_bar: true }, { name: 'Unused bar' }],
    );
    expect(out.map((s) => [s.name, s.collapsed])).toEqual([
      ['Sample filters', true],
      ['Environment', false],
      // A section bar's filters, declared so they fold too; a bar with no
      // control in the panel is left out.
      ['Key figures', true],
    ]);
    expect(out[2]).not.toHaveProperty('appearance');
  });
});
