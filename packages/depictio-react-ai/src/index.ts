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
export { default as DraftTileActions } from './components/DraftTileActions';
export type { DraftTileActionsProps } from './components/DraftTileActions';
export { default as ExecutionTrace } from './components/ExecutionTrace';
export { default as GenerationHistory } from './components/GenerationHistory';
export type { GenerationHistoryProps } from './components/GenerationHistory';
export { default as GenerateDashboardPanel } from './components/GenerateDashboardPanel';
export type {
  GenerateDataCollection,
  GenerateProjectOption,
} from './components/GenerateDashboardPanel';
export {
  SectionSummaryPanel,
  SummarizeSectionButton,
  trimDigest,
  useSectionSummaries,
} from './components/SectionSummary';
export type { SectionSummaryState } from './components/SectionSummary';

export {
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
export type { AIHealth, AIStreamHandlers, AnalyzeStreamHandlers } from './api';

export { useAISession, useAIStore } from './store';
export type { AIChatMessage, AISession } from './store';

export {
  GENERATE_DASHBOARD_SESSION_ID,
  useAIHealth,
  useAnalysisReport,
  useAnalyze,
  useComponentFromPrompt,
  useGenerateDashboard,
  useRegenerateComponent,
  useResolveFilters,
  useSuggestComponents,
  useSummarizeSection,
} from './hooks';
export type {
  AnalysisRunState,
  GenerateDashboardRunState,
  RegenerateRunState,
} from './hooks';

export type {
  AIGenerationInfo,
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
