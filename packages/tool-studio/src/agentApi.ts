/**
 * `window.toolStudio`: drive the Studio without clicking.
 *
 * Everything the wizard does is reachable here, on the same store the UI reads,
 * so an agent (or a Playwright test) can load a draft, check it and export it,
 * and a person watching sees the UI follow along. Documented in
 * `public/agent.md`, which the app also serves.
 *
 *   await toolStudio.ready
 *   toolStudio.load({ format: 'depictio-tool-studio/draft@1', tool, output, fixture, renders })
 *   await toolStudio.loadFiles({ 'mytool/module.yaml': '…', 'mytool/results.yaml': '…', 'mytool/results.csv': '…' })
 *   toolStudio.validate()      // → Diagnostic[] (code, severity, path, message, step)
 *   toolStudio.exportFiles()   // → { 'mytool/module.yaml': '…', … }
 *   await toolStudio.exportZip() // → Blob
 *   await toolStudio.link()    // → shareable URL with #draft=
 */
import JSZip from 'jszip';
import { allOutputs, useStudioStore } from './state/useStudioStore';
import {
  DRAFT_FORMAT,
  draftFromCatalogFiles,
  encodeDraftForUrl,
  filesFromZip,
  normalizeDraft,
  toDraft,
  type ImportResult,
  type StudioDraft,
} from './catalog/draft';
import { parseIndex, validateTool, sha256Hex, type Diagnostic } from './catalog/diagnostics';
import { appendRenders, generateEntry } from './catalog/yamlGen';
import { kindsMapFrom } from './catalog/kinds';
import type { CatalogManifest } from './catalog/catalog';
import type { KindsMap, RenderSpec } from './types';

export interface ToolStudioApi {
  version: string;
  draftFormat: typeof DRAFT_FORMAT;
  /** Resolves once kinds, catalog and indices are loaded (validate needs them). */
  ready: Promise<void>;
  getDraft(): StudioDraft;
  load(draft: StudioDraft | string, opts?: { step?: number }): StudioDraft;
  loadFiles(files: Record<string, string>, opts?: { output?: string }): ImportResult;
  loadZip(data: Blob | ArrayBuffer | Uint8Array, opts?: { output?: string }): Promise<ImportResult>;
  addRender(render: Omit<RenderSpec, 'uid'>): string;
  /** Outputs in order, with the active index (the one the steps edit). */
  outputs(): { slugs: string[]; active: number };
  addOutput(): void;
  switchOutput(index: number): void;
  removeRender(uid: string): void;
  validate(): Diagnostic[];
  validateAsync(): Promise<Diagnostic[]>;
  exportFiles(): Record<string, string>;
  exportZip(): Promise<Blob>;
  link(): Promise<string>;
  goTo(step: 0 | 1 | 2 | 3): void;
  reset(): void;
}

declare global {
  interface Window {
    toolStudio?: ToolStudioApi;
  }
}

let kinds: KindsMap = {};
let catalog: CatalogManifest | undefined;
let indices: { nfCoreModules?: Set<string>; edamTerms?: Set<string> } = {};

const base = import.meta.env.BASE_URL;
const getJson = (p: string) => fetch(`${base}${p}`).then((r) => r.json());
const getText = (p: string) => fetch(`${base}${p}`).then((r) => (r.ok ? r.text() : ''));

function currentDraft(): StudioDraft {
  return toDraft(useStudioStore.getState());
}

let catalogReady: Promise<CatalogManifest | undefined> | undefined;

/** Put a (normalized) draft in the store. A draft carrying `appendTo`
 *  re-enters append mode on that catalog output, which needs the catalog
 *  snapshot: when the output is not in it, the draft is refused rather than
 *  silently turned into a new tool. Renders from a draft are untrusted
 *  (catalog/trust.ts): code-mode figures wait for a click. */
export function applyDraft(draft: StudioDraft, opts?: { step?: number }): void {
  const a = draft.appendTo;
  if (!a) {
    useStudioStore.getState().loadDraft(draft, opts?.step);
    return;
  }
  if (!catalog)
    throw new Error(
      `This draft appends to ${a.outputId} (${a.yamlPath}), which needs the catalog snapshot; it is not loaded yet (await toolStudio.ready).`,
    );
  const tool = catalog.tools.find((t) => t.id === a.toolId);
  const output = tool?.outputs.find((o) => o.id === a.outputId);
  if (!tool || !output)
    throw new Error(
      `This draft appends to ${a.outputId} of ${a.toolId}, which is not in this build's catalog, so it cannot be re-entered in append mode.`,
    );
  if (output.yamlPath && a.yamlPath && output.yamlPath !== a.yamlPath)
    throw new Error(`This draft appends to ${a.yamlPath}, but ${a.outputId} now lives at ${output.yamlPath}.`);
  useStudioStore.getState().loadAppendDraft(tool, output, draft, opts?.step);
}

/** Test seam: the catalog snapshot applyDraft resolves `appendTo` against. */
export function __setAgentCatalogForTests(c: CatalogManifest | undefined): void {
  catalog = c;
}

