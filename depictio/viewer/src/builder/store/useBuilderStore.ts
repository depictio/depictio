/**
 * Builder store — single source of truth for the in-flight component builder
 * (create stepper or edit page). Mirrors what the Dash stepper holds across
 * its many `dcc.Store` slices, but flat and typed.
 *
 * Lives only while the create/edit page is mounted. `reset()` is called on
 * unmount so revisiting the page starts fresh.
 *
 * Persisted shape on commit() matches the canonical metadata schemas in
 * depictio/models/components/{card,figure,interactive,table,multiqc,image,map}.py.
 */
import { create } from 'zustand';
import { readEditorFilters } from 'depictio-react-core';
import type {
  InteractiveFilter,
  StoredMetadata,
  FigureVisualizationDefinition,
  FigureVisualizationSummary,
} from 'depictio-react-core';

export type ComponentType =
  | 'figure'
  | 'card'
  | 'interactive'
  | 'table'
  | 'multiqc'
  | 'image'
  | 'map'
  | 'text'
  | 'advanced_viz';

export type FigureMode = 'ui' | 'code';

export interface DataCollectionLite {
  _id: string;
  data_collection_tag?: string;
  config?: { type?: string; [k: string]: unknown };
  [k: string]: unknown;
}

export interface WorkflowLite {
  _id: string;
  name?: string;
  workflow_tag?: string;
  engine?: { name?: string } | string;
  data_collections?: DataCollectionLite[];
  [k: string]: unknown;
}

export interface ColumnSpec {
  name: string;
  type: string;
  specs?: Record<string, unknown>;
}

/** Which surface the Add-component page is showing. Named because the page's
 *  history entries carry it too. */
export type SourceMode = 'unset' | 'manual' | 'catalog' | 'ai';

/**
 * Step numbers of the create flow.
 *
 * Manual and catalog: 0 Type, 1 Data, 2 Design. Text binds to no data
 * collection and skips Data (0 then 2). The AI mode is prompt-first: 0
 * Describe (the prompt, with type and collection left to the assistant or
 * pinned), 1 Design.
 */
export function designStepFor(mode: SourceMode): number {
  return mode === 'ai' ? 1 : 2;
}
export function stepAfterType(t: ComponentType | null): number {
  return t === 'text' ? 2 : 1;
}

export interface AISource {
  /** Which assistant flow authored the component: a prompt on the Describe
   *  step (or the Design step's AI fill), or a picked typed suggestion. */
  flow: 'component-from-prompt' | 'suggest-components';
  prompt?: string;
}

/** How the AI answer's type and collection were decided (see
 *  RoutingInfo in depictio-react-ai). Transient: shown on the Design step,
 *  never persisted. */
export interface AIRouting {
  source: 'user' | 'single' | 'auto';
  reason?: string | null;
  dcTag: string | null;
  alternatives: { data_collection_id: string; data_collection_tag: string }[];
}

export interface BuilderState {
  // Mode + ids
  mode: 'create' | 'edit';
  dashboardId: string | null;
  componentId: string | null;
  step: number; // 0,1,2 in create mode; always 2 in edit

  // Step 1: workflow + DC
  wfId: string | null;
  dcId: string | null;
  projectId: string | null;
  dcConfigType: string | null; // for MultiQC routing
  cols: ColumnSpec[]; // resolved columns for the chosen DC

  // Step 2: component type
  componentType: ComponentType | null;

  // Step 3: per-type config bag (kept loosely typed; one builder writes one
  // shape, and `commit()` pulls only the relevant fields out).
  config: Record<string, unknown>;

  // Figure-specific (UI mode + Code mode interlinked)
  figureMode: FigureMode;
  visuType: string;
  dictKwargs: Record<string, unknown>;
  codeContent: string;
  // Cache of /figure/parameter-discovery responses by viz_type
  figureParamSpecs: Record<string, FigureVisualizationDefinition>;
  // Cached `/figure/visualizations` payload — fetched once on figure-builder mount
  figureVisualizationList: FigureVisualizationSummary[] | null;
  // Last figure successfully produced from Code mode Execute
  lastCodeFigure: { data: unknown[]; layout: Record<string, unknown> } | null;
  // Status alert state under the code editor
  codeStatus: { title: string; color: string; message: string };

