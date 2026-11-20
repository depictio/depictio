import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { newOutputSlugClash } from '../state/useStudioStore';
import type { RenderSpec } from '../types';

/** Fresh module instance, so the persist middleware rehydrates from whatever is
 *  in localStorage at import time. */
async function loadStore() {
  vi.resetModules();
  const m = await import('../state/useStudioStore');
  return m.useStudioStore;
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

const card = (id?: string): RenderSpec => ({
  uid: 'x',
  component: 'card',
  column: 'cov',
  aggregation: 'average',
  ...(id ? { id } : {}),
});

describe('newOutputSlugClash', () => {
  const target = {
    toolId: 'mosdepth',
    toolName: 'mosdepth',
    dir: 'depictio/catalog/mosdepth',
    existingOutputSlugs: ['coverage', 'summary'],
  };

  it('flags a slug that would overwrite an existing output file', () => {
    expect(newOutputSlugClash(target, 'coverage')).toBe(true);
  });

  it('allows a free slug, and is inert without a target or a slug', () => {
    expect(newOutputSlugClash(target, 'per_base')).toBe(false);
    expect(newOutputSlugClash(null, 'coverage')).toBe(false);
    expect(newOutputSlugClash(target, '')).toBe(false);
  });
});

describe('addRender id assignment', () => {
  it('gives every render a default id so `use: <tool>/<id>` works out of the box', async () => {
    const store = await loadStore();
    store.getState().addRender(card());
    expect(store.getState().renders[0].id).toBeTruthy();
  });

  it('dedupes against sibling renders', async () => {
    const store = await loadStore();
    store.getState().addRender(card());
    store.getState().addRender(card());
    const ids = store.getState().renders.map((r) => r.id);
    expect(new Set(ids).size).toBe(2);
  });

  it('respects an id the author typed', async () => {
    const store = await loadStore();
    store.getState().addRender(card('my_card'));
    expect(store.getState().renders[0].id).toBe('my_card');
  });
});

describe('draft persistence', () => {
  it('survives a reload, re-parsing the rows it deliberately did not store', async () => {
    const store = await loadStore();
    store.getState().setTool({ id: 'mytool', name: 'My Tool' });
    store.getState().setFixture({
      fileName: 'sample.csv',
      delimiter: ',',
      columns: [
        { name: 'gene', dtype: 'String' },
        { name: 'cov', dtype: 'Int64' },
      ],
      // parseFixture keeps cells as text (dtypes are inferred separately), and
      // that is what a rehydrated draft re-derives.
      rows: [{ gene: 'BRCA1', cov: '120' }],
      raw: 'gene,cov\nBRCA1,120\n',
    });
    store.getState().addRender(card());

    // Rows are the bulk of the state and are pure derived data.
    const stored = JSON.parse(localStorage.getItem('depictio-studio-draft')!);
    expect(stored.state.fixture.rows).toBeUndefined();

    const reloaded = await loadStore();
    expect(reloaded.getState().tool.id).toBe('mytool');
    expect(reloaded.getState().renders).toHaveLength(1);
    expect(reloaded.getState().fixture?.rows).toEqual([{ gene: 'BRCA1', cov: '120' }]);
  });

  it('keeps the columns of a fixture that has no raw text (parquet, append mode)', async () => {
    localStorage.setItem(
      'depictio-studio-draft',
      JSON.stringify({
        version: 1,
        state: {
          step: 2,
          tool: { id: 'multiqc', name: 'MultiQC', source: 'nf-core' },
          output: { slug: 'general_stats', path_glob: '' },
          fixture: {
            fileName: 'general_stats.parquet',
            delimiter: ',',
            columns: [{ name: 'sample', dtype: 'String' }],
            raw: '',
          },
          renders: [],
          existing: null,
          newOutputTarget: null,
          dismissedMatchId: null,
        },
      }),
    );
    const store = await loadStore();
    expect(store.getState().fixture?.columns).toEqual([{ name: 'sample', dtype: 'String' }]);
    expect(store.getState().fixture?.rows).toEqual([]);
  });

  it('does not break the session when localStorage refuses the write', async () => {
    const store = await loadStore();
    const setItem = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new DOMException('quota', 'QuotaExceededError');
      });
    expect(() => store.getState().setTool({ id: 'big' })).not.toThrow();
    expect(store.getState().tool.id).toBe('big');
    setItem.mockRestore();
  });

  it('reset clears the draft', async () => {
    const store = await loadStore();
    store.getState().setTool({ id: 'mytool', name: 'My Tool' });
    store.getState().reset();
    const reloaded = await loadStore();
    expect(reloaded.getState().tool.id).toBe('');
    expect(reloaded.getState().renders).toEqual([]);
  });
});

