/**
 * Declarative draft: the whole wizard state as one JSON document, plus the two
 * ways in that do not need a single click.
 *
 *   - `StudioDraft` (format `depictio-tool-studio/draft@1`) is what
 *     `window.toolStudio.getDraft()` returns and `load()` accepts, and what a
 *     `#draft=` link carries (gzip + base64url).
 *   - `draftFromCatalogFiles` reads the files the Studio itself exports
 *     (`module.yaml`, `<output>.yaml`, the fixture) — or any committed catalog
 *     entry — back into a draft, so an export round-trips and an existing
 *     entry can be edited rather than only appended to.
 *
 * Render `uid`s are runtime handles, not part of the format: they are dropped
 * on the way out and minted on the way in.
 */
import yaml from 'js-yaml';
import JSZip from 'jszip';
import type { OutputMeta, RenderSpec, Stage, ToolMeta } from '../types';
import { renderSpecFromManifest } from './fromManifestRender';
import type { ManifestRender } from './catalog';
import { stripOutputRuntime, stripRenderRuntime } from './trust';

export const DRAFT_FORMAT = 'depictio-tool-studio/draft@1';

type DraftRender = Omit<RenderSpec, 'uid'> & { uid?: string };

export interface StudioDraft {
  format: typeof DRAFT_FORMAT;
  tool: ToolMeta;
  output: OutputMeta;
  /** The fixture verbatim; omitted when none is loaded. */
  fixture?: { fileName: string; content: string };
  renders: DraftRender[];
  /** The tool's other outputs, in order after this one. */
  moreOutputs?: Array<{ output: OutputMeta; fixture?: { fileName: string; content: string }; renders: DraftRender[] }>;
  /** Set when the draft adds renders to an output already in the catalog
   *  (append mode): `renders` are the NEW ones, spliced into `yamlPath` on
   *  export. Loading it re-enters append mode from the catalog snapshot. */
  appendTo?: DraftAppendTarget;
}

export interface DraftAppendTarget {
  toolId: string;
  outputId: string;
  yamlPath: string;
}

export interface ImportResult {
  draft: StudioDraft;
  /** Things that did not come across, in words (unsupported renders, extra outputs). */
  notes: string[];
}

let importCounter = 0;
const mintUid = () => `i${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}${++importCounter}`;

type OutputState = {
  output: OutputMeta;
  fixture: { fileName: string; raw: string } | null;
  renders: RenderSpec[];
};

const cleanRenders = (rs: RenderSpec[]): DraftRender[] => rs.map((r) => stripRenderRuntime(r) as DraftRender);

const outPart = (o: OutputState) => ({
  // Raw recipe samples stay in the tab: they are the user's unreduced data and
  // can be large, and nothing downstream (export, CI) reads them.
  output: stripOutputRuntime(o.output),
  ...(o.fixture?.raw ? { fixture: { fileName: o.fixture.fileName, content: o.fixture.raw } } : {}),
  renders: cleanRenders(o.renders),
});

/** Strip runtime-only fields (uid, executed code-mode previews, trust flags,
 *  raw recipe samples). Outputs are written in order: the first is the
 *  draft's own, the rest `moreOutputs`. */
export function toDraft(state: OutputState & {
  tool: ToolMeta;
  siblings?: OutputState[];
  activeIndex?: number;
  existing?: { toolId: string; outputId: string; yamlPath: string } | null;
}): StudioDraft {
  const active: OutputState = { output: state.output, fixture: state.fixture, renders: state.renders };
  const sib = state.siblings ?? [];
  const i = Math.min(state.activeIndex ?? 0, sib.length);
  const [first, ...rest] = [...sib.slice(0, i), active, ...sib.slice(i)];
  return {
    format: DRAFT_FORMAT,
    tool: state.tool,
    ...outPart(first),
    ...(rest.length ? { moreOutputs: rest.map(outPart) } : {}),
    ...(state.existing
      ? { appendTo: { toolId: state.existing.toolId, outputId: state.existing.outputId, yamlPath: state.existing.yamlPath } }
      : {}),
  };
}