  // Existing component snapshot (edit mode only)
  existing: StoredMetadata | null;

  // Active dashboard filters carried across the full-page navigation into the
  // builder (seeded from the editor's per-tab store on init — see
  // editorFilters.ts). Previews apply them so the design view shows the data
  // the component will actually render under the dashboard's current filters.
  dashboardFilters: InteractiveFilter[];
  // Preview-only toggle for the banner in StepDesign: a heavily filtered
  // preview can be legitimately empty, so authors can flip back to the full
  // dataset. Never persisted into the component metadata.
  applyDashboardFilters: boolean;

  // 'unset' = mode choice screen; 'manual' = stepper; 'catalog' = catalog
  // browser or pre-fill; 'ai' = the stepper with a Describe step before Design
  sourceMode: SourceMode;
  // Set true when the builder was initiated from a catalog suggestion. Steps
  // 0 and 1 are skipped; the design step shows a dismissable catalog banner.
  catalogMode: boolean;
  // When catalogMode, the tool+output that supplied the pre-fill (for the banner,
  // the "from catalog" flag, and the metadata inspector). `use` is the
  // `<tool>/<ref>` snippet the render maps to (advanced_viz), when applicable.
  catalogSource: {
    toolId?: string;
    toolName: string;
    outputId: string;
    description?: string;
    use?: string;
  } | null;
  // Set when the component was authored by the AI (Describe step or the
  // "Refine with AI" modal); persisted as `ai_source` provenance on the saved
  // metadata (mirrors catalog_source).
  aiSource: AISource | null;
  aiRouting: AIRouting | null;

  // UI status flags
  saving: boolean;
  saveError: string | null;
  // Set true once a live preview has rendered for component types that show
  // one (currently advanced_viz). Non-preview component types leave it at the
  // initial `true` so they aren't blocked from saving.
  previewReady: boolean;
}

export interface BuilderActions {
  init: (args: {
    mode: 'create' | 'edit';
    dashboardId: string;
    componentId: string;
  }) => void;
  setStep: (n: number) => void;
  setWorkflow: (
    wfId: string | null,
    projectId: string | null,
  ) => void;
  setDataCollection: (
    dcId: string | null,
    dcConfigType: string | null,
  ) => void;
  setCols: (cols: ColumnSpec[]) => void;
  setComponentType: (t: ComponentType | null) => void;
  patchConfig: (patch: Record<string, unknown>) => void;
  setFigureMode: (m: FigureMode) => void;
  setVisuType: (t: string) => void;
  patchDictKwargs: (patch: Record<string, unknown>) => void;
  setCodeContent: (s: string) => void;
  setFigureParamSpec: (vizType: string, spec: FigureVisualizationDefinition) => void;
  setFigureVisualizationList: (list: FigureVisualizationSummary[]) => void;
  setLastCodeFigure: (
    fig: { data: unknown[]; layout: Record<string, unknown> } | null,
  ) => void;
  setCodeStatus: (s: { title: string; color: string; message: string }) => void;
  setSourceMode: (mode: SourceMode) => void;
  initFromCatalog: (patch: {
    componentType: ComponentType;
    wfId: string;
    dcId: string;
    projectId: string;
    config: Record<string, unknown>;
    source: {
      toolId?: string;
      toolName: string;
      outputId: string;
      description?: string;
      use?: string;
    };
  }) => void;
  setAiSource: (source: AISource | null) => void;
  /** Seed the store from an AI answer: the resolved type and collection
   *  plus the routing verdict, keeping the visit (dashboard, filters). The
   *  config itself is applied through applyLiteComponent afterwards. */
  initFromAI: (patch: {
    componentType: ComponentType;
    wfId: string | null;
    dcId: string | null;
    projectId: string | null;
    dcConfigType: string | null;
    source: AISource;
    routing: AIRouting | null;
  }) => void;
  loadExisting: (m: StoredMetadata) => void;
  setApplyDashboardFilters: (b: boolean) => void;
  setSaving: (b: boolean) => void;
  setSaveError: (e: string | null) => void;
  setPreviewReady: (b: boolean) => void;
  reset: () => void;
}

