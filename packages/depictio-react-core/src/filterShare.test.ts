import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { InteractiveFilter } from './api';
import {
  buildFilterShareUrl,
  syncFiltersToLocation,
  decodeFiltersFromHash,
  encodeFiltersForHash,
  sanitizeRestoredFilters,
} from './filterShare';

// The module reads `window.btoa` / `window.location`; vitest runs in node, so
// stand a minimal window in front of node's own btoa / atob.
const g = globalThis as unknown as { window?: unknown };
const replaced: string[] = [];

beforeEach(() => {
  g.window = {
    btoa: globalThis.btoa,
    atob: globalThis.atob,
    location: { origin: 'https://depictio.test', pathname: '/dashboard/abc', search: '', hash: '' },
    history: {
      state: null,
      replaceState(_s: unknown, _t: string, url: string) {
        const loc = (g.window as { location: { pathname: string; search: string; hash: string } })
          .location;
        loc.hash = url.includes('#') ? url.slice(url.indexOf('#')) : '';
        replaced.push(url);
      },
    },
  };
  replaced.length = 0;
});
afterEach(() => {
  delete g.window;
});

const panel = (index: string, value: unknown, type = 'MultiSelect'): InteractiveFilter => ({
  index,
  value: value as InteractiveFilter['value'],
  column_name: 'species',
  interactive_component_type: type,
  metadata: { dc_id: 'dc1', column_name: 'species', interactive_component_type: type },
});

const roundTrip = (filters: InteractiveFilter[]) => {
  const hash = encodeFiltersForHash(filters);
  expect(hash).not.toBeNull();
  return decodeFiltersFromHash(`#filters=${hash}`);
};

describe('filter share encoding', () => {
  it('writes panel controls as one readable line each', () => {
    const hash = encodeFiltersForHash([panel('c1', ['Adelie', 'Gentoo']), panel('c2', [3, 7.5], 'RangeSlider')]);
    expect(hash).toMatch(/^2;/);
    expect(hash?.split(';')).toHaveLength(3);
  });

  it('round-trips lists, ranges, scalars and UTF-8 values', () => {
    const filters = [
      panel('c1', ['Adélie', 'Gentoo; "x"']),
      panel('c2', [3, 7.5], 'RangeSlider'),
      panel('c3', 'solo', 'Select'),
      panel('c4', true, 'Checkbox'),
    ];
    expect(roundTrip(filters)).toEqual(filters);
  });

  it('falls back to the opaque form for selections the compact grammar cannot hold', () => {
    const selection: InteractiveFilter = {
      index: 's1',
      value: [1, 2, 3],
      source: 'scatter_selection',
      column_name: 'id',
    };
    const hash = encodeFiltersForHash([panel('c1', ['a']), selection]);
    expect(hash).not.toMatch(/^2;/);
    expect(roundTrip([panel('c1', ['a']), selection])).toEqual([panel('c1', ['a']), selection]);
  });

  it('refuses to encode a selection too large to survive as a link', () => {
    const ids = Array.from({ length: 5000 }, (_, i) => `sample-${i}`);
    const big: InteractiveFilter = { index: 't1', value: ids, source: 'table_selection' };
    expect(encodeFiltersForHash([big])).toBeNull();
    expect(buildFilterShareUrl([big])).toBeNull();
  });

  it('decodes garbage and malformed fragments to null instead of throwing', () => {
    expect(decodeFiltersFromHash('#filters=%%%')).toBeNull();
    expect(decodeFiltersFromHash('#filters=not-base64!')).toBeNull();
    expect(decodeFiltersFromHash('#other=1')).toBeNull();
    expect(decodeFiltersFromHash('')).toBeNull();
  });

  it('drops one truncated entry without losing the others', () => {
    const hash = encodeFiltersForHash([panel('c1', ['a']), panel('c2', ['b'])]) as string;
    const [head, first, second] = hash.split(';');
    const damaged = [head, first, second.slice(0, second.indexOf(':') + 3) + '%E0%A4%A'].join(';');
    expect(decodeFiltersFromHash(`#filters=${damaged}`)).toEqual([panel('c1', ['a'])]);
  });
});

describe('buildFilterShareUrl', () => {
  it('is the plain dashboard link with no filters', () => {
    expect(buildFilterShareUrl([])).toBe('https://depictio.test/dashboard/abc');
  });

  it('carries the view in the fragment, never the query', () => {
    const url = buildFilterShareUrl([panel('c1', ['a'])]) as string;
    expect(url.startsWith('https://depictio.test/dashboard/abc#filters=')).toBe(true);
    expect(url).not.toContain('?');
  });
});

describe('sanitizeRestoredFilters', () => {
  it('keeps only entries whose component exists in the dashboard family', () => {
    const kept = panel('c1', ['a']);
    const floatingMap: InteractiveFilter = { index: 'm1', value: [1], source: 'map_selection' };
    const stale = panel('gone', ['b']);
    expect(
      sanitizeRestoredFilters([kept, floatingMap, stale], new Set(['c1', 'm1'])),
    ).toEqual([kept, floatingMap]);
  });
});

describe('syncFiltersToLocation', () => {
  const loc = () => (g.window as { location: { hash: string } }).location;

  it('writes the filters into the fragment and replaces history', () => {
    syncFiltersToLocation([panel('c1', ['a'])]);
    expect(loc().hash).toMatch(/^#filters=2;/);
    expect(replaced).toHaveLength(1);
  });

  it('removes only its own param when the filters go away', () => {
    loc().hash = '#theme=dark&filters=2;x';
    syncFiltersToLocation([]);
    expect(loc().hash).toBe('#theme=dark');
  });

  it('leaves other fragment params in place beside the filters', () => {
    loc().hash = '#theme=dark';
    syncFiltersToLocation([panel('c1', ['a'])]);
    expect(loc().hash).toMatch(/^#theme=dark&filters=2;/);
  });

  it('does not touch history when nothing changed', () => {
    syncFiltersToLocation([panel('c1', ['a'])]);
    replaced.length = 0;
    syncFiltersToLocation([panel('c1', ['a'])]);
    expect(replaced).toHaveLength(0);
  });

  it('drops a selection too large to encode instead of leaving a stale one', () => {
    syncFiltersToLocation([panel('c1', ['a'])]);
    const big: InteractiveFilter = {
      index: 't1',
      value: Array.from({ length: 5000 }, (_, i) => `sample-${i}`),
      source: 'table_selection',
    };
    syncFiltersToLocation([big]);
    expect(loc().hash).toBe('');
  });
});
