import { create } from 'zustand';
import type { Dtype, ParsedFixture, RenderSpec, ToolMeta, OutputMeta } from '../types';
import type { ManifestOutput, ManifestRender, ManifestTool } from '../catalog/catalog';
import { parseFixture } from '../catalog/parseFixture';
import { defaultRenderId } from '../viz/renderMeta';

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

interface StudioState {
  step: number;
  tool: ToolMeta;
  output: OutputMeta;
  fixture: ParsedFixture | null;
  renders: RenderSpec[];
  existing: ExistingTarget | null;

  setStep: (step: number) => void;
  setTool: (patch: Partial<ToolMeta>) => void;
  setOutput: (patch: Partial<OutputMeta>) => void;
  setFixture: (fixture: ParsedFixture | null) => void;
  addRender: (render: RenderSpec) => void;
  updateRender: (uid: string, patch: Partial<RenderSpec>) => void;
  removeRender: (uid: string) => void;
  /** Enter "add a visualization to an existing tool" mode from the manifest. */
  startExisting: (tool: ManifestTool, output: ManifestOutput) => void;
  reset: () => void;
}

const emptyTool: ToolMeta = { id: '', name: '', source: 'nf-core' };
const emptyOutput: OutputMeta = { slug: '', path_glob: '' };

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

export const useStudioStore = create<StudioState>((set) => ({
  step: 0,
  tool: { ...emptyTool },
  output: { ...emptyOutput },
  fixture: null,
  renders: [],
  existing: null,

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
  startExisting: (tool, output) =>
    set(() => ({
      step: 2, // jump straight to Visualizations — identity & fixture come from the catalog
      tool: {
        id: tool.id,
        name: tool.name,
        source: 'nf-core',
        description: tool.description,
        homepage: tool.homepage ?? undefined,
        nf_core_url: tool.nf_core_url ?? undefined,
        biotools_url: tool.biotools_url ?? undefined,
      },
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
    })),
  reset: () =>
    set({
      step: 0,
      tool: { ...emptyTool },
      output: { ...emptyOutput },
      fixture: null,
      renders: [],
      existing: null,
    }),
}));
