/**
 * Wire types for the FastAPI /ai endpoints. Mirror the Pydantic schemas
 * in depictio/api/v1/endpoints/ai_endpoints/schemas.py — keep the two
 * in sync when adding fields.
 */

/** Same members and order as the viewer builder store's `ComponentType`
 *  (`depictio/viewer/src/builder/store/useBuilderStore.ts`), so the
 *  "Describe with AI" source mode covers every type the builder offers. */
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

/** Body of POST /ai/component-from-prompt.
 *
 *  `data_collection_id` is null only for `text`: a text component reads no
 *  data collection, so it gets the dashboard as context through
 *  `dashboard_id` instead (titles, sections, the other components). Every
 *  other type sends the DC it will render from. `useComponentFromPrompt`
 *  fills `dashboard_id` from its hook argument when a caller omits it. */
export interface ComponentFromPromptRequest {
  /** Component type to author. `null` asks the server to choose one from
   *  the prompt (routing); the response says which it picked. */
  component_type: ComponentType | null;
  /** Data collection to author against. `null` asks the server to choose
   *  among the dashboard's project collections, preferring those already
   *  on the dashboard. Always `null` for `text`, which needs no data. */
  data_collection_id: string | null;
  /** Owning dashboard. Required whenever type or collection is left to the
   *  server; filled in by `useComponentFromPrompt` when omitted. */
  dashboard_id?: string | null;
  prompt: string;
  /** Set in edit-mode to ask the LLM to revise an existing component
   *  rather than build one from scratch. Pass the current
   *  `StoredMetadata` dict. */
  current?: Record<string, unknown> | null;
}

/** A data collection the router considered. */
export interface RoutedCollection {
  data_collection_id: string;
  data_collection_tag: string;
  workflow_id: string;
  workflow_tag?: string | null;
}

/** How the type and collection of an answer were decided: pinned by the
 *  user, the only candidate, or chosen by the model from the prompt. */
export interface RoutingInfo {
  source: 'user' | 'single' | 'auto';
  reason?: string | null;
  alternatives: RoutedCollection[];
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
  /** Collection the component was authored against (null for text). */
  data_collection_id?: string | null;
  workflow_id?: string | null;
  routing?: RoutingInfo | null;
}

/** Body of POST /ai/suggest-components: "what would you add to this
 *  dashboard?". Both pins are optional; `null` (or absent) means Auto, and
 *  the server then mixes types and collections, dashboard collections first.
 *  `useSuggestComponents` fills `dashboard_id` from its hook argument. */
export interface SuggestComponentsRequest {
  dashboard_id: string;
  component_type?: ComponentType | null;
  data_collection_id?: string | null;
  /** How many suggestions to ask for (server clamps to 1..8, default 4). */
  n?: number;
}

/** One typed component proposed by `/ai/suggest-components`. `component` is
 *  the validated lite dict (the same shape `/ai/component-from-prompt`
 *  returns in `parsed`), so a picked suggestion drops straight into the
 *  builder through `applyLiteComponent`. `code` is display-only Python for
 *  figures, synthesized server-side and never executed client-side.
 *  `origin` says whether the model proposed it or the server ranked it
 *  deterministically from the collection's schema. */
export interface ComponentSuggestion {
  component_type: ComponentType;
  /** Null for text, which reads no collection. */
  data_collection_id: string | null;
  data_collection_tag: string | null;
  workflow_id: string | null;
  title: string;
  rationale: string;
  component: Record<string, unknown>;
  code?: string | null;
  origin: 'llm' | 'ranked';
}

export interface SuggestComponentsResponse {
  suggestions: ComponentSuggestion[];
  /** Things the server could not do, e.g. the LLM call failed and only the
   *  ranked suggestions are shown. */
  warnings: string[];
}

export interface ExecutionStep {
  thought: string;
  code: string;
  output: string;
  status: 'success' | 'error' | 'warning' | 'running';
  /** Which data collection the step ran against (analysis mode). */
  dc_tag?: string;
  /** Cardinalities: a filter that kept everything and one that kept
   *  nothing read identically in prose and very differently here. */
  rows_in?: number | null;
  rows_out?: number | null;
  seconds?: number;
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
  /** Human handle for set_widget targets (the widget's column) — show this,
   *  keep `component_id` for tooltips. */
  label?: string | null;
}

