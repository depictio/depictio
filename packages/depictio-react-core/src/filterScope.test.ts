import { describe, expect, it } from 'vitest';

import type { FilterSectionSpec, InteractiveFilter, StoredMetadata } from './api';
import {
  activeFilterSignature,
  filtersInScope,
  mergeFilterScopes,
  NO_FILTER_SCOPES,
  planScopedRequests,
  scopedFilterIds,
  sectionFilterScopes,
  sectionScopeKey,
} from './filterScope';

const meta = (index: string, extra: Partial<StoredMetadata> = {}): StoredMetadata =>
  ({ index, component_type: 'interactive', ...extra }) as StoredMetadata;

const filter = (index: string, value: unknown, extra: Partial<InteractiveFilter> = {}) =>
  ({ index, value, ...extra }) as InteractiveFilter;

// The TREC Overview demo: a bar on "Key figures" (city, size), one on "At a
// glance" (a second city control), a tab-wide strip and a panel filter.
const SECTIONS: FilterSectionSpec[] = [
  { name: 'Quick filters', display: 'strip' },
  { name: 'Key figures', filter_bar: true },
  { name: 'At a glance', filter_bar: true },
  { name: 'Findings' },
];
const METADATA: StoredMetadata[] = [
  meta('kf-city', { section: 'Key figures' }),
  meta('kf-size', { section: 'Key figures' }),
  meta('glance-city', { section: 'At a glance' }),
  meta('strip-season', { section: 'Quick filters' }),
  meta('panel-sample', { section: 'Sample filters' }),
  meta('footer-time', { section: 'Key figures', placement: 'top' }),
  meta('kf-card', { component_type: 'card', section: 'Key figures' }),
];
const SCOPES = sectionFilterScopes(METADATA, SECTIONS);

const FILTERS: InteractiveFilter[] = [
  filter('kf-city', ['Athens']),
  filter('kf-size', []),
  filter('glance-city', ['Naples']),
  filter('strip-season', ['Spring']),
  filter('panel-sample', ['S1']),
  // A lasso on the map in "At a glance": tab-wide, wherever the map sits.
  filter('glance-map', ['S2'], { source: 'map_selection' }),
];

const indices = (fs: InteractiveFilter[]) => fs.map((f) => f.index);

describe('sectionFilterScopes', () => {
  it('binds the controls of a section bar to that section, and nothing else', () => {
    expect([...SCOPES.entries()]).toEqual([
      ['kf-city', 'Key figures'],
      ['kf-size', 'Key figures'],
      ['glance-city', 'At a glance'],
    ]);
  });

  it('scopes nothing on a dashboard without section bars', () => {
    expect(sectionFilterScopes(METADATA, [{ name: 'Quick filters', display: 'strip' }]).size).toBe(0);
    expect(sectionFilterScopes(METADATA, undefined).size).toBe(0);
  });

  it('keys a fanned-out section by its owner tab', () => {
    const foreign = sectionFilterScopes(METADATA, [{ name: 'Key figures', filter_bar: true }], 'tab-2');
    expect(foreign.get('kf-city')).toBe(sectionScopeKey('Key figures', 'tab-2'));
    expect(sectionScopeKey('Key figures', 'tab-2')).not.toBe('Key figures');
  });
});

