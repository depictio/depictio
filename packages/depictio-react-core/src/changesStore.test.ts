import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  CHANGES_MODE_KEY,
  changesStorageKey,
  mergeLocalDismissed,
  readLocalMode,
  readLocalReader,
  resetChangesMemory,
  writeLocalBaseline,
  writeLocalMode,
} from './changesStore';
import { changeKey } from './changeMarks';
import type { ReaderBaseline } from './api';

class FakeStorage {
  data = new Map<string, string>();
  getItem(k: string) {
    return this.data.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.data.set(k, v);
  }
}

const baseline = (seenAt: string): ReaderBaseline => ({ seen_at: seenAt, version_id: 'v1' });

describe('changesStore', () => {
  let storage: FakeStorage;
  beforeEach(() => {
    storage = new FakeStorage();
    (globalThis as { localStorage?: unknown }).localStorage = storage;
    resetChangesMemory();
  });
  afterEach(() => {
    delete (globalThis as { localStorage?: unknown }).localStorage;
    resetChangesMemory();
  });

  it('keys one entry per family', () => {
    expect(changesStorageKey('abc')).toBe('depictio.changesSince.v1:abc');
    expect(changeKey('tab1', 'idx')).toBe('tab1:idx');
  });

  it('is empty on a first visit', () => {
    expect(readLocalReader('fam')).toEqual({ baseline: null, dismissed: {} });
  });

  it('round-trips a baseline under the family key', () => {
    writeLocalBaseline('fam', baseline('2026-11-01T10:00:00'));
    expect(storage.data.has('depictio.changesSince.v1:fam')).toBe(true);
    expect(readLocalReader('fam').baseline?.seen_at).toBe('2026-11-01T10:00:00');
    expect(readLocalReader('other').baseline).toBeNull();
  });

  it('merges dismissals and clears them when the baseline moves', () => {
    writeLocalBaseline('fam', baseline('2026-11-01T10:00:00'));
    mergeLocalDismissed('fam', { 't:a': { fingerprint: 'f1', data_token: null } });
    mergeLocalDismissed('fam', { 't:b': { fingerprint: null, data_token: 'd1' } });
    expect(Object.keys(readLocalReader('fam').dismissed).sort()).toEqual(['t:a', 't:b']);
    writeLocalBaseline('fam', baseline('2026-11-02T10:00:00'));
    expect(readLocalReader('fam').dismissed).toEqual({});
  });

  it('ignores a dismissal made without a baseline', () => {
    mergeLocalDismissed('fam', { 't:a': { fingerprint: 'f1', data_token: null } });
    expect(readLocalReader('fam')).toEqual({ baseline: null, dismissed: {} });
  });

  it('survives corrupt storage', () => {
    storage.setItem(changesStorageKey('fam'), '{not json');
    expect(readLocalReader('fam')).toEqual({ baseline: null, dismissed: {} });
    storage.setItem(changesStorageKey('fam'), JSON.stringify({ baseline: { nope: 1 } }));
    expect(readLocalReader('fam').baseline).toBeNull();
  });

  it('keeps the mode, and rejects an unknown one', () => {
    expect(readLocalMode()).toBeNull();
    writeLocalMode('previous_visit');
    expect(readLocalMode()).toBe('previous_visit');
    storage.setItem(CHANGES_MODE_KEY, 'bogus');
    expect(readLocalMode()).toBeNull();
  });

  it('works from memory when storage throws', () => {
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem() {
        throw new Error('blocked');
      },
      setItem() {
        throw new Error('blocked');
      },
    };
    writeLocalBaseline('fam', baseline('2026-11-01T10:00:00'));
    expect(readLocalReader('fam').baseline?.seen_at).toBe('2026-11-01T10:00:00');
    writeLocalMode('sticky');
    expect(readLocalMode()).toBe('sticky');
  });

  it('works with no storage at all', () => {
    delete (globalThis as { localStorage?: unknown }).localStorage;
    writeLocalBaseline('fam', baseline('2026-11-01T10:00:00'));
    expect(readLocalReader('fam').baseline).not.toBeNull();
  });
});
