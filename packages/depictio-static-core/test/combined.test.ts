import { describe, expect, it, vi } from 'vitest';

import {
  COMBINED_HOST_GLOBAL,
  createFilterChannel,
  findCombinedHost,
  formatCombinedHash,
  landingView,
  parseCombinedHash,
  resolveTab,
  scopeSelector,
  scopeSelectorList,
  splitSelectorList,
  tabSlug,
  viewMemoryKey,
} from '../src/combined';

const MAIN = '6824cb3b89d2b72169309738';
const CHILD = '6a75a191f5e6ff34386c8f0c';
const TABS = [
  { id: MAIN, title: 'Overview' },
  { id: CHILD, title: 'Species & islands' },
];

describe('filter channel', () => {
  it('starts empty, then holds what was written', () => {
    const ch = createFilterChannel();
    expect(ch.get()).toBeNull();
    expect(ch.set([{ index: 'a', value: ['x'] }], 'report')).toBe(true);
    expect(ch.get()).toEqual([{ index: 'a', value: ['x'] }]);
  });

  it('tells every view but the writer', () => {
    const ch = createFilterChannel();
    const report = vi.fn();
    const dashboard = vi.fn();
    ch.subscribe('report', report);
    ch.subscribe('dashboard', dashboard);
    ch.set([{ index: 'a', value: [1] }], 'report');
    expect(report).not.toHaveBeenCalled();
    expect(dashboard).toHaveBeenCalledWith([{ index: 'a', value: [1] }], 'report');
  });

  it('an unchanged write notifies nobody, so echoing views do not loop', () => {
    const ch = createFilterChannel();
    let echoes = 0;
    // Each view writes back whatever it hears, as a React effect would.
    ch.subscribe('report', (f) => {
      echoes++;
      ch.set(f, 'report');
    });
    ch.subscribe('dashboard', (f) => {
      echoes++;
      ch.set(f, 'dashboard');
    });
    ch.set([{ index: 'a', value: ['Adelie'] }], 'dashboard');
    expect(echoes).toBe(1);
    expect(ch.set([{ index: 'a', value: ['Adelie'] }], 'report')).toBe(false);
  });

  it('hands each reader its own copy (no object shared across realms)', () => {
    const ch = createFilterChannel();
    const value = [{ index: 'a', value: ['x'] }];
    ch.set(value, 'report');
    const read = ch.get()!;
    expect(read).toEqual(value);
    expect(read).not.toBe(value);
    (read[0] as { value: string[] }).value.push('mutated');
    expect(ch.get()).toEqual(value);
  });

  it('keeps the opening state apart from later writes', () => {
    const ch = createFilterChannel([{ index: 'a', value: ['Adelie'] }]);
    ch.set([], 'dashboard');
    expect(ch.get()).toEqual([]);
    expect(ch.initial()).toEqual([{ index: 'a', value: ['Adelie'] }]);
  });

  it('a throwing listener does not stop the others', () => {
    const ch = createFilterChannel();
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const ok = vi.fn();
    ch.subscribe('a', () => {
      throw new Error('boom');
    });
    ch.subscribe('b', ok);
    ch.set([1], 'c');
    expect(ok).toHaveBeenCalled();
    warn.mockRestore();
  });

  it('unsubscribes', () => {
    const ch = createFilterChannel();
    const fn = vi.fn();
    const off = ch.subscribe('dashboard', fn);
    off();
    ch.set([1], 'report');
    expect(fn).not.toHaveBeenCalled();
  });
});

describe('findCombinedHost', () => {
  it('finds the host on the window itself or on its parent', () => {
    const api = { filters: createFilterChannel() };
    const parent = { [COMBINED_HOST_GLOBAL]: api } as unknown as Window;
    (parent as unknown as { parent: Window }).parent = parent;
    const child = { parent } as unknown as Window;
    expect(findCombinedHost(parent)).toBe(api);
    expect(findCombinedHost(child)).toBe(api);
  });

  it('is null for a plain page and for a parent it may not read', () => {
    const lone = {} as Window;
    (lone as unknown as { parent: Window }).parent = lone;
    expect(findCombinedHost(lone)).toBeNull();
    const foreign = new Proxy(
      {},
      {
        get() {
          throw new DOMException('Blocked a frame', 'SecurityError');
        },
      },
    ) as Window;
    expect(findCombinedHost({ parent: foreign } as unknown as Window)).toBeNull();
    expect(findCombinedHost(null)).toBeNull();
  });
});