const isObj = (v: unknown): v is Record<string, unknown> => Boolean(v) && typeof v === 'object' && !Array.isArray(v);

function checkFixture(f: unknown, where: string): StudioDraft['fixture'] {
  if (f == null) return undefined;
  if (!isObj(f) || typeof f.fileName !== 'string' || !f.fileName || typeof f.content !== 'string')
    throw new Error(`${where} needs a fileName and a content string.`);
  return { fileName: f.fileName, content: f.content };
}

function checkRenders(rs: unknown, where: string): DraftRender[] {
  if (rs == null) return [];
  if (!Array.isArray(rs)) throw new Error(`${where} must be a list.`);
  return rs.map((r, i) => {
    if (!isObj(r)) throw new Error(`${where}[${i}] must be an object.`);
    if (typeof r.component !== 'string' || !r.component)
      throw new Error(`${where}[${i}].component must be a string (figure, card, table, interactive, advanced_viz).`);
    return { ...(r as DraftRender), uid: typeof r.uid === 'string' && r.uid ? r.uid : mintUid() };
  });
}

function checkOutput(o: unknown, where: string): OutputMeta {
  if (!isObj(o) || typeof o.slug !== 'string') throw new Error(`${where}.slug is required.`);
  if (o.recipe != null && (!isObj(o.recipe) || typeof o.recipe.code !== 'string'))
    throw new Error(`${where}.recipe needs a code string.`);
  return { ...(o as unknown as OutputMeta), path_glob: typeof o.path_glob === 'string' ? o.path_glob : '' };
}

/** Validate the envelope of an untrusted draft and give every render a uid. */
export function normalizeDraft(input: unknown): StudioDraft {
  if (!isObj(input)) throw new Error('A draft must be a JSON object.');
  const d = input as Partial<StudioDraft> & Record<string, unknown>;
  if (d.format !== DRAFT_FORMAT) throw new Error(`Unknown draft format "${String(d.format)}" (expected ${DRAFT_FORMAT}).`);
  if (!isObj(d.tool) || typeof d.tool.id !== 'string') throw new Error('draft.tool.id is required.');
  const output = checkOutput(d.output, 'draft.output');
  const fixture = checkFixture(d.fixture, 'draft.fixture');
  const renders = checkRenders(d.renders, 'draft.renders');
  if (d.moreOutputs != null && !Array.isArray(d.moreOutputs)) throw new Error('draft.moreOutputs must be a list.');
  const more = (d.moreOutputs ?? []).map((o, i) => {
    const where = `draft.moreOutputs[${i}]`;
    if (!isObj(o)) throw new Error(`${where} must be an object.`);
    const f = checkFixture(o.fixture, `${where}.fixture`);
    return {
      output: checkOutput(o.output, `${where}.output`),
      ...(f ? { fixture: f } : {}),
      renders: checkRenders(o.renders, `${where}.renders`),
    };
  });
  let appendTo: DraftAppendTarget | undefined;
  if (d.appendTo != null) {
    const a = d.appendTo as unknown;
    if (!isObj(a) || typeof a.toolId !== 'string' || typeof a.outputId !== 'string' || typeof a.yamlPath !== 'string')
      throw new Error('draft.appendTo needs toolId, outputId and yamlPath strings.');
    appendTo = { toolId: a.toolId, outputId: a.outputId, yamlPath: a.yamlPath };
  }
  return {
    format: DRAFT_FORMAT,
    tool: { ...(d.tool as ToolMeta), source: (d.tool.source as ToolMeta['source']) ?? 'nf-core', name: typeof d.tool.name === 'string' ? d.tool.name : '' },
    output,
    ...(fixture ? { fixture } : {}),
    renders,
    ...(more.length ? { moreOutputs: more } : {}),
    ...(appendTo ? { appendTo } : {}),
  };
}

const str = (v: unknown): string | undefined => (typeof v === 'string' && v.trim() ? v : undefined);
const strList = (v: unknown): string[] | undefined =>
  Array.isArray(v) && v.every((x) => typeof x === 'string') && v.length ? (v as string[]) : undefined;