export interface DashboardActions {
  filters: FilterAction[];
  figure_mutations: FigureMutation[];
  filter_proposals?: FilterProposal[];
}

/** Which half of the assistant a request asks for.
 *  - `mutate`: answer *and* propose dashboard actions the user can Apply.
 *  - `analyze`: read-only. The server strips `actions`, so no Apply
 *    affordance may ever render for a reply in this mode. */
export type AnalyzeMode = 'mutate' | 'analyze';

export interface AnalysisResult {
  answer: string;
  steps: ExecutionStep[];
  mode: AnalyzeMode;
  actions: DashboardActions;
  resolved_filters?: ResolvedFilter[];
  /** Things the server dropped or could not do, e.g. actions proposed in
   *  read-only mode, or a malformed action payload. */
  warnings?: string[];
}

/** SSE event names emitted by /ai/analyze and /ai/generate-dashboard.
 *  Mutate mode: status* → step* → answer → actions → result → done.
 *  Analyze mode: status* → (plan) → (budget|step)* → answer → report →
 *  result → done.
 *  Generation: status* → plan → (budget|component)* → dashboard → done.
 *  Regeneration: status* → (budget|component)* → a terminal event carrying
 *  the replacing component dict(s) → done.
 *  `error` may interrupt the stream at any point and is followed by `done`. */
export type AIStreamEventType =
  | 'status'
  | 'step'
  | 'answer'
  | 'actions'
  | 'result'
  | 'plan'
  | 'budget'
  | 'report'
  | 'component'
  | 'components'
  | 'replacement'
  | 'dashboard'
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
  /** Omitted means `mutate`, matching the server default. */
  mode?: AnalyzeMode;
}

// ---------- Analysis reports (read-only mode's artifact) ----------

export interface Finding {
  claim: string;
  /** Indices into AnalysisReport.steps. Non-empty by server validation:
   *  a claim without executed evidence is dropped server-side, never
   *  delivered. */
  evidence_step_ids: number[];
  confidence: 'low' | 'medium' | 'high';
}

export interface BudgetSpent {
  steps: number;
  tokens: number;
  seconds: number;
}

export interface AnalysisReport {
  id: string;
  dashboard_id: string;
  created_at: string;
  model: string;
  prompt: string;
  status: 'running' | 'complete' | 'failed' | 'cancelled';
  findings: Finding[];
  steps: ExecutionStep[];
  narrative_md: string;
  budget_spent: BudgetSpent;
  warnings: string[];
  /** Set on reports an agent wrote (the `create_report` tool, or the
   *  reporter of an agent-team run); absent on `/ai/analyze` reports. */
  agent?: ReportAgentInfo | null;
  /** The agent's own findings, each tied to the tool calls behind it.
   *  Empty or absent on `/ai/analyze` reports, which use `findings`. */
  agent_findings?: AgentReportFinding[];
  updated_at?: string | null;
}

/** Who wrote an agent report. `name` is `<role>/<topic>@<version>` for
 *  agent-team runs, and `run_id` names the run. */
export interface ReportAgentInfo {
  name: string;
  model?: string | null;
  run_id?: string | null;
  on_behalf_of?: string | null;
}

/** One item of evidence behind an agent finding: the tool call that showed
 *  it (`call_id`), the query that ran and the values it returned. */
export interface AgentReportEvidence {
  note: string;
  call_id?: string | null;
  query?: string | null;
  values?: Record<string, unknown> | unknown[] | null;
}

export interface AgentReportFinding {
  title: string;
  detail: string;
  component_index?: string | null;
  confidence: 'low' | 'medium' | 'high';
  evidence: AgentReportEvidence[];
  /** Not in the report schema today: read when a server attaches the
   *  skeptic's verdict to the finding it judged. */
  finding_id?: string | null;
  verdict?: AgentVerdict | null;
  verdict_reason?: string | null;
}

export interface AnalysesResponse {
  analyses: AnalysisReport[];
}

