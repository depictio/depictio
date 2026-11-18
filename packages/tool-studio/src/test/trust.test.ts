/**
 * Code from outside the session is shown, not run (catalog/trust.ts): a
 * `#draft=` link, an imported folder or draft JSON, and `toolStudio.load*` all
 * go through `loadDraft`, which marks code-mode figures and recipes untrusted;
 * the api shim refuses to execute an untrusted figure; the flag survives a
 * reload and never leaves the app.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const runner = vi.hoisted(() => ({
  runCodeToFigure: vi.fn(async () => ({ figure: { data: [], layout: {} } })),
}));
vi.mock('../builder/pyodideRunner', () => runner);

import { DRAFT_FORMAT, draftFromCatalogFiles, normalizeDraft, toDraft, type StudioDraft } from '../catalog/draft';
import { needsConsent } from '../catalog/trust';
import { parseFixture } from '../catalog/parseFixture';
import { registerComponent, setActiveFixture, unregisterComponent } from '../api/fixtureRegistry';
import { renderFigure } from '../api/studioApi';
import { metadataFromRender } from '../viz/renderMetadata';
import type { FigureRender, RenderSpec } from '../types';

const CSV = 'gene,log2fc\nA,1\nB,2\n';
const CODE = 'import js\njs.window.__ran = True\nfig = px.bar(df, x="gene", y="log2fc")';

const draft = (): StudioDraft => ({
  format: DRAFT_FORMAT,
  tool: { id: 't', name: 'T', source: 'nf-core' },
  output: { slug: 'o', path_glob: '*.csv', recipe: { code: 'SOURCES = []', inputs: [{ fileName: 'raw.txt', text: 'x' }] } },
  fixture: { fileName: 'o.csv', content: CSV },
  renders: [{ component: 'figure', code: CODE } as StudioDraft['renders'][number], { component: 'table' }],
  moreOutputs: [
    { output: { slug: 'p', path_glob: '' }, renders: [{ component: 'figure', code: CODE } as StudioDraft['renders'][number]] },
  ],
});

async function loadStore() {
  vi.resetModules();
  return (await import('../state/useStudioStore')).useStudioStore;
}

beforeEach(() => {
  localStorage.clear();
  runner.runCodeToFigure.mockClear();
});

describe('loadDraft marks outside code untrusted', () => {
  it('flags code figures (all outputs) and recipes, not other renders', async () => {
    const store = await loadStore();
    store.getState().loadDraft(normalizeDraft(draft()));
    const s = store.getState();
    expect(needsConsent(s.renders[0])).toBe(true);
    expect(needsConsent(s.renders[1])).toBe(false);
    expect(needsConsent(s.siblings[0].renders[0])).toBe(true);
    expect(s.output.recipe?._untrusted).toBe(true);
  });

  it('ignores a sender that claims its code is trusted or ships a preview', async () => {
    const store = await loadStore();
    const d = draft();
    d.renders[0] = { component: 'figure', code: CODE, _untrusted: false, _previewFigure: { data: [], layout: {} } } as never;
    store.getState().loadDraft(normalizeDraft(d));
    const r = store.getState().renders[0] as FigureRender;
    expect(r._untrusted).toBe(true);
    expect(r._previewFigure).toBeUndefined();
  });

  it('marks an imported catalog folder too', async () => {
    const store = await loadStore();
    const { draft: d } = draftFromCatalogFiles({
      't/module.yaml': 'id: t\nname: T\n',
      't/o.yaml': `id: t_o\nfind: {path_glob: "*.csv"}\nfixture: o.csv\nrenders_as:\n  - component: figure\n    code: |\n      fig = 1\n`,
      't/o.csv': CSV,
    });
    store.getState().loadDraft(d);
    expect(needsConsent(store.getState().renders[0])).toBe(true);
  });

  it('a render authored in the session is trusted', async () => {
    const store = await loadStore();
    store.getState().addRender({ uid: 'u', component: 'figure', code: CODE });
    expect(needsConsent(store.getState().renders[0])).toBe(false);
  });

  it('stays untrusted across a reload, and is never exported', async () => {
    let store = await loadStore();
    store.getState().loadDraft(normalizeDraft(draft()));
    store = await loadStore(); // rehydrate from localStorage
    expect(needsConsent(store.getState().renders[0])).toBe(true);
    expect(store.getState().output.recipe?._untrusted).toBe(true);
    const out = JSON.stringify(toDraft(store.getState()));
    expect(out).not.toContain('_untrusted');
    expect(out).not.toContain('raw.txt'); // raw recipe samples stay in the tab
  });

  it('pressing "Run this code" (clearing the flag) trusts it', async () => {
    const store = await loadStore();
    store.getState().loadDraft(normalizeDraft(draft()));
    const uid = store.getState().renders[0].uid;
    store.getState().updateRender(uid, { _untrusted: undefined } as Partial<RenderSpec>);
    expect(needsConsent(store.getState().renders[0])).toBe(false);
  });
});

describe('the api shim never runs untrusted code', () => {
  const fixture = parseFixture('o.csv', CSV);

  it('refuses an untrusted code figure without touching Pyodide', async () => {
    setActiveFixture(fixture);
    const render: FigureRender = { uid: 'u', component: 'figure', code: CODE, _untrusted: true };
    registerComponent(metadataFromRender(render, 'fig-u', fixture));
    await expect(renderFigure('d', 'fig-u', [])).rejects.toThrow(/Run this code/);
    expect(runner.runCodeToFigure).not.toHaveBeenCalled();
    unregisterComponent('fig-u');
  });

  it('runs it once trusted', async () => {
    setActiveFixture(fixture);
    const render: FigureRender = { uid: 'u', component: 'figure', code: CODE };
    registerComponent(metadataFromRender(render, 'fig-t', fixture));
    await renderFigure('d', 'fig-t', []);
    expect(runner.runCodeToFigure).toHaveBeenCalledTimes(1);
    unregisterComponent('fig-t');
  });
});
