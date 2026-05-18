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
import type {
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
  | 'text';

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

  // UI status flags
  saving: boolean;
  saveError: string | null;
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
  loadExisting: (m: StoredMetadata) => void;
  setSaving: (b: boolean) => void;
  setSaveError: (e: string | null) => void;
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
  saving: false,
  saveError: null,
};

export const useBuilderStore = create<BuilderState & BuilderActions>((set) => ({
  ...INITIAL,
  init: ({ mode, dashboardId, componentId }) =>
    set({
      ...INITIAL,
      mode,
      dashboardId,
      componentId,
      step: mode === 'edit' ? 2 : 0,
    }),
  setStep: (n) => set({ step: n }),
  setWorkflow: (wfId, projectId) =>
    set({
      wfId,
      projectId,
      // Changing workflow invalidates DC + columns.
      dcId: null,
      dcConfigType: null,
      cols: [],
    }),
  setDataCollection: (dcId, dcConfigType) =>
    set({ dcId, dcConfigType, cols: [] }),
  setCols: (cols) => set({ cols }),
  setComponentType: (t) => set({ componentType: t, config: {} }),
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
  setSaving: (b) => set({ saving: b }),
  setSaveError: (e) => set({ saveError: e }),
  reset: () => set(INITIAL),
}));
