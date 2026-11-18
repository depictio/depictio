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
}

export interface ImportResult {
  draft: StudioDraft;
  /** Things that did not come across, in words (unsupported renders, extra outputs). */
  notes: string[];
}

let importCounter = 0;
const mintUid = () => `i${Date.now().toString(36)}${++importCounter}`;

type OutputState = {
  output: OutputMeta;
  fixture: { fileName: string; raw: string } | null;
  renders: RenderSpec[];
};

const cleanRenders = (rs: RenderSpec[]): DraftRender[] =>
  rs.map((r) => {
    const { uid: _uid, ...rest } = r as RenderSpec & { _previewFigure?: unknown };
    delete (rest as { _previewFigure?: unknown })._previewFigure;
    return rest;
  });

const outPart = (o: OutputState) => ({
  output: o.output,
  ...(o.fixture?.raw ? { fixture: { fileName: o.fixture.fileName, content: o.fixture.raw } } : {}),
  renders: cleanRenders(o.renders),
});

/** Strip runtime-only fields (uid, executed code-mode previews). Outputs are
 *  written in order: the first is the draft's own, the rest `moreOutputs`. */
export function toDraft(state: OutputState & {
  tool: ToolMeta;
  siblings?: OutputState[];
  activeIndex?: number;
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
  };
}

/** Validate the envelope of an untrusted draft and give every render a uid. */
export function normalizeDraft(input: unknown): StudioDraft {
  if (!input || typeof input !== 'object') throw new Error('A draft must be a JSON object.');
  const d = input as Partial<StudioDraft>;
  if (d.format !== DRAFT_FORMAT) throw new Error(`Unknown draft format "${String(d.format)}" (expected ${DRAFT_FORMAT}).`);
  if (!d.tool || typeof d.tool !== 'object' || typeof d.tool.id !== 'string')
    throw new Error('draft.tool.id is required.');
  if (!d.output || typeof d.output !== 'object' || typeof d.output.slug !== 'string')
    throw new Error('draft.output.slug is required.');
  if (d.renders != null && !Array.isArray(d.renders)) throw new Error('draft.renders must be a list.');
  if (d.fixture && (typeof d.fixture.fileName !== 'string' || typeof d.fixture.content !== 'string'))
    throw new Error('draft.fixture needs fileName and content strings.');
  return {
    format: DRAFT_FORMAT,
    tool: { ...d.tool, source: d.tool.source ?? 'nf-core', name: d.tool.name ?? '' },
    output: { ...d.output, path_glob: d.output.path_glob ?? '' },
    ...(d.fixture ? { fixture: d.fixture } : {}),
    renders: (d.renders ?? []).map((r) => ({ ...r, uid: r.uid || mintUid() })),
    ...(Array.isArray(d.moreOutputs) && d.moreOutputs.length
      ? {
          moreOutputs: d.moreOutputs.map((o, i) => {
            if (!o?.output || typeof o.output.slug !== 'string') throw new Error(`draft.moreOutputs[${i}].output.slug is required.`);
            return {
              ...o,
              output: { ...o.output, path_glob: o.output.path_glob ?? '' },
              renders: (o.renders ?? []).map((r) => ({ ...r, uid: r.uid || mintUid() })),
            };
          }),
        }
      : {}),
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
    if (o.recipe) notes.push(`${slug}: uses a recipe (${String(o.recipe)}), which is not loaded.`);
    const find = (o.find ?? {}) as Record<string, unknown>;
    const output: OutputMeta = {
      slug,
      path_glob: str(find.path_glob) ?? '',
      path_glob_alt: strList(find.path_glob_alt),
      filename: str(find.filename),
      name: str(o.name),
      description: str(o.description),
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
      .filter((f) => !f.dir && /\.(ya?ml|csv|tsv|txt|tab)$/i.test(f.name))
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

export async function encodeDraftForUrl(draft: StudioDraft): Promise<string> {
  const slim: StudioDraft = draft.fixture
    ? {
        ...draft,
        fixture: {
          ...draft.fixture,
          content: draft.fixture.content.split('\n').slice(0, LINK_FIXTURE_ROWS + 1).join('\n'),
        },
      }
    : draft;
  const json = new TextEncoder().encode(JSON.stringify(slim));
  return toB64Url(await pipe(json, new CompressionStream('gzip')));
}

export async function decodeDraftFromUrl(token: string): Promise<StudioDraft> {
  const json = await pipe(fromB64Url(token), new DecompressionStream('gzip'));
  return normalizeDraft(JSON.parse(new TextDecoder().decode(json)));
}