/** Resolves with the catalog snapshot once it has loaded (or failed to). */
export function catalogLoaded(): Promise<CatalogManifest | undefined> {
  return catalogReady ?? Promise.resolve(catalog);
}

function diagnosticsFor(shas: Record<string, string> = {}): Diagnostic[] {
  const s = useStudioStore.getState();
  return validateTool(
    { tool: s.tool, kinds, catalog, indices, appendMode: Boolean(s.existing) },
    allOutputs(s).map((o) => ({ ...o, fixtureSha256: o.fixture?.raw ? shas[o.fixture.raw] : undefined })),
  );
}

/** Every file of the tool folder: module.yaml (unless the tool already
 *  exists) and, per output, its YAML and fixture. In append mode, the one file
 *  that changes: the output's YAML with the new renders spliced in, under its
 *  repo path (as the Export step downloads and the PR commits it). */
export function toolFiles(): Record<string, string> {
  const s = useStudioStore.getState();
  if (s.existing) {
    const { yamlPath, rawYaml } = s.existing;
    if (!yamlPath) throw new Error(`The output ${s.existing.outputId} has no YAML path in this catalog snapshot.`);
    const res = appendRenders(rawYaml, s.renders);
    if (res.problem) throw new Error(`${yamlPath}: ${res.problem}`);
    return { [yamlPath]: res.yaml };
  }
  const dir = s.tool.id;
  const out: Record<string, string> = {};
  for (const o of allOutputs(s)) {
    if (!o.fixture) throw new Error(`Output "${o.output.slug || '(unnamed)'}" has no fixture.`);
    const e = generateEntry({ tool: s.tool, output: o.output, fixtureFileName: o.fixture.fileName, fixtureContent: o.fixture.raw, renders: o.renders });
    if (!s.newOutputTarget && !out[`${dir}/module.yaml`]) out[`${dir}/module.yaml`] = e.moduleYaml;
    out[`${dir}/${e.outputYamlName}`] = e.outputYaml;
    out[`${dir}/${e.fixtureName}`] = e.fixtureContent;
    if (e.recipeFile) out[`${dir}/${e.recipeFile.name}`] = e.recipeFile.content;
  }
  return out;
}

export function installAgentApi(version: string): ToolStudioApi {
  const ready = Promise.all([
    getJson('kinds.json').then((k) => (kinds = kindsMapFrom(k.kinds))),
    (catalogReady = getJson('catalog.json')
      .then((c: CatalogManifest) => (catalog = c))
      .catch(() => undefined)),
    Promise.all([getText('nf_core_modules.txt'), getText('edam_terms.txt')]).then(
      ([n, e]) => (indices = { nfCoreModules: parseIndex(n), edamTerms: parseIndex(e) }),
    ),
  ]).then(() => undefined);

  const api: ToolStudioApi = {
    version,
    draftFormat: DRAFT_FORMAT,
    ready,
    getDraft: currentDraft,
    load(draft, opts) {
      const d = normalizeDraft(typeof draft === 'string' ? JSON.parse(draft) : draft);
      applyDraft(d, opts);
      return currentDraft();
    },
    loadFiles(f, opts) {
      const res = draftFromCatalogFiles(f, opts?.output);
      applyDraft(res.draft);
      return res;
    },
    async loadZip(data, opts) {
      return api.loadFiles(await filesFromZip(data), opts);
    },
    addRender(render) {
      const before = new Set(useStudioStore.getState().renders.map((r) => r.uid));
      useStudioStore.getState().addRender({ ...render, uid: `a${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}` } as RenderSpec);
      return useStudioStore.getState().renders.find((r) => !before.has(r.uid))!.uid;
    },
    removeRender: (uid) => useStudioStore.getState().removeRender(uid),
    outputs: () => {
      const s = useStudioStore.getState();
      return { slugs: allOutputs(s).map((o) => o.output.slug), active: s.activeIndex };
    },
    addOutput: () => useStudioStore.getState().addOutput(),
    switchOutput: (i) => useStudioStore.getState().switchOutput(i),
    validate: () => diagnosticsFor(),
    async validateAsync() {
      await ready;
      const shas: Record<string, string> = {};
      for (const o of allOutputs(useStudioStore.getState()))
        if (o.fixture?.raw) shas[o.fixture.raw] = await sha256Hex(o.fixture.raw);
      return diagnosticsFor(shas);
    },
    exportFiles: toolFiles,
    async exportZip() {
      const zip = new JSZip();
      for (const [p, text] of Object.entries(toolFiles())) zip.file(p, text);
      return zip.generateAsync({ type: 'blob' });
    },
    async link() {
      const token = await encodeDraftForUrl(currentDraft());
      return `${location.origin}${location.pathname}#draft=${token}`;
    },
    goTo(step) {
      useStudioStore.setState({ started: true, step });
    },
    reset: () => useStudioStore.getState().reset(),
  };
  window.toolStudio = api;
  return api;
}