describe('review fixes', () => {
  const fx = (raw: string) => ({ fileName: 'f.csv', delimiter: ',' as const, columns: [{ name: 'a', dtype: 'String' as const }], rows: [{ a: 'x' }], raw });

  it('default render ids avoid the sibling outputs’ ids too', async () => {
    const store = await loadStore();
    store.getState().addRender(card());
    const first = store.getState().renders[0].id;
    store.getState().addOutput();
    store.getState().addRender(card());
    expect(store.getState().renders[0].id).not.toBe(first);
  });

  it('uids stay unique across a reload', async () => {
    let store = await loadStore();
    const { nextUid } = await import('../state/useStudioStore');
    store.getState().addRender({ ...card(), uid: nextUid() });
    const before = store.getState().renders[0].uid;
    store = await loadStore();
    const fresh = (await import('../state/useStudioStore')).nextUid;
    store.getState().addRender({ ...card(), uid: fresh() });
    const uids = store.getState().renders.map((r) => r.uid);
    expect(uids[0]).toBe(before);
    expect(new Set(uids).size).toBe(2);
  });

  it('setFixtureAt writes into the output that asked, by index and slug', async () => {
    const store = await loadStore();
    store.getState().setOutput({ slug: 'a' });
    store.getState().addOutput();
    store.getState().setOutput({ slug: 'b' });
    // Active is "b" (index 1); a run that started on "a" lands on "a".
    expect(store.getState().setFixtureAt(0, 'a', fx('a\nx\n'))).toBe(true);
    expect(store.getState().fixture).toBeNull();
    expect(store.getState().siblings[0].fixture?.raw).toBe('a\nx\n');
    // A renamed or removed output is not written into.
    expect(store.getState().setFixtureAt(0, 'renamed', fx('z'))).toBe(false);
    expect(store.getState().setFixtureAt(5, 'a', fx('z'))).toBe(false);
    expect(store.getState().setFixtureAt(1, 'b', fx('b\ny\n'))).toBe(true);
    expect(store.getState().fixture?.raw).toBe('b\ny\n');
  });

  it('never persists raw recipe samples', async () => {
    const store = await loadStore();
    store.getState().setOutput({ slug: 'a', recipe: { code: 'X', inputs: [{ fileName: 'r.txt', text: 'RAW-SAMPLE' }] } });
    store.getState().addOutput();
    expect(localStorage.getItem('depictio-studio-draft')).not.toContain('RAW-SAMPLE');
  });

  it('the quota fallback strips every output’s fixture text, not only the active one', async () => {
    const store = await loadStore();
    store.getState().setFixture(fx('SIBLING-RAW'));
    store.getState().addOutput();
    store.getState().setFixture(fx('ACTIVE-RAW'));
    const real = Storage.prototype.setItem;
    const writes: string[] = [];
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, k: string, v: string) {
      if (v.includes('-RAW')) throw new DOMException('quota', 'QuotaExceededError');
      writes.push(v);
      return real.call(this, k, v);
    });
    store.getState().setTool({ id: 'big' });
    spy.mockRestore();
    const last = writes[writes.length - 1];
    expect(last).not.toContain('SIBLING-RAW');
    expect(last).not.toContain('ACTIVE-RAW');
  });
});

describe('#draft= link backup', () => {
  it('keeps the draft a link replaced, and restores it', async () => {
    vi.resetModules();
    const { useStudioStore } = await import('../state/useStudioStore');
    const backup = await import('../state/draftBackup');
    const { DRAFT_FORMAT } = await import('../catalog/draft');
    useStudioStore.getState().setTool({ id: 'mine', name: 'Mine' });
    useStudioStore.getState().addRender(card());
    expect(backup.backupCurrentDraft()).toBe(true);
    useStudioStore.getState().loadDraft({ format: DRAFT_FORMAT, tool: { id: 'theirs', name: 'T', source: 'nf-core' }, output: { slug: 'o', path_glob: '' }, renders: [] });
    expect(useStudioStore.getState().tool.id).toBe('theirs');
    expect(backup.useDraftBackup.getState()).toMatchObject({ available: true, toolId: 'mine' });
    expect(localStorage.getItem(backup.BACKUP_KEY)).toContain('mine');
    expect(backup.restoreDraftBackup()).toBe(true);
    expect(useStudioStore.getState().tool.id).toBe('mine');
    expect(useStudioStore.getState().renders).toHaveLength(1);
    expect(localStorage.getItem(backup.BACKUP_KEY)).toBeNull();
    expect(backup.useDraftBackup.getState().available).toBe(false);
  });

  it('backs up nothing when the draft is empty', async () => {
    vi.resetModules();
    const backup = await import('../state/draftBackup');
    expect(backup.backupCurrentDraft()).toBe(false);
    expect(localStorage.getItem(backup.BACKUP_KEY)).toBeNull();
  });
});
