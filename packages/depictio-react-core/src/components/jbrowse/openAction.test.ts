import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { GenomeBrowserTarget } from './browserTarget';
import { openActionState, openInGenomeBrowser } from './openAction';
import { PENDING_LOCUS_EVENT, takePendingLocus } from './pendingLocus';

const target: GenomeBrowserTarget = {
  familyId: 'fam',
  dashboardId: 'tab-locus',
  index: 'jb1',
  href: '/dashboard/tab-locus',
  here: false,
};

describe('openActionState', () => {
  const base = { target, reader: true, selfIndex: 'manhattan', locus: 'chr1:1-9' };
  it('is enabled with a target, a genomic tile and a locus', () => {
    expect(openActionState(base)).toBe('enabled');
  });
  it('is disabled while no source gives a locus', () => {
    expect(openActionState({ ...base, locus: null })).toBe('disabled');
  });
  it('is hidden without a target, on a non genomic tile and on the browser itself', () => {
    expect(openActionState({ ...base, target: null })).toBe('hidden');
    expect(openActionState({ ...base, reader: false })).toBe('hidden');
    expect(openActionState({ ...base, selfIndex: 'jb1' })).toBe('hidden');
  });
});

describe('openInGenomeBrowser', () => {
  const events: Event[] = [];
  let store: Map<string, string>;
  beforeEach(() => {
    events.length = 0;
    store = new Map();
    (globalThis as any).window = {
      sessionStorage: {
        get length() {
          return store.size;
        },
        key: (i: number) => [...store.keys()][i] ?? null,
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
      },
      dispatchEvent: (e: Event) => events.push(e),
    };
  });
  afterEach(() => {
    delete (globalThis as any).window;
  });

  it('writes the locus for the family and navigates to another tab', () => {
    const visited: string[] = [];
    openInGenomeBrowser(target, 'chr8:1-9', { assign: (h) => visited.push(h) });
    expect(visited).toEqual(['/dashboard/tab-locus']);
    expect(events).toHaveLength(0);
    expect(takePendingLocus('fam', 'tab-locus', 'jb1')).toBe('chr8:1-9');
  });

  it('only sends the event when the browser is on this tab', () => {
    const visited: string[] = [];
    openInGenomeBrowser({ ...target, here: true }, 'chr8:1-9', { assign: (h) => visited.push(h) });
    expect(visited).toEqual([]);
    expect(events.map((e) => e.type)).toEqual([PENDING_LOCUS_EVENT]);
    expect(takePendingLocus('fam', 'tab-locus', 'jb1')).toBeNull();
  });
});
