/**
 * Wire types for the FastAPI /ai endpoints. Mirror the Pydantic schemas
 * in depictio/api/v1/endpoints/ai_endpoints/schemas.py — keep the two
 * in sync when adding fields.
 */

export type ComponentType =
  | 'figure'
  | 'card'
  | 'interactive'
  | 'table'
  | 'image'
  | 'multiqc'
  | 'map';

export interface ComponentFromPromptRequest {
  data_collection_id: string;
  prompt: string;
  component_type: ComponentType;
  /** Set in edit-mode to ask the LLM to revise an existing component
   *  rather than build one from scratch. Pass the current
   *  `StoredMetadata` dict. */
  current?: Record<string, unknown> | null;
}

export interface ComponentFromPromptResponse {
  component_type: ComponentType;
  /** YAML the LLM produced (canonicalized — re-dumped from the
   *  validated dict). Display-only, used for "show your work". */
  yaml: string;
  /** Validated component dict ready to drop into the builder store's
   *  `config` field. Field names match the lite-model / StoredMetadata
   *  shape, so no translation layer is needed in the React host. */
  parsed: Record<string, unknown>;
  explanation: string;
  validation_attempts: number;
}

export interface ExecutionStep {
  thought: string;
  code: string;
  output: string;
  status: 'success' | 'error' | 'warning' | 'running';
}

export interface FilterAction {
  component_id: string;
  value: unknown;
  reason?: string;
}

export interface FigureMutation {
  component_id: string;
  dict_kwargs_patch: Record<string, unknown>;
  reason?: string;
}

export interface DashboardActions {
  filters: FilterAction[];
  figure_mutations: FigureMutation[];
}

export interface AnalysisResult {
  answer: string;
  steps: ExecutionStep[];
  actions: DashboardActions;
}

/** SSE event names emitted by /ai/analyze, in order:
 *    status* → step* → answer → actions → result → done
 *  `error` may interrupt the stream at any point and is followed by `done`. */
export type AIStreamEventType =
  | 'status'
  | 'step'
  | 'answer'
  | 'actions'
  | 'result'
  | 'error'
  | 'done';

export interface AIStreamEvent {
  type: AIStreamEventType;
  data: Record<string, unknown>;
}

export interface AnalyzeRequest {
  dashboard_id: string;
  prompt: string;
  selected_component_id?: string;
}