describe('filtersInScope', () => {
  it('gives a section its own bar filters on top of the tab-wide ones', () => {
    expect(indices(filtersInScope(FILTERS, SCOPES, 'Key figures'))).toEqual([
      'kf-city',
      'kf-size',
      'strip-season',
      'panel-sample',
      'glance-map',
    ]);
    expect(indices(filtersInScope(FILTERS, SCOPES, 'At a glance'))).toEqual([
      'glance-city',
      'strip-season',
      'panel-sample',
      'glance-map',
    ]);
  });

  it('keeps every section bar filter away from the rest of the tab', () => {
    const tabWide = ['strip-season', 'panel-sample', 'glance-map'];
    expect(indices(filtersInScope(FILTERS, SCOPES, null))).toEqual(tabWide);
    // A section without a bar sees what the rest of the tab sees.
    expect(indices(filtersInScope(FILTERS, SCOPES, 'Findings'))).toEqual(tabWide);
  });

  it('hands back the same array when nothing is scoped away', () => {
    expect(filtersInScope(FILTERS, NO_FILTER_SCOPES, null)).toBe(FILTERS);
    expect(filtersInScope(FILTERS, undefined, 'Key figures')).toBe(FILTERS);
    const tabOnly = FILTERS.filter((f) => !SCOPES.has(f.index));
    expect(filtersInScope(tabOnly, SCOPES, 'Findings')).toBe(tabOnly);
  });
});

describe('mergeFilterScopes / scopedFilterIds', () => {
  it('unions scope maps, the first claim winning', () => {
    const merged = mergeFilterScopes(SCOPES, new Map([['kf-city', 'other'], ['x', 'y']]), null);
    expect(merged.get('kf-city')).toBe('Key figures');
    expect(merged.get('x')).toBe('y');
    expect(mergeFilterScopes(undefined, NO_FILTER_SCOPES)).toBe(NO_FILTER_SCOPES);
    expect(mergeFilterScopes(SCOPES)).toBe(SCOPES);
  });

  it('lists the controls of one section bar', () => {
    expect(scopedFilterIds(SCOPES, 'Key figures')).toEqual(['kf-city', 'kf-size']);
    expect(scopedFilterIds(SCOPES, 'Findings')).toEqual([]);
  });
});

describe('activeFilterSignature', () => {
  it('ignores emptied controls and order', () => {
    const a = [filter('a', ['x']), filter('b', [])];
    const b = [filter('c', null), filter('a', ['x'])];
    expect(activeFilterSignature(a)).toBe(activeFilterSignature(b));
    expect(activeFilterSignature(a)).not.toBe(activeFilterSignature([filter('a', ['y'])]));
  });
});

describe('planScopedRequests', () => {
  const cards = [
    { id: 'kf-samples', scope: 'Key figures' },
    { id: 'kf-phyla', scope: 'Key figures' },
    { id: 'meta-samples', scope: null },
    { id: 'findings-card', scope: 'Findings' },
    { id: 'glance-card', scope: 'At a glance' },
  ];

  it('sends one request per distinct filter set, each with the filters its cards see', () => {
    const plan = planScopedRequests(cards, FILTERS, SCOPES);
    expect(plan.map((p) => p.ids)).toEqual([
      ['kf-samples', 'kf-phyla'],
      ['meta-samples', 'findings-card'],
      ['glance-card'],
    ]);
    expect(indices(plan[0].filters)).toContain('kf-city');
    expect(indices(plan[1].filters)).not.toContain('kf-city');
    expect(indices(plan[1].filters)).not.toContain('glance-city');
    expect(indices(plan[2].filters)).toContain('glance-city');
  });

  it('is one request when no section bar is filtering', () => {
    const idle = FILTERS.filter((f) => !SCOPES.has(f.index));
    const plan = planScopedRequests(cards, idle, SCOPES);
    expect(plan).toHaveLength(1);
    expect(plan[0].ids).toEqual(cards.map((c) => c.id));
    // An emptied bar control does not split the batch either.
    const emptied = [...idle, filter('kf-city', [])];
    expect(planScopedRequests(cards, emptied, SCOPES)).toHaveLength(1);
  });

  it('is the unscoped request, unchanged, on a dashboard without section bars', () => {
    const plan = planScopedRequests(cards, FILTERS, NO_FILTER_SCOPES);
    expect(plan).toEqual([{ ids: cards.map((c) => c.id), filters: FILTERS }]);
    expect(plan[0].filters).toBe(FILTERS);
    expect(planScopedRequests([], FILTERS, SCOPES)).toEqual([]);
  });
});