/** A tool folder (path → text) → a draft for ONE of its outputs. */
export function draftFromCatalogFiles(files: Record<string, string>, outputSlug?: string): ImportResult {
  const notes: string[] = [];
  const base = (p: string) => p.split('/').pop() ?? p;
  const moduleEntry = Object.entries(files).find(([p]) => base(p) === 'module.yaml');
  if (!moduleEntry) throw new Error('No module.yaml found.');
  const mod = (yaml.load(moduleEntry[1]) ?? {}) as Record<string, unknown>;
  const toolId = str(mod.id) ?? '';
  const tool: ToolMeta = {
    id: toolId,
    name: str(mod.name) ?? toolId,
    source: 'nf-core',
    description: str(mod.description),
    homepage: str(mod.homepage),
    source_url: str(mod.source_url),
    nf_core_url: str(mod.nf_core_url),
    biotools_url: str(mod.biotools_url),
    version: str(mod.version),
    stage: str(mod.stage) as Stage | undefined,
    edam_topics: strList(mod.edam_topics),
  };
  for (const k of Object.keys(tool) as (keyof ToolMeta)[]) if (tool[k] === undefined) delete tool[k];

  const outputs = Object.entries(files)
    .filter(([p]) => /\.ya?ml$/.test(p) && base(p) !== 'module.yaml')
    .map(([p, text]) => ({ path: p, doc: (yaml.load(text) ?? {}) as Record<string, unknown> }))
    .filter((o) => typeof o.doc.id === 'string');
  if (!outputs.length) throw new Error('No output YAML (with an id) found next to module.yaml.');
  const slugOf = (id: string) => (id.startsWith(`${toolId}_`) ? id.slice(toolId.length + 1) : id);
  if (outputSlug && !outputs.some((o) => slugOf(o.doc.id as string) === outputSlug))
    throw new Error(`No output "${outputSlug}" in this folder.`);
  // The requested output (or the first) leads; the others follow in file order.
  const ordered = outputSlug
    ? [...outputs.filter((o) => slugOf(o.doc.id as string) === outputSlug), ...outputs.filter((o) => slugOf(o.doc.id as string) !== outputSlug)]
    : outputs;

  const readOutput = (o: Record<string, unknown>) => {
    const slug = slugOf(o.id as string);
    let recipe: OutputMeta['recipe'];
    if (typeof o.recipe === 'string' && o.recipe.trim()) {
      const ref = o.recipe.trim();
      const name = ref.split('/').pop()!;
      // A module-owned recipe sits next to the YAML (`<tool>/<name>.py`); a
      // pipeline-keyed one (`nf-core/<pipeline>/<name>.py`) lives elsewhere in
      // the catalog. Either way the reference is kept as written: rewriting it
      // to `<tool>/<slug>.py` would point CI at a file that does not exist.
      const moduleOwned = ref === `${toolId}/${name}`;
      const hit = moduleOwned ? Object.entries(files).find(([p]) => base(p) === name) : undefined;
      const keepRef = ref !== `${toolId}/${slug}.py` ? { ref } : {};
      if (hit) recipe = { code: hit[1], ...keepRef };
      else {
        recipe = { code: '', ref };
        notes.push(
          moduleOwned
            ? `${slug}: recipe ${ref} was not among the files; the reference is kept, add the .py to edit it.`
            : `${slug}: recipe ${ref} lives outside this tool's folder; the reference is kept as-is.`,
        );
      }
    }
    const find = (o.find ?? {}) as Record<string, unknown>;
    const columns =
      o.columns && typeof o.columns === 'object' && !Array.isArray(o.columns)
        ? Object.fromEntries(
            Object.entries(o.columns as Record<string, unknown>)
              .filter(([, v]) => typeof v === 'string')
              .map(([k, v]) => [k, v as string]),
          )
        : undefined;
    const output: OutputMeta = {
      slug,
      path_glob: str(find.path_glob) ?? '',
      path_glob_alt: strList(find.path_glob_alt),
      filename: str(find.filename),
      name: str(o.name),
      description: str(o.description),
      recipe,
      // recipe XOR columns (SCHEMA.md); a file carrying both keeps the recipe.
      columns: !recipe && columns && Object.keys(columns).length ? columns : undefined,
      stage: str(o.stage) as Stage | undefined,
      origin_tool: str(o.origin_tool),
      mode: str(o.mode),
      nf_core_url: str(o.nf_core_url),
      biotools_url: str(o.biotools_url),
      edam_operations: strList(o.edam_operations),
      edam_formats: strList(o.edam_formats),
    };
    for (const k of Object.keys(output) as (keyof OutputMeta)[]) if (output[k] === undefined) delete output[k];
    const renders: DraftRender[] = [];
    for (const [i, raw] of ((o.renders_as as ManifestRender[] | undefined) ?? []).entries()) {
      const spec = renderSpecFromManifest(raw, mintUid());
      if (spec) renders.push(spec);
      else notes.push(`${slug}: renders_as[${i}] (${String(raw?.component)}) cannot be edited in the Studio and was left out.`);
    }
    let fixture: StudioDraft['fixture'];
    const fixtureName = str(o.fixture);
    if (fixtureName) {
      const hit = Object.entries(files).find(([p]) => base(p) === fixtureName);
      if (hit) fixture = { fileName: fixtureName, content: hit[1] };
      else notes.push(`${slug}: fixture "${fixtureName}" was not among the files.`);
    }
    return { output, ...(fixture ? { fixture } : {}), renders };
  };

  const [first, ...rest] = ordered.map((o) => readOutput(o.doc));
  return {
    draft: {
      format: DRAFT_FORMAT,
      tool,
      ...first,
      ...(rest.length ? { moreOutputs: rest } : {}),
    },
    notes,
  };
}

