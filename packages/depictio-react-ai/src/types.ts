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

export interface SuggestFiguresRequest {
  data_collection_id: string;
  /** How many suggestions to ask for (server clamps to 1..8). */
  n?: number;
}

/** One Plotly Express configuration proposed by `/ai/suggest-figures`.
 *  `dict_kwargs` is already in the builder's figure grammar, so a picked
 *  suggestion drops straight into the create flow. `code` is display-only
 *  Python synthesized server-side — never executed client-side. */
export interface PlotSuggestion {
  visu_type: string;
  dict_kwargs: Record<string, unknown>;
  title: string;
  explanation: string;
  code: string;
}

export interface SuggestFiguresResponse {
  suggestions: PlotSuggestion[];
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

export interface ThresholdSpec {
  column: string;
  kind: 'quantile';
  q: number;
  op: '>=' | '>' | '<=' | '<';
}

/** LLM-proposed filter, pre-resolution. Servers resolve these; clients
 *  should only ever apply `ResolvedFilter`s. */
export interface FilterProposal {
  kind: 'set_widget' | 'filter_expr' | 'threshold';
  component_id?: string | null;
  value?: unknown;
  filter_expr?: string | null;
  threshold?: ThresholdSpec | null;
  reason?: string;
}

/** Server-validated filter, safe to apply.
 *  - `set_widget`: set the interactive component's value.
 *  - `filter_expr`: inject as InteractiveFilter{source:'ai_prompt'}. */
export interface ResolvedFilter {
  kind: 'set_widget' | 'filter_expr';
  component_id?: string | null;
  value?: unknown;
  filter_expr?: string | null;
  dc_id?: string | null;
  description: string;
}

export interface DashboardActions {
  filters: FilterAction[];
  figure_mutations: FigureMutation[];
  filter_proposals?: FilterProposal[];
}

export interface AnalysisResult {
  answer: string;
  steps: ExecutionStep[];
  actions: DashboardActions;
  resolved_filters?: ResolvedFilter[];
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
  /** Active InteractiveFilter list — threshold quantiles are computed on
   *  the filtered rows the user currently sees. */
  filters?: unknown[];
}

export interface ResolveFiltersRequest {
  dashboard_id: string;
  prompt: string;
  filters?: unknown[];
}

export interface ResolveFiltersResponse {
  applied: ResolvedFilter[];
  explanation: string;
  warnings: string[];
}

// ---------- Section summaries ----------

export interface SummaryComponentPayload {
  id: string;
  type: string;
  title?: string;
  /** The rendered payload the user sees: card value, trimmed Plotly
   *  {data, layout}, table rows. The server trims again before prompting. */
  digest?: unknown;
}

export interface SummarizeSectionRequest {
  dashboard_id: string;
  section?: string | null;
  filters?: unknown[];
  components: SummaryComponentPayload[];
  force?: boolean;
}

export interface SummarizeSectionResponse {
  summary_md: string;
  generated_at: string;
  model: string;
  context_hash: string;
  cached: boolean;
}

export interface SummaryEntry {
  section: string | null;
  summary_md: string;
  generated_at: string;
  model: string;
  context_hash: string;
}

export interface SummariesResponse {
  summaries: SummaryEntry[];
}