/** Payload of the per-turn `budget` event: the countdown the model sees. */
export interface BudgetTick {
  steps_used: number;
  tokens_used: number;
  seconds: number;
  max_steps: number;
  max_tokens: number;
  max_seconds: number;
  /** Dollars the tokens spent so far are estimated to cost, from the model's
   *  public pricing. Null or absent when the model has no price the server
   *  knows, in which case no cost is shown at all rather than a zero. */
  cost_usd?: number | null;
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

// ---------- Whole-dashboard generation ----------

/** Body of POST /ai/generate-dashboard. Only `project_id` is required: an
 *  empty prompt lets the model plan from the data alone, an empty
 *  `data_collection_ids` means every table collection of the project (up to
 *  the server's cap), and `title` overrides the model's choice (a title
 *  collision then fails unless `overwrite`). */
export interface GenerateDashboardRequest {
  project_id: string;
  prompt?: string;
  title?: string | null;
  data_collection_ids?: string[];
  overwrite?: boolean;
  /** Phase one of the reviewed flow: plan, emit the `plan` event and stop.
   *  Nothing is filled and nothing is saved, so the same request can be
   *  replayed until the plan is worth building. */
  plan_only?: boolean;
  /** Phase two: the plan the user approved, sent back as the server emitted
   *  it. The server re-normalises it, re-emits it as a `plan` event and fills
   *  it, so no planning call is paid for twice. Omit it (with `plan_only`
   *  unset) for the single-call flow. */
  plan?: DashboardPlan | null;
}

/** One section of a generated plan: the presentation fields of
 *  FilterSectionSpec (icon ids and palette names are allowlisted
 *  server-side). */
export interface PlannedSection {
  name: string;
  icon?: string | null;
  color?: string | null;
  description?: string | null;
  /** The planner's own reason for the section, shown to whoever reviews the
   *  draft. Absent from runs generated before the planner was asked for it. */
  rationale?: string | null;
}

/** One component the plan intends to fill. `tag` is the handle every later
 *  `component` event and the terminal `dropped` list refer to. */
export interface PlannedComponent {
  tag: string;
  section: string;
  component_type: ComponentType;
  data_collection_tag: string;
  intent: string;
  /** Catalog offer to fill from, when the plan picked one. */
  use?: string | null;
  /** Advanced-viz kind to fill from, when the plan picked one. */
  viz_kind?: string | null;
}

/** Payload of the `plan` event (under `plan`): what the model intends to
 *  build, before any component is filled. */
export interface DashboardPlan {
  title: string;
  subtitle?: string | null;
  filter_sections: PlannedSection[];
  grid_sections: PlannedSection[];
  components: PlannedComponent[];
}

/** The gates one filled component passes, named after what actually runs.
 *  Mirrors CheckLayer in the AI package's schemas.py. */
export type CheckLayer = 'model' | 'style' | 'substance' | 'schema' | 'render';

/** How one gate answered. `skipped` is its own state: a gate can decline to
 *  run (a text tile has no table to check columns against, four types have no
 *  cheap render probe, a code-mode figure binds no columns statically, the
 *  probe itself can break) and showing that as `passed` would claim a check
 *  that never happened. */
export type CheckStatus = 'passed' | 'failed' | 'skipped';

/** One gate's verdict, read loosely.
 *
 *  What the surfaces that draw a strip actually need. It is deliberately open
 *  where `ComponentCheck` is closed, because those surfaces draw two sources:
 *  this run's own events, which come from this build's server, and the stamp
 *  on a draft, which may have been written by another one. A gate this build
 *  has never heard of is something to show, not to choke on, which is the
 *  same call `AIComponentCheck` makes in the Pydantic model. */
export interface RecordedCheck {
  layer: string;
  status: string;
  /** The finding when failed, the reason when skipped. */
  detail: string;
}

/** One gate's verdict on one component of the run in progress. */
export interface ComponentCheck extends RecordedCheck {
  layer: CheckLayer;
  status: CheckStatus;
}

/** Payload of a `component` event, one per planned component. A later event
 *  for the same tag supersedes the earlier one: a repair turns a failing
 *  component into `repaired`, an exhausted repair budget into `dropped`, and
 *  the render pass re-reports every tile once it has been probed. */
export interface GeneratedComponentEvent {
  tag: string;
  section: string;
  component_type: ComponentType;
  status: 'ok' | 'repaired' | 'dropped';
  attempts: number;
  error?: string | null;
  /** The gates the component went through, in the order they ran. Absent on
   *  a run from a server that did not record them. */
  checks?: ComponentCheck[];
  /** The finding a successful repair round corrected. */
  repair?: string | null;
}

/** Payload of the terminal `dashboard` event: the persisted draft. */
export interface GeneratedDashboardEvent {
  dashboard_id: string;
  title: string;
  project_id: string;
  /** The dashboard as YAML, display-only ("show your work"). */
  yaml: string;
  warnings: string[];
  /** Tags of the planned components that did not survive validation. */
  dropped: string[];
}

/** One planned section with the planner's reason for it; mirrors
 *  AISectionRationale in depictio/models/models/dashboards.py and
 *  DashboardAISection in depictio-react-core. */
export interface AISectionRationale {
  name: string;
  kind: 'filter' | 'grid';
  rationale: string;
}

/** The gates one generated tile went through, as the draft records them.
 *  Mirrors AIComponentChecks in depictio/models/models/dashboards.py. */
export interface AIComponentChecks {
  tag: string;
  attempts: number;
  /** The finding a successful repair round corrected; empty when none. */
  repair: string;
  /** Loose, like the stamp itself: a draft can have been written by another
   *  server build than the one reading it. */
  checks: RecordedCheck[];
}

/** `ai_generation` on a dashboard document. Mirrors AIGenerationInfo in
 *  depictio/models/models/dashboards.py; structurally identical to
 *  depictio-react-core's DashboardAIGeneration so hosts pass the
 *  dashboard's field straight through. */
export interface AIGenerationInfo {
  status: 'draft' | 'promoted';
  model: string;
  prompt: string;
  /** ISO timestamp of the run. */
  generated_at: string;
  run_id: string;
  warnings: string[];
  /** Generation tags of the tiles the owner has been through. Written only
   *  by the review route; autosave strips the whole block. Absent on drafts
   *  saved before the review flow existed, so readers default it to []. */
  reviewed?: string[];
  /** The planner's reason for each section, filter panel first then the
   *  grid, in plan order. Absent on drafts generated before the planner was
   *  asked to explain itself, so readers default it to []. */
  sections?: AISectionRationale[];
  /** Generation tags the run planned but could not deliver. */
  dropped?: string[];
  /** Which gates each tile passed. Absent on drafts saved before the gates
   *  were recorded, which readers must show as "not recorded" rather than
   *  as a clean pass. */
  checks?: AIComponentChecks[];
}

/** Answer of POST /ai/generated-dashboards/{id}/promote. */
export interface PromoteGeneratedDashboardResponse {
  dashboard_id: string;
  status: 'promoted';
}

// ---------- Reviewing a generated draft ----------

/** Body of the two regenerate routes
 *  (`.../components/{index}/regenerate`, `.../sections/{section}/regenerate`).
 *  `instruction` refines what the tile should show ("use a box plot",
 *  "group by cohort"); omitted, the tile is filled again from the plan's
 *  original intent. */
export interface RegenerateRequest {
  instruction?: string;
}

/** Body of POST /ai/generated-dashboards/{id}/review. `tag` is the
 *  generation handle of one tile (`ai_source.tag` on its stored metadata),
 *  not its runtime `index`. */
export interface ReviewComponentRequest {
  /** Empty for the `-all` actions, which read the draft's tiles server-side. */
  tag: string;
  action: 'keep' | 'unkeep' | 'keep-all' | 'unkeep-all';
}

/** Answer of the review route: the draft's progress after the write. */
export interface ReviewComponentResponse {
  reviewed: number;
  total: number;
}

/** Payload of the terminal `regenerated` event of both regenerate routes
 *  (RegeneratedEvent server-side): the components written back, as the full
 *  stored dicts the viewer renders, so a host swaps them into its local
 *  dashboard by `index` without waiting for a refetch.
 *
 *  `components` always lists every tile written; the single-tile route also
 *  repeats its one tile in `component` and names its position and tag.
 *  `normalizeReplacement` in hooks.ts reads whichever is there, and keys off
 *  the payload rather than the event name. */
export interface RegeneratedComponentsEvent {
  dashboard_id: string;
  /** Set by the section route only. */
  section?: string | null;
  /** Position in `stored_metadata`, single-tile route only. */
  index?: number | null;
  tag?: string | null;
  component?: Record<string, unknown> | null;
  components: Record<string, unknown>[];
  warnings: string[];
}

/** Per-outcome tally of one generation run. The wire shape spells the three
 *  out flat on the row (see `GenerationSummary`); this is what
 *  `GenerationHistory` reduces them to before rendering. */
export interface GenerationCounts {
  ok: number;
  repaired: number;
  dropped: number;
}

/** One row of GET /ai/generations/{project_id}: a past whole-dashboard run,
 *  without its plan or its YAML. Mirrors GenerationSummary in schemas.py.
 *  `dashboard_id` is null while the run saved nothing (cancelled, or failed
 *  before the draft landed). `title` is the saved dashboard's, falling back
 *  to the title the plan chose, so it is null only for a run that never got
 *  as far as a plan. */
export interface GenerationSummary {
  id: string;
  dashboard_id: string | null;
  title: string | null;
  prompt: string;
  model: string;
  status: 'running' | 'planned' | 'complete' | 'failed' | 'cancelled';
  /** Naive UTC ISO timestamp, the API's wire convention (no offset). */
  created_at: string;
  ok: number;
  repaired: number;
  dropped: number;
  warnings: string[];
  /** The run saved a draft that has since been deleted: the row still
   *  reports what the run did, without a way back into it. */
  dashboard_deleted?: boolean;
  /** Not on the wire today: tolerated so a nested tally would render rather
   *  than read as three zeroes. */
  counts?: GenerationCounts | null;
}

/** Answer of GET /ai/generations/{project_id} (GenerationsResponse). */
export interface GenerationsResponse {
  generations: GenerationSummary[];
}

// ---------- Agent-team runs (/ai/agent-runs*) ----------

/** One entry of GET /ai/agent-profiles: a role (analyst, skeptic, annotator,
 *  questioner, reporter) or a topic pack (QC, differential expression...). */
export interface AgentProfile {
  id: string;
  kind: 'role' | 'topic';
  name: string;
  version: string | number;
  description: string;
  applies_to_summary?: string | null;
}

/** One member of a team: `agent_id` is `<role>/<topic>@<version>`. */
export interface AgentTeamMember {
  agent_id: string;
  role: string;
  topic?: string | null;
  /** Why the router picked it (matched template, columns, keywords...). */
  reason?: string | null;
}

export interface AgentRouting {
  method: 'rules' | 'llm' | 'fixed';
  scores?: Record<string, unknown>;
}

/** Body of POST /ai/agent-runs/route (dry run: no LLM spend unless rules
 *  tie or miss). */
export interface AgentRouteRequest {
  dashboard_id: string;
  question: string;
}

export interface AgentRouteResponse {
  team: AgentTeamMember[];
  routing: AgentRouting;
}

/** Body of POST /ai/agent-runs. `team` overrides routing when set. */
export interface AgentRunRequest {
  dashboard_id: string;
  question: string;
  team?: string[];
  budget_usd?: number;
}

export type AgentVerdict = 'confirmed' | 'weakened' | 'refuted';
export type AgentRunStatus = 'running' | 'complete' | 'cancelled' | 'failed' | 'budget';
export type AgentStatus = 'ok' | 'budget' | 'error';

export interface AgentRunOutputs {
  thread_ids: string[];
  report_id?: string | null;
  draft_ids: string[];
}

export interface AgentRunBudget {
  spent_usd: number;
  limit_usd: number;
  tool_calls: number;
  max_tool_calls?: number | null;
}

export interface AgentEvidenceRef {
  call_id: string;
  note: string;
}

/** SSE events of POST /ai/agent-runs, in stream order:
 *  run_started, then per agent agent_started, (tool_call, tool_result)*,
 *  finding*, agent_finished; the skeptic's verdicts, the annotator's and
 *  questioner's thread_created, the reporter's report_created; budget ticks
 *  throughout; run_finished, then done. `error` may appear at any point. */
export type AgentRunEvent =
  | {
      type: 'run_started';
      data: {
        run_id: string;
        team: (AgentTeamMember | string)[];
        routing?: AgentRouting | null;
        budget?: { limit_usd: number; max_tool_calls?: number | null } | null;
      };
    }
  | { type: 'agent_started'; data: { agent_id: string; role: string; topic?: string | null } }
  | {
      type: 'tool_call';
      data: { agent_id: string; call_id: string; tool: string; args?: unknown };
    }
  | {
      type: 'tool_result';
      data: {
        agent_id: string;
        call_id: string;
        ok: boolean;
        truncated?: boolean;
        summary?: string | null;
      };
    }
  | {
      type: 'finding';
      data: {
        agent_id: string;
        finding_id: string;
        title: string;
        detail?: string | null;
        component_index?: string | null;
        confidence: 'low' | 'medium' | 'high';
        evidence: AgentEvidenceRef[];
      };
    }
  | {
      type: 'verdict';
      data: { finding_id: string; verdict: AgentVerdict; reason?: string | null; agent_id?: string };
    }
  | {
      type: 'thread_created';
      data: {
        agent_id: string;
        thread_id: string;
        kind: 'comment' | 'question';
        component_index?: string | null;
        finding_id?: string | null;
      };
    }
  | { type: 'report_created'; data: { agent_id: string; report_id: string } }
  | { type: 'budget'; data: AgentRunBudget }
  | {
      type: 'agent_finished';
      data: { agent_id: string; status: AgentStatus; summary?: string | null };
    }
  | { type: 'error'; data: { detail: string; agent_id?: string | null } }
  | {
      type: 'run_finished';
      data: { run_id: string; status: AgentRunStatus; outputs?: Partial<AgentRunOutputs> | null };
    }
  | { type: 'done'; data: Record<string, unknown> };

export type AgentRunEventType = AgentRunEvent['type'];

/** One row of GET /ai/agent-runs?dashboard_id=. Read loosely: `id` or
 *  `run_id` names it (see `agentRunId`). */
export interface AgentRunSummary {
  id?: string;
  run_id?: string;
  dashboard_id: string;
  question: string;
  status: AgentRunStatus;
  team?: (AgentTeamMember | string)[];
  created_at: string;
  finished_at?: string | null;
  budget?: Partial<AgentRunBudget> | null;
  outputs?: Partial<AgentRunOutputs> | null;
}

/** A tool call as a finished run records it. */
export interface AgentToolCallRecord {
  call_id: string;
  tool: string;
  args?: unknown;
  ok?: boolean | null;
  truncated?: boolean;
  summary?: string | null;
  error?: string | null;
}

/** A finding as a finished run records it, with the skeptic's verdict when
 *  it has one and the threads written from it. */
export interface AgentFindingRecord {
  finding_id: string;
  title: string;
  detail?: string | null;
  component_index?: string | null;
  confidence: 'low' | 'medium' | 'high';
  evidence: AgentEvidenceRef[];
  verdict?: AgentVerdict | null;
  verdict_reason?: string | null;
  thread_ids?: string[];
}

export interface AgentRecord {
  agent_id: string;
  role?: string;
  topic?: string | null;
  status?: AgentStatus | 'running' | null;
  summary?: string | null;
  tool_calls?: AgentToolCallRecord[];
  findings?: AgentFindingRecord[];
}

/** GET /ai/agent-runs/{run_id}: the whole run. Everything past the summary
 *  fields is optional so a leaner server still renders. */
export interface AgentRun extends AgentRunSummary {
  routing?: AgentRouting | null;
  agents?: AgentRecord[];
  verdicts?: { finding_id: string; verdict: AgentVerdict; reason?: string | null; agent_id?: string }[];
  /** Threads the run wrote, with the finding each came from. */
  threads?: {
    thread_id: string;
    kind?: 'comment' | 'question';
    component_index?: string | null;
    finding_id?: string | null;
    agent_id?: string;
  }[];
}
