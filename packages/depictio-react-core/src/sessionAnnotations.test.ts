import { afterEach, describe, expect, it } from 'vitest';

import {
  annotationsProblem,
  emptyAnnotations,
  mergeAccountAndLocal,
  MAX_LABEL_LENGTH,
  parseAnnotations,
  readBrowserAnnotations,
  setLabel,
  copyName,
  parseSharedColumns,
  splitForAccount,
  withShared,
  writeBrowserAnnotations,
} from './sessionAnnotations';

const base = () => ({
  ...emptyAnnotations(),
  columns: [{ id: 'c1', name: 'response', dcId: 'dc1', keyColumn: 'sample', values: { S1: 'yes' } }],
  activeColumnId: 'c1',
});

class MemoryStorage {
  data = new Map<string, string>();
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

afterEach(() => {
  delete (globalThis as { localStorage?: unknown }).localStorage;
});

describe('parseAnnotations', () => {
  it('accepts version 2 and keeps an active id it cannot resolve (a shared column)', () => {
    expect(parseAnnotations(base())).toEqual(base());
    expect(parseAnnotations({ ...base(), activeColumnId: 'zz' })?.activeColumnId).toBe('zz');
  });
  it('refuses other shapes', () => {
    expect(parseAnnotations({ ...base(), version: 1 })).toBeNull();
    expect(parseAnnotations({ ...base(), columns: [{ id: 'c1', name: 'r', values: {} }] })).toBeNull();
    expect(parseAnnotations({ ...base(), columns: [{ id: 'c1', name: 'r', dcId: 'dc1', keyColumn: 'sample', values: { a: 1 } }] })).toBeNull();
    expect(parseAnnotations(null)).toBeNull();
  });
});

describe('setLabel', () => {
  it('trims, and a blank label removes the key', () => {
    let a = setLabel(base(), 'c1', 'S2', '  no ');
    expect(a.columns[0].values).toEqual({ S1: 'yes', S2: 'no' });
    a = setLabel(a, 'c1', 'S1', '   ');
    expect(a.columns[0].values).toEqual({ S2: 'no' });
  });
});

describe('annotationsProblem', () => {
  it('flags the caps the server enforces', () => {
    expect(annotationsProblem(base())).toBeNull();
    const long = setLabel(base(), 'c1', 'S1', 'x'.repeat(MAX_LABEL_LENGTH + 1));
    expect(annotationsProblem(long)).toMatch(/longer than 80/);
    const dup = { ...base(), columns: [base().columns[0], { ...base().columns[0], id: 'c2' }] };
    expect(annotationsProblem(dup)).toMatch(/Two annotations/);
  });
});

describe('browser storage', () => {
  it('reports when the browser keeps nothing', () => {
    expect(readBrowserAnnotations('d1')).toEqual({ ok: false });
    expect(writeBrowserAnnotations('d1', base())).toBe(false);
  });
  it('round-trips and removes an empty set', () => {
    const store = new MemoryStorage();
    (globalThis as { localStorage?: unknown }).localStorage = store;
    expect(writeBrowserAnnotations('d1', base())).toBe(true);
    expect(store.data.has('depictio.annotations.d1')).toBe(true);
    expect(readBrowserAnnotations('d1')).toEqual({ ok: true, value: base() });
    writeBrowserAnnotations('d1', { ...base(), columns: [], activeColumnId: null });
    expect(readBrowserAnnotations('d1')).toEqual({ ok: true, value: null });
  });
  it('treats unreadable stored text as nothing stored, not as a failure', () => {
    const store = new MemoryStorage();
    store.setItem('depictio.annotations.d1', '{"version":9}');
    (globalThis as { localStorage?: unknown }).localStorage = store;
    expect(readBrowserAnnotations('d1')).toEqual({ ok: true, value: null });
  });
});

describe('account and browser halves', () => {
  const both = () => ({
    ...base(),
    columns: [
      { id: 'c1', name: 'response', dcId: 'dc1', keyColumn: 'sample', values: { S1: 'yes' } },
      { id: 'c2', name: 'cohort', dcId: 'dc1', keyColumn: 'sample', values: { S1: 'early' }, local: true as const },
    ],
    activeColumnId: 'c2',
  });

  it('never puts a local annotation, or an active id naming one, in the account half', () => {
    const { account, local } = splitForAccount(both());
    expect(account).toEqual({ ...base(), activeColumnId: null });
    expect(JSON.stringify(account)).not.toContain('early');
    expect(local?.columns.map((c) => c.id)).toEqual(['c2']);
    expect(local?.activeColumnId).toBe('c2');
  });

  it('merges back to the same set', () => {
    const { account, local } = splitForAccount(both());
    expect(mergeAccountAndLocal(account, local)).toEqual(both());
  });

  it('keeps the account active id when the active one is shared', () => {
    const a = { ...both(), activeColumnId: 'c1' };
    const { account, local } = splitForAccount(a);
    expect(account?.activeColumnId).toBe('c1');
    expect(local?.activeColumnId).toBeNull();
    expect(mergeAccountAndLocal(account, local)?.activeColumnId).toBe('c1');
  });

  it('keeps browser labels of another table, drops a column whose name the account uses', () => {
    const { account, local } = splitForAccount(both());
    const other = { ...local!.columns[0], dcId: 'dc2', keyColumn: 'id' };
    expect(mergeAccountAndLocal(account, { ...local!, columns: [other] })?.columns[1]).toMatchObject({
      dcId: 'dc2',
      local: true,
    });
    const clash = { ...local!.columns[0], id: 'c9', name: 'response' };
    expect(mergeAccountAndLocal(account, { ...local!, columns: [clash] })?.columns).toHaveLength(1);
  });

  it('reads a browser half alone as local annotations', () => {
    const { local } = splitForAccount(both());
    expect(mergeAccountAndLocal(null, local)?.columns.every((c) => c.local)).toBe(true);
    expect(splitForAccount(null)).toEqual({ account: null, local: null });
  });

  it('round-trips the local flag through parsing', () => {
    expect(parseAnnotations(both())?.columns[1].local).toBe(true);
  });
});

describe('shared labels', () => {
  const shared = parseSharedColumns([
    { id: 's1', name: 'cohort', dcId: 'dc1', keyColumn: 'sample', values: { S1: 'A' } },
  ]);

  it('reads the server shape and marks the columns shared', () => {
    expect(shared).toHaveLength(1);
    expect(shared[0].shared).toBe(true);
    expect(parseSharedColumns('nope')).toEqual([]);
  });

  it('shows shared columns first, then the reader\'s own', () => {
    const view = withShared(base(), shared)!;
    expect(view.columns.map((c) => c.id)).toEqual(['s1', 'c1']);
    expect(view.activeColumnId).toBe('c1');
  });

  it('lets a reader compare by a shared column, and keeps that choice stored', () => {
    const personal = { ...base(), activeColumnId: 's1' };
    expect(withShared(personal, shared)!.activeColumnId).toBe('s1');
    // The choice survives a round trip through storage and the account split.
    expect(parseAnnotations(JSON.parse(JSON.stringify(personal)))!.activeColumnId).toBe('s1');
    expect(splitForAccount(personal).account!.activeColumnId).toBe('s1');
    const none = { ...emptyAnnotations(), activeColumnId: 's1' };
    expect(splitForAccount(none).account).toEqual(none);
  });

  it('drops an active id that names no column at all', () => {
    expect(withShared({ ...base(), activeColumnId: 'gone' }, shared)!.activeColumnId).toBeNull();
  });

  it('shows a personal column named like a shared one as "(mine)"', () => {
    const personal = { ...base(), columns: [{ ...base().columns[0], name: 'cohort' }] };
    expect(withShared(personal, shared)!.columns.map((c) => c.name)).toEqual(['cohort', 'cohort (mine)']);
  });

  it('is null when there is nothing to show', () => {
    expect(withShared(null, [])).toBeNull();
  });

  it('names a copy so that it clashes with nothing', () => {
    expect(copyName('cohort', ['cohort'])).toBe('cohort (copy)');
    expect(copyName('cohort', ['cohort', 'cohort (copy)'])).toBe('cohort (copy 2)');
  });
});
