import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { RenderSpec } from '../types';

async function loadStore() {
  vi.resetModules();
  const m = await import('../state/useStudioStore');
  return m;
}
beforeEach(() => localStorage.clear());

const card = (uid: string): RenderSpec => ({ uid, component: 'card', column: 'v', aggregation: 'average' });

describe('multiple outputs', () => {
  it('adds, switches and removes outputs while every step keeps editing the active one', async () => {
    const { useStudioStore, allOutputs } = await loadStore();
    const st = () => useStudioStore.getState();
    st().setOutput({ slug: 'a', path_glob: '*.a' });
    st().addRender(card('r1'));
    st().addOutput();
    expect(st().step).toBe(0);
    expect(st().output.slug).toBe('');
    st().setOutput({ slug: 'b', path_glob: '*.b' });
    st().addRender(card('r2'));
    expect(allOutputs(st()).map((o) => o.output.slug)).toEqual(['a', 'b']);

    st().switchOutput(0);
    expect(st().output.slug).toBe('a');
    expect(st().renders.map((r) => r.uid)).toEqual(['r1']);
    // Order is stable across switches.
    expect(allOutputs(st()).map((o) => o.output.slug)).toEqual(['a', 'b']);

    st().removeOutput(0);
    expect(allOutputs(st()).map((o) => o.output.slug)).toEqual(['b']);
    expect(st().output.slug).toBe('b');
    st().removeOutput(0); // the last one stays
    expect(allOutputs(st())).toHaveLength(1);
  });

  it('persists the parked outputs across a reload', async () => {
    let m = await loadStore();
    m.useStudioStore.getState().setOutput({ slug: 'a', path_glob: '*' });
    m.useStudioStore.getState().setFixture(m.useStudioStore.getState().fixture);
    m.useStudioStore.getState().addOutput();
    m.useStudioStore.getState().setOutput({ slug: 'b', path_glob: '*' });
    m = await loadStore();
    expect(m.allOutputs(m.useStudioStore.getState()).map((o) => o.output.slug)).toEqual(['a', 'b']);
    expect(m.useStudioStore.getState().output.slug).toBe('b');
  });

  it('loads a multi-output draft with the first output active', async () => {
    const { useStudioStore, allOutputs } = await loadStore();
    useStudioStore.getState().loadDraft({
      format: 'depictio-tool-studio/draft@1',
      tool: { id: 't', name: 'T', source: 'nf-core' },
      output: { slug: 'a', path_glob: '*' },
      renders: [],
      moreOutputs: [{ output: { slug: 'b', path_glob: '*' }, renders: [{ component: 'table' }] }],
    });
    expect(allOutputs(useStudioStore.getState()).map((o) => o.output.slug)).toEqual(['a', 'b']);
    expect(useStudioStore.getState().siblings[0].renders[0].uid).toBeTruthy();
  });
});