/** Read a zip (as exported by the Studio, or a zipped tool folder) into files. */
export async function filesFromZip(data: Blob | ArrayBuffer | Uint8Array): Promise<Record<string, string>> {
  const zip = await JSZip.loadAsync(data);
  const out: Record<string, string> = {};
  await Promise.all(
    Object.values(zip.files)
      .filter((f) => !f.dir && /\.(ya?ml|csv|tsv|txt|tab|py|json)$/i.test(f.name))
      .map(async (f) => {
        out[f.name] = await f.async('string');
      }),
  );
  return out;
}

// ── URL encoding (#draft=…) ────────────────────────────────────────────────

const toB64Url = (bytes: Uint8Array) => {
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};
const fromB64Url = (s: string) => {
  const bin = atob(s.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
};

async function pipe(bytes: Uint8Array, stream: CompressionStream | DecompressionStream): Promise<Uint8Array> {
  const out = new Response(new Blob([bytes as Uint8Array<ArrayBuffer>]).stream().pipeThrough(stream));
  return new Uint8Array(await out.arrayBuffer());
}

/** Rows a shared link keeps of the fixture: links are for reproducing a state,
 *  and a browser URL tops out around a few hundred KB. */
export const LINK_FIXTURE_ROWS = 200;

const trimFixture = (f: { fileName: string; content: string }) => ({
  ...f,
  content: f.content.split('\n').slice(0, LINK_FIXTURE_ROWS + 1).join('\n'),
});

export async function encodeDraftForUrl(draft: StudioDraft): Promise<string> {
  // Every output's fixture is trimmed, and no raw recipe sample rides along
  // (toDraft already drops them; this guards a hand-built draft too).
  const slim: StudioDraft = {
    ...draft,
    output: stripOutputRuntime(draft.output),
    ...(draft.fixture ? { fixture: trimFixture(draft.fixture) } : {}),
    ...(draft.moreOutputs
      ? {
          moreOutputs: draft.moreOutputs.map((o) => ({
            ...o,
            output: stripOutputRuntime(o.output),
            ...(o.fixture ? { fixture: trimFixture(o.fixture) } : {}),
          })),
        }
      : {}),
  };
  const json = new TextEncoder().encode(JSON.stringify(slim));
  return toB64Url(await pipe(json, new CompressionStream('gzip')));
}

export async function decodeDraftFromUrl(token: string): Promise<StudioDraft> {
  const json = await pipe(fromB64Url(token), new DecompressionStream('gzip'));
  return normalizeDraft(JSON.parse(new TextDecoder().decode(json)));
}
