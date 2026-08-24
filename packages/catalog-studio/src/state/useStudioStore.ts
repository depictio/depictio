import { create } from 'zustand';
import type { Dtype, ParsedFixture, RenderSpec, ToolMeta, OutputMeta } from '../types';
import type { ManifestOutput, ManifestRender, ManifestTool } from '../catalog/catalog';
import { parseFixture } from '../catalog/parseFixture';
import { defaultRenderId } from '../viz/renderMeta';
import { fetchUpstreamFile } from '../catalog/upstreamFile';
import { renderIdsIn } from '../catalog/github';

let uidCounter = 0;
export const nextUid = () => `r${++uidCounter}`;

/** Set when the wizard is adding renders to an already-published tool/output
 *  (rather than authoring a new tool). Drives read-only base renders + the
 *  "append to the existing YAML" export path. */
export interface ExistingTarget {
  toolId: string;
  toolName: string;
  outputId: string;
  outputSlug: string;
  /** Repo-relative path of the output's YAML — the append target. */
  yamlPath: string;
  /** The output YAML's current text (new renders are inserted under renders_as). */
  rawYaml: string;
  /** Existing renders, shown read-only so the author doesn't duplicate them. */
  baseRenders: ManifestRender[];
  baseRenderIds: string[];
}

/** Set when the wizard is authoring a *new* output for an already-published tool
 *  (reuse its identity, but write a fresh `<slug>.yaml` + fixture into the tool's
 *  folder rather than appending to an existing output or creating a new tool). */
export interface NewOutputTarget {
  toolId: string;
  toolName: string;
  /** Repo-relative tool folder the new `<slug>.yaml` + fixture land in. */
  dir: string;
  /** Existing output slugs — a new slug must not overwrite one of these files. */
  existingOutputSlugs: string[];
}

/** True when a new output's slug would overwrite an existing output's file.
 *  Shared by the nav gate (App) and the inline error (ToolForm) so they agree. */
export function newOutputSlugClash(target: NewOutputTarget | null, slug: string): boolean {
  return Boolean(slug && target?.existingOutputSlugs.includes(slug));
}

interface StudioState {
  step: number;
  tool: ToolMeta;
  output: OutputMeta;
  fixture: ParsedFixture | null;
  renders: RenderSpec[];
  existing: ExistingTarget | null;
  newOutputTarget: NewOutputTarget | null;
  /** Catalog tool id the author dismissed as "not my tool" — kept in the store
   *  (not ToolForm local state) so it survives the Tool step unmounting on
   *  Back/Next, instead of resurfacing the dismissed match. */
  dismissedMatchId: string | null;

  setStep: (step: number) => void;
  setTool: (patch: Partial<ToolMeta>) => void;
  setOutput: (patch: Partial<OutputMeta>) => void;
  setFixture: (fixture: ParsedFixture | null) => void;
  addRender: (render: RenderSpec) => void;
  updateRender: (uid: string, patch: Partial<RenderSpec>) => void;
  removeRender: (uid: string) => void;
  /** Enter "add a visualization to an existing tool" mode from the manifest. */
  startExisting: (tool: ManifestTool, output: ManifestOutput) => void;
  /** Enter "add a new output to an existing tool" mode from the manifest. */
  startNewOutput: (tool: ManifestTool) => void;
  /** Dismiss the recognized match for a catalog tool id (or clear with null). */
  setDismissedMatch: (toolId: string | null) => void;
  reset: () => void;
}

const emptyTool: ToolMeta = { id: '', name: '', source: 'nf-core' };
const emptyOutput: OutputMeta = { slug: '', path_glob: '' };

/** The editable tool identity for a catalog tool the wizard is extending
 *  (shared by the two "existing tool" entry actions). */
function identityFromManifest(tool: ManifestTool): ToolMeta {
  return {
    id: tool.id,
    name: tool.name,
    source: 'nf-core',
    description: tool.description,
    homepage: tool.homepage ?? undefined,
    nf_core_url: tool.nf_core_url ?? undefined,
    biotools_url: tool.biotools_url ?? undefined,
  };
}

/** Rebuild a ParsedFixture for an existing output: parse the embedded CSV/TSV
 *  sample when present, else synthesize a columns-only fixture (parquet outputs)
 *  so bindings still validate — previews are just empty without rows. */
function fixtureFromManifest(output: ManifestOutput): ParsedFixture | null {
  const fileName = output.fixture || `${output.slug}.csv`;
  if (output.fixtureContent) return parseFixture(fileName, output.fixtureContent);
  const cols = output.columns;
  if (cols && Object.keys(cols).length) {
    return {
      fileName,
      delimiter: ',',
      columns: Object.entries(cols).map(([name, dtype]) => ({ name, dtype: dtype as Dtype })),
      rows: [],
      raw: '',
    };
  }
  return null;
}

