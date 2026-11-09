import { afterEach, describe, expect, it } from 'vitest';

import {
  annotationsProblem,
  emptyAnnotations,
  mergeAccountAndLocal,
  MAX_LABEL_LENGTH,
  parseAnnotations,
  readBrowserAnnotations,
  setLabel,
  splitForAccount,
  writeBrowserAnnotations,
} from './sessionAnnotations';

const base = () => ({
  ...emptyAnnotations('dc1', 'sample'),
  columns: [{ id: 'c1', name: 'response', values: { S1: 'yes' } }],
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
  it('accepts version 1 and drops an active id that names nothing', () => {
    expect(parseAnnotations(base())).toEqual(base());
    expect(parseAnnotations({ ...base(), activeColumnId: 'zz' })?.activeColumnId).toBeNull();
  });
  it('refuses other shapes', () => {
    expect(parseAnnotations({ ...base(), version: 2 })).toBeNull();
    expect(parseAnnotations({ ...base(), columns: [{ id: 'c1', name: 'r', values: { a: 1 } }] })).toBeNull();
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
    writeBrowserAnnotations('d1', { ...base(), columns: [] });
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
      { id: 'c1', name: 'response', values: { S1: 'yes' } },
      { id: 'c2', name: 'cohort', values: { S1: 'early' }, local: true as const },
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

  it('drops a browser half made on another table or key', () => {
    const { account, local } = splitForAccount(both());
    expect(mergeAccountAndLocal(account, { ...local!, keyColumn: 'other' })).toEqual(account);
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
