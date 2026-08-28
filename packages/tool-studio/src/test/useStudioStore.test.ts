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