const INITIAL: BuilderState = {
  mode: 'create',
  dashboardId: null,
  componentId: null,
  step: 0,
  wfId: null,
  dcId: null,
  projectId: null,
  dcConfigType: null,
  cols: [],
  componentType: null,
  config: {},
  figureMode: 'ui',
  visuType: 'scatter',
  dictKwargs: {},
  codeContent: '',
  figureParamSpecs: {},
  figureVisualizationList: null,
  lastCodeFigure: null,
  codeStatus: {
    title: 'Ready',
    color: 'blue',
    message:
      "Enter code and click 'Execute Code' to see preview on the left.",
  },
  existing: null,
  dashboardFilters: [],
  applyDashboardFilters: true,
  sourceMode: 'unset',
  catalogMode: false,
  catalogSource: null,
  aiSource: null,
  aiRouting: null,
  saving: false,
  saveError: null,
  previewReady: true,
};

export const useBuilderStore = create<BuilderState & BuilderActions>((set) => ({
  ...INITIAL,
  init: ({ mode, dashboardId, componentId }) =>
    set({
      ...INITIAL,
      mode,
      dashboardId,
      componentId,
      // Seeded here rather than by the pages so the INITIAL spread can never
      // clobber it — init() is the one entry point both pages share.
      dashboardFilters: readEditorFilters(dashboardId),
      step: mode === 'edit' ? 2 : 0,
    }),
  setStep: (n) => set({ step: n }),
  setWorkflow: (wfId, projectId) =>
    set((s) => ({
      wfId,
      projectId,
      // Changing workflow invalidates DC, columns, AND any per-type config
      // (column bindings reference column names that may not exist in the new
      // DC). Without resetting `config`, a viz_kind + column_mapping bound to
      // the old DC leaks into the new one and surfaces as
      // "Column X (role Y) is not in the DC" save errors.
      dcId: null,
      dcConfigType: null,
      cols: [],
      config: {},
      previewReady: s.componentType !== 'advanced_viz',
    })),
  setDataCollection: (dcId, dcConfigType) =>
    set((s) => ({
      dcId,
      dcConfigType,
      cols: [],
      // See setWorkflow comment — same reset applies here.
      config: {},
      previewReady: s.componentType !== 'advanced_viz',
    })),
  setCols: (cols) => set({ cols }),
  // Reset previewReady when switching to a type that demands a preview.
  // Other types keep it at true so they aren't blocked from saving.
  setComponentType: (t) =>
    set({ componentType: t, config: {}, previewReady: t !== 'advanced_viz' }),
  patchConfig: (patch) =>
    set((s) => ({ config: { ...s.config, ...patch } })),
  setFigureMode: (m) => set({ figureMode: m }),
  setVisuType: (t) => set({ visuType: t }),
  patchDictKwargs: (patch) =>
    set((s) => {
      const next: Record<string, unknown> = { ...s.dictKwargs, ...patch };
      // Strip empty values so persisted dict_kwargs matches Dash UI mode behaviour.
      for (const k of Object.keys(next)) {
        const v = next[k];
        if (v === '' || v == null) delete next[k];
      }
      return { dictKwargs: next };
    }),
  setCodeContent: (s) => set({ codeContent: s }),
  setFigureParamSpec: (vizType, spec) =>
    set((s) => ({
      figureParamSpecs: { ...s.figureParamSpecs, [vizType.toLowerCase()]: spec },
    })),
  setFigureVisualizationList: (list) => set({ figureVisualizationList: list }),
  setLastCodeFigure: (fig) => set({ lastCodeFigure: fig }),
  setCodeStatus: (status) => set({ codeStatus: status }),
  setSourceMode: (mode) => set({ sourceMode: mode }),
  initFromCatalog: ({ componentType, wfId, dcId, projectId, config, source }) => {
    // Figure has separate top-level store fields (visuType, figureMode, …) that
    // must be set alongside config — mirrors loadExisting's hydration.
    const cfg = config as Record<string, unknown>;
    const figureFields =
      componentType === 'figure'
        ? {
            figureMode: (cfg.mode as FigureMode) === 'code' ? 'code' as FigureMode : 'ui' as FigureMode,
            visuType: (cfg.visu_type as string) || 'scatter',
            dictKwargs: (cfg.dict_kwargs as Record<string, unknown>) || {},
            codeContent: (cfg.code_content as string) || '',
          }
        : {};
    set((s) => ({
      ...INITIAL,
      mode: 'create',
      dashboardId: s.dashboardId,
      componentId: s.componentId,
      // Catalog pre-fill replaces the config, not the visit — the dashboard's
      // filter carry-over must survive this INITIAL spread too.
      dashboardFilters: s.dashboardFilters,
      applyDashboardFilters: s.applyDashboardFilters,
      componentType,
      wfId,
      dcId,
      projectId,
      config,
      step: 2,
      sourceMode: 'catalog',
      catalogMode: true,
      catalogSource: source,
      previewReady: true,
      dcConfigType: 'table',
      ...figureFields,
    }));
  },
  setAiSource: (source) => set({ aiSource: source }),
  initFromAI: ({ componentType, wfId, dcId, projectId, dcConfigType, source, routing }) =>
    set((s) => ({
      ...INITIAL,
      mode: 'create',
      dashboardId: s.dashboardId,
      componentId: s.componentId,
      dashboardFilters: s.dashboardFilters,
      applyDashboardFilters: s.applyDashboardFilters,
      sourceMode: 'ai',
      step: designStepFor('ai'),
      componentType,
      wfId,
      dcId,
      projectId,
      dcConfigType,
      aiSource: source,
      aiRouting: routing,
      previewReady: componentType !== 'advanced_viz',
    })),
  loadExisting: (m) => {
    const ct = String(m.component_type) as ComponentType;
    // Legacy Map components saved before the rename used `lat`/`lon`/`color`/`size`.
    // Map them onto the canonical `*_column` names so the builder dropdowns
    // rehydrate; the next save writes the canonical keys.
    const rawMeta = m as Record<string, unknown>;
    const config: Record<string, unknown> = { ...rawMeta };
    if (ct === 'map') {
      if (config.lat_column === undefined && rawMeta.lat !== undefined) {
        config.lat_column = rawMeta.lat;
      }
      if (config.lon_column === undefined && rawMeta.lon !== undefined) {
        config.lon_column = rawMeta.lon;
      }
      if (config.color_column === undefined && rawMeta.color !== undefined) {
        config.color_column = rawMeta.color;
      }
      if (config.size_column === undefined && rawMeta.size !== undefined) {
        config.size_column = rawMeta.size;
      }
    }
    set({
      existing: m,
      mode: 'edit',
      componentType: ct,
      wfId: (m.wf_id as string) || null,
      dcId: (m.dc_id as string) || null,
      projectId: (m.project_id as string) || null,
      visuType: (m.visu_type as string) || 'scatter',
      dictKwargs: (m.dict_kwargs as Record<string, unknown>) || {},
      figureMode: ((m.mode as FigureMode) || 'ui') === 'code' ? 'code' : 'ui',
      codeContent: (m.code_content as string) || '',
      // The per-type config bag is just the raw metadata for edit prefilling —
      // each builder reads what it cares about.
      config,
    });
  },
  setApplyDashboardFilters: (b) => set({ applyDashboardFilters: b }),
  setSaving: (b) => set({ saving: b }),
  setSaveError: (e) => set({ saveError: e }),
  setPreviewReady: (b) => set({ previewReady: b }),
  reset: () => set(INITIAL),
}));
