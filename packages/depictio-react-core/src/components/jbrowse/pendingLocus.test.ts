import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  PENDING_LOCUS_EVENT,
  PENDING_LOCUS_PREFIX,
  PENDING_LOCUS_TTL_MS,
  announcePendingLocus,
  pendingLocusFor,
  takePendingLocus,
  writePendingLocus,
} from './pendingLocus';

class MemoryStorage {
  private data = new Map<string, string>();
  get length() {
    return this.data.size;
  }
  key(i: number) {
    return [...this.data.keys()][i] ?? null;
  }
  getItem(k: string) {
    return this.data.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.data.set(k, v);
  }
  removeItem(k: string) {
    this.data.delete(k);
  }
}

const target = { dashboardId: 'tab-locus', index: 'jb1', locus: 'chr8:100-200' };

beforeEach(() => {
  (globalThis as any).window = { sessionStorage: new MemoryStorage() };
});
afterEach(() => {
  delete (globalThis as any).window;
});

describe('pending locus', () => {
  it('is read once, then gone', () => {
    writePendingLocus('fam', target, 1000);
    expect(takePendingLocus('fam', 'tab-locus', 'jb1', 2000)).toBe('chr8:100-200');
    expect(takePendingLocus('fam', 'tab-locus', 'jb1', 2000)).toBeNull();
  });

  it('expires after the TTL', () => {
    writePendingLocus('fam', target, 1000);
    expect(takePendingLocus('fam', 'tab-locus', 'jb1', 1000 + PENDING_LOCUS_TTL_MS + 1)).toBeNull();
    // and the stale entry was dropped, not left behind
    expect(takePendingLocus('fam', 'tab-locus', 'jb1', 1500)).toBeNull();
  });

  it('is scoped to the family', () => {
    writePendingLocus('fam', target, 1000);
    expect(takePendingLocus('other', 'tab-locus', 'jb1', 1500)).toBeNull();
    expect(takePendingLocus('fam', 'tab-locus', 'jb1', 1500)).toBe('chr8:100-200');
  });

  it('stays for the tile it was written for', () => {
    writePendingLocus('fam', target, 1000);
    expect(takePendingLocus('fam', 'tab-locus', 'jb2', 1500)).toBeNull();
    expect(takePendingLocus('fam', 'other-tab', 'jb1', 1500)).toBeNull();
    expect(takePendingLocus('fam', 'tab-locus', 'jb1', 1500)).toBe('chr8:100-200');
  });

  it('is found without a family id by dashboard and index', () => {
    writePendingLocus('fam', target, 1000);
    expect(takePendingLocus(null, 'tab-locus', 'jb2', 1500)).toBeNull();
    expect(takePendingLocus(null, 'tab-locus', 'jb1', 1500)).toBe('chr8:100-200');
  });

  it('ignores a corrupt entry and drops it', () => {
    const store = (globalThis as any).window.sessionStorage as MemoryStorage;
    store.setItem(`${PENDING_LOCUS_PREFIX}fam`, '{not json');
    expect(takePendingLocus('fam', 'tab-locus', 'jb1')).toBeNull();
    expect(store.getItem(`${PENDING_LOCUS_PREFIX}fam`)).toBeNull();
  });

  it('does nothing without storage', () => {
    delete (globalThis as any).window;
    expect(() => writePendingLocus('fam', target)).not.toThrow();
    expect(takePendingLocus('fam', 'tab-locus', 'jb1')).toBeNull();
  });
});

describe('pending locus event', () => {
  it('goes out on the window and matches only its tile', () => {
    const seen: Event[] = [];
    (globalThis as any).window.dispatchEvent = (e: Event) => seen.push(e);
    announcePendingLocus({ familyId: 'fam', ...target });
    expect(seen).toHaveLength(1);
    expect(seen[0].type).toBe(PENDING_LOCUS_EVENT);
    expect(pendingLocusFor(seen[0], 'tab-locus', 'jb1')?.locus).toBe('chr8:100-200');
    expect(pendingLocusFor(seen[0], 'tab-locus', 'jb2')).toBeNull();
    expect(pendingLocusFor(seen[0], 'elsewhere', 'jb1')).toBeNull();
  });
});