describe('deep links', () => {
  it('reads #dashboard, #dashboard/<tab id> and #dashboard/<tab title>', () => {
    expect(parseCombinedHash('#dashboard', TABS)).toEqual({ view: 'dashboard' });
    expect(parseCombinedHash(`#dashboard/${CHILD}`, TABS)).toEqual({
      view: 'dashboard',
      tab: CHILD,
    });
    expect(parseCombinedHash('#dashboard/species-islands', TABS)).toEqual({
      view: 'dashboard',
      tab: CHILD,
    });
    expect(parseCombinedHash('#dashboard/Species%20%26%20islands', TABS)).toEqual({
      view: 'dashboard',
      tab: CHILD,
    });
  });

  it('an unknown tab still opens the dashboard, on its current tab', () => {
    expect(parseCombinedHash('#dashboard/nope', TABS)).toEqual({ view: 'dashboard' });
  });

  it('reads #report and #report/<anchor>, anchors with slashes kept whole', () => {
    expect(parseCombinedHash('#report', TABS)).toEqual({ view: 'report' });
    expect(parseCombinedHash('#report/tab-overview', TABS)).toEqual({
      view: 'report',
      anchor: 'tab-overview',
    });
    expect(parseCombinedHash('#report/a/b', TABS)).toEqual({ view: 'report', anchor: 'a/b' });
  });

  it("leaves the report's own anchors (and no hash) to the report", () => {
    expect(parseCombinedHash('', TABS)).toBeNull();
    expect(parseCombinedHash('#', TABS)).toBeNull();
    expect(parseCombinedHash('#tab-overview', TABS)).toBeNull();
    expect(parseCombinedHash('#dashboards', TABS)).toBeNull();
  });

  it('formats what it parses', () => {
    for (const route of [
      { view: 'dashboard' as const },
      { view: 'dashboard' as const, tab: CHILD },
      { view: 'report' as const },
      { view: 'report' as const, anchor: 'tab-species-islands' },
    ]) {
      expect(parseCombinedHash(formatCombinedHash(route), TABS)).toEqual(route);
    }
  });

  it('resolves tabs by id first, then by title', () => {
    expect(resolveTab(MAIN, TABS)).toBe(MAIN);
    expect(resolveTab('OVERVIEW', TABS)).toBe(MAIN);
    expect(resolveTab('', TABS)).toBeNull();
    expect(tabSlug('Données & QC — été')).toBe('donnees-qc-ete');
  });
});

describe('landing view', () => {
  it('a link wins, then the reader, then the export', () => {
    expect(landingView({ view: 'dashboard' }, 'report', 'report')).toBe('dashboard');
    expect(landingView({ view: 'report', anchor: 'x' }, 'dashboard', 'dashboard')).toBe('report');
    expect(landingView(null, 'dashboard', 'report')).toBe('dashboard');
    expect(landingView(null, null, 'dashboard')).toBe('dashboard');
    expect(landingView(null, 'garbage', 'report')).toBe('report');
    expect(landingView(null, undefined)).toBe('report');
  });

  it('remembers per export, not per dashboard', () => {
    expect(viewMemoryKey('d1', '2026-11-16T14:53')).not.toBe(viewMemoryKey('d1', '2026-11-17'));
    expect(viewMemoryKey('d1', null)).toBe('depictio-combined-view:d1:');
  });
});

describe('stylesheet scoping', () => {
  const ROOT = '.depictio-report-root';

  it('moves document-level selectors onto the root', () => {
    expect(scopeSelector(':root', ROOT)).toBe(ROOT);
    expect(scopeSelector(":root[data-mantine-color-scheme='dark']", ROOT)).toBe(
      `${ROOT}[data-mantine-color-scheme='dark']`,
    );
    expect(scopeSelector('body', ROOT)).toBe(ROOT);
    expect(scopeSelector('html .x', ROOT)).toBe(`${ROOT} .x`);
  });

  it('prefixes element, universal and pseudo-element heads', () => {
    expect(scopeSelector('a', ROOT)).toBe(`${ROOT} a`);
    expect(scopeSelector('*', ROOT)).toBe(`${ROOT} *`);
    expect(scopeSelector('::before', ROOT)).toBe(`${ROOT} ::before`);
    expect(scopeSelector('input:focus', ROOT)).toBe(`${ROOT} input:focus`);
  });

  it("leaves the runtime's own selectors alone", () => {
    for (const s of ['.mantine-Button-root', '#x', '[data-x]', ':where(.a)', '.a > b']) {
      expect(scopeSelector(s, ROOT)).toBe(s);
    }
    expect(scopeSelector('bodyish', ROOT)).toBe(`${ROOT} bodyish`);
  });

  it('splits selector lists on top-level commas only', () => {
    expect(splitSelectorList('a, :is(b, c), [x="1,2"], d')).toEqual([
      'a',
      ':is(b, c)',
      '[x="1,2"]',
      'd',
    ]);
    expect(splitSelectorList("[title='a\\'b,c'], e")).toEqual(["[title='a\\'b,c']", 'e']);
  });

  it('scopes a whole list and drops duplicates', () => {
    expect(scopeSelectorList('html, body', ROOT)).toBe(ROOT);
    expect(scopeSelectorList('*, ::before, ::after', ROOT)).toBe(
      `${ROOT} *, ${ROOT} ::before, ${ROOT} ::after`,
    );
  });
});