/** Replace the snapshot copy of the target output YAML with the live one.
 *  Best-effort: offline or rate-limited, the snapshot stays and the Export step
 *  says so. Only touches `existing` if the wizard is still on the same file. */
async function refreshExistingFromUpstream(
  set: (fn: (s: StudioState) => Partial<StudioState>) => void,
  get: () => StudioState,
  yamlPath: string,
): Promise<void> {
  let text: string;
  try {
    text = await fetchUpstreamFile(yamlPath);
  } catch {
    return;
  }
  const current = get().existing;
  if (!current || current.yamlPath !== yamlPath) return;
  set((s) => ({
    existing: s.existing
      ? {
          ...s.existing,
          rawYaml: text,
          // Ids are unique within a tool; dedupe against the live set so the
          // PR-time check doesn't reject a render the user already named.
          baseRenderIds: [...new Set([...s.existing.baseRenderIds, ...renderIdsIn(text)])],
        }
      : s.existing,
  }));
}

export const useStudioStore = create<StudioState>((set, get) => ({
  step: 0,
  tool: { ...emptyTool },
  output: { ...emptyOutput },
  fixture: null,
  renders: [],
  existing: null,
  newOutputTarget: null,
  dismissedMatchId: null,

  setStep: (step) => set({ step }),
  setTool: (patch) => set((s) => ({ tool: { ...s.tool, ...patch } })),
  setOutput: (patch) => set((s) => ({ output: { ...s.output, ...patch } })),
  setFixture: (fixture) => set({ fixture }),
  addRender: (render) =>
    set((s) => {
      // Give every render a default, editable, tool-unique id so it's reusable
      // via `use: <tool>/<id>` out of the box.
      let spec = render;
      if (!spec.id) {
        const base = defaultRenderId(render) || 'render';
        // Avoid colliding with sibling new renders AND the existing tool's
        // render ids (unique within a tool → the `use: <tool>/<id>` handle).
        const taken = new Set(
          [...s.renders.map((r) => r.id), ...(s.existing?.baseRenderIds ?? [])].filter(Boolean),
        );
        let id = base;
        for (let n = 2; taken.has(id); n++) id = `${base}_${n}`;
        spec = { ...render, id } as RenderSpec;
      }
      return { renders: [...s.renders, spec] };
    }),
  updateRender: (uid, patch) =>
    set((s) => ({
      renders: s.renders.map((r) => (r.uid === uid ? ({ ...r, ...patch } as RenderSpec) : r)),
    })),
  removeRender: (uid) => set((s) => ({ renders: s.renders.filter((r) => r.uid !== uid) })),
  startExisting: (tool, output) => {
    // The manifest is a build-time snapshot; pull the live file in the
    // background so new render ids are deduped against what is actually in the
    // catalog today, not against a copy that may be weeks old.
    if (output.yamlPath) void refreshExistingFromUpstream(set, get, output.yamlPath);
    return set(() => ({
      step: 2, // jump straight to Visualizations — identity & fixture come from the catalog
      tool: identityFromManifest(tool),
      output: {
        slug: output.slug,
        path_glob: output.path_glob ?? '',
        description: output.description,
      },
      fixture: fixtureFromManifest(output),
      renders: [],
      existing: {
        toolId: tool.id,
        toolName: tool.name,
        outputId: output.id,
        outputSlug: output.slug,
        yamlPath: output.yamlPath ?? '',
        rawYaml: output.rawYaml ?? '',
        baseRenders: output.renders_as ?? [],
        baseRenderIds: (output.renders_as ?? [])
          .map((r) => r.id)
          .filter((x): x is string => Boolean(x)),
      },
      newOutputTarget: null,
    }));
  },
  startNewOutput: (tool) =>
    set(() => ({
      // Stay on the Tool step: the new output's slug/path_glob is authored there,
      // then a fresh fixture + renders are added like a new tool from step 1 on.
      step: 0,
      tool: identityFromManifest(tool),
      output: { ...emptyOutput },
      fixture: null,
      renders: [],
      existing: null,
      newOutputTarget: {
        toolId: tool.id,
        toolName: tool.name,
        dir: tool.dir ?? `depictio/catalog/${tool.id}`,
        existingOutputSlugs: tool.outputs.map((o) => o.slug),
      },
    })),
  setDismissedMatch: (toolId) => set({ dismissedMatchId: toolId }),
  reset: () =>
    set({
      step: 0,
      tool: { ...emptyTool },
      output: { ...emptyOutput },
      fixture: null,
      renders: [],
      existing: null,
      newOutputTarget: null,
      dismissedMatchId: null,
    }),
}));
