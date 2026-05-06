/**
 * Wire types for the FastAPI /ai endpoints. These mirror the Pydantic
 * schemas in depictio/api/v1/endpoints/ai_endpoints/schemas.py — keep
 * the two in sync when adding fields.
 */

export type VisuType =
  | 'scatter'
  | 'bar'
  | 'line'
  | 'histogram'
  | 'box'
  | 'violin'
  | 'heatmap';

export interface PlotSuggestion {
  visu_type: VisuType;
  dict_kwargs: Record<string, unknown>;
  title: string;
  explanation: string;
}

export interface SuggestFiguresResponse {
  suggestions: PlotSuggestion[];
}

export interface FigureFromPromptResponse {
  suggestion: PlotSuggestion;
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

// Request bodies

export interface SuggestFiguresRequest {
  data_collection_id: string;
  n?: number;
}

export interface FigureFromPromptRequest {
  data_collection_id: string;
  prompt: string;
}

export interface AnalyzeRequest {
  dashboard_id: string;
  prompt: string;
  selected_component_id?: string;
}
