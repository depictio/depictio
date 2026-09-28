/**
 * Public surface of depictio-react-ai.
 */

// The one AI affordance icon (star) — hosts reuse it for their own AI
// entry points (menus, builder buttons) so the cue stays uniform.
export { AI_COLOR, AI_ICON, aiColorVar } from './icons';

// Components
export { default as AIAnalyzePanel } from './components/AIAnalyzePanel';
export { default as AIKeySection } from './components/AIKeySection';
export { default as ActionsPreview } from './components/ActionsPreview';
export type { ApplyActionsPayload } from './components/ActionsPreview';
export { default as AiFillModal } from './components/AiFillModal';
export { default as AIAnalysisModal } from './components/AIAnalysisModal';
export { default as AIDraftBanner, formatGeneratedAt } from './components/AIDraftBanner';
export { default as DraftReviewPanel } from './components/DraftReviewPanel';
export type {
  DraftReviewPanelProps,
  DraftReviewSection,
  DraftTile,
} from './components/DraftReviewPanel';
export { default as ExecutionTrace } from './components/ExecutionTrace';
export { default as AgentRunTrace, VerdictBadge, VERDICT_COLOR } from './components/AgentRunTrace';
export { default as AgentTeamPanel, composeTeamOptions } from './components/AgentTeamPanel';
export { default as GenerationHistory } from './components/GenerationHistory';
export type { GenerationHistoryProps } from './components/GenerationHistory';
export { default as GenerateDashboardPanel } from './components/GenerateDashboardPanel';
export type {
  GenerateDataCollection,
  GenerateJoinInfo,
  GenerateProjectOption,
} from './components/GenerateDashboardPanel';
export { default as GenerationProgress } from './components/GenerationProgress';
export type { GenerationProgressProps } from './components/GenerationProgress';
export {
  SectionSummaryPanel,
  SummarizeSectionButton,
  trimDigest,
  useSectionSummaries,
} from './components/SectionSummary';
export type { SectionSummaryState } from './components/SectionSummary';

export {
  cancelAgentRun,
  fetchAgentProfiles,
  fetchAgentRun,
  fetchAgentRuns,
  parseSSEFrame,
  routeAgentRun,
  splitSSEFrames,
  streamAgentRun,
  componentFromPrompt,
  fetchGenerations,
  getAIHealth,
  getAnalyses,
  getSummaries,
  promoteGeneratedDashboard,
  resolveFilters,
  reviewComponent,
  streamAnalyze,
  streamGenerateDashboard,
  streamPost,
  streamRegenerateComponent,
  streamRegenerateSection,
  suggestComponents,
  summarizeSection,
} from './api';
export type {
  AgentRunStreamHandlers,
  AIHealth,
  AIStreamHandlers,
  AnalyzeStreamHandlers,
  SSEFrame,
} from './api';

export {
  acceptableThreads,
  agentRunId,
  agentRunLabel,
  agentRunToTrace,
  EMPTY_AGENT_TRACE,
  filterThreads,
  laneVerdicts,
  reduceAgentRunEvent,
  runIdsOf,
  splitAgentId,
  threadRunId,
  threadVerdicts,
  traceReportId,
} from './agentRuns';
export type {
  AgentLane,
  AgentRunTraceState,
  ThreadFilter,
  TraceFinding,
  TraceThread,
  TraceToolCall,
  TraceVerdict,
} from './agentRuns';
export { useAgentProfiles, useAgentRoute, useAgentRun } from './useAgentTeam';
export type { AgentRouteState, AgentRunOptions } from './useAgentTeam';

export { useAISession, useAIStore } from './store';
export type { AIChatMessage, AISession } from './store';

export {
  GENERATE_DASHBOARD_SESSION_ID,
  useAIHealth,
  useAnalysisReport,
  useAnalyze,
  useComponentFromPrompt,
  useGenerateDashboard,
  useGenerationRun,
  useRegenerateComponent,
  useResolveFilters,
  useSuggestComponents,
  useSummarizeSection,
} from './hooks';
export type {
  AnalysisRunState,
  GenerateDashboardRunOptions,
  GenerateDashboardRunState,
  GenerationRun,
  GenerationRunSummary,
  RegenerateRunState,
  RunSpend,
} from './hooks';

export type {
  AgentEvidenceRef,
  AgentFindingRecord,
  AgentProfile,
  AgentRecord,
  AgentReportEvidence,
  AgentReportFinding,
  AgentRouteRequest,
  AgentRouteResponse,
  AgentRouting,
  AgentRun,
  AgentRunBudget,
  AgentRunEvent,
  AgentRunEventType,
  AgentRunOutputs,
  AgentRunRequest,
  AgentRunStatus,
  AgentRunSummary,
  AgentStatus,
  AgentTeamMember,
  AgentToolCallRecord,
  AgentVerdict,
  ReportAgentInfo,
  AIComponentChecks,
  AIGenerationInfo,
  AISectionRationale,
  AIStreamEvent,
  AIStreamEventType,
  AnalysesResponse,
  AnalysisReport,
  AnalysisResult,
  AnalyzeMode,
  AnalyzeRequest,
  BudgetSpent,
  BudgetTick,
  Finding,
  CheckLayer,
  CheckStatus,
  ComponentCheck,
  RecordedCheck,
  ComponentFromPromptRequest,
  ComponentFromPromptResponse,
  ComponentSuggestion,
  ComponentType,
  DashboardActions,
  DashboardPlan,
  ExecutionStep,
  FigureMutation,
  FilterAction,
  FilterProposal,
  GenerateDashboardRequest,
  GeneratedComponentEvent,
  GeneratedDashboardEvent,
  GenerationCounts,
  GenerationSummary,
  PlannedComponent,
  PlannedSection,
  PromoteGeneratedDashboardResponse,
  RegenerateRequest,
  RegeneratedComponentsEvent,
  ResolveFiltersRequest,
  ResolveFiltersResponse,
  ResolvedFilter,
  ReviewComponentRequest,
  ReviewComponentResponse,
  RoutedCollection,
  RoutingInfo,
  SuggestComponentsRequest,
  SuggestComponentsResponse,
  SummariesResponse,
  SummarizeSectionRequest,
  SummarizeSectionResponse,
  SummaryComponentPayload,
  SummaryEntry,
  ThresholdSpec,
} from './types';
