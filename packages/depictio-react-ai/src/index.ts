/**
 * Public surface of depictio-react-ai.
 */

// Components
export { default as AIAnalyzePanel } from './components/AIAnalyzePanel';
export { default as AIKeySection } from './components/AIKeySection';
export { default as ActionsPreview } from './components/ActionsPreview';
export type { ApplyActionsPayload } from './components/ActionsPreview';
export { default as AddWithAIModal } from './components/AddWithAIModal';
export type { AvailableDataCollection } from './components/AddWithAIModal';
export { default as AiFillModal } from './components/AiFillModal';
export { default as ExecutionTrace } from './components/ExecutionTrace';
export {
  SectionSummaryPanel,
  SummarizeSectionButton,
  trimDigest,
  useSectionSummaries,
} from './components/SectionSummary';
export type { SectionSummaryState } from './components/SectionSummary';

export {
  componentFromPrompt,
  getAIHealth,
  getSummaries,
  resolveFilters,
  streamAnalyze,
  suggestFigures,
  summarizeSection,
} from './api';
export type { AIHealth, AnalyzeStreamHandlers } from './api';

export { useAISession, useAIStore } from './store';
export type { AIChatMessage, AISession } from './store';

export {
  useAIHealth,
  useAnalyze,
  useComponentFromPrompt,
  useResolveFilters,
  useSuggestFigures,
  useSummarizeSection,
} from './hooks';

export type {
  AIStreamEvent,
  AIStreamEventType,
  AnalysisResult,
  AnalyzeRequest,
  ComponentFromPromptRequest,
  ComponentFromPromptResponse,
  ComponentType,
  DashboardActions,
  ExecutionStep,
  FigureMutation,
  FilterAction,
  FilterProposal,
  PlotSuggestion,
  ResolveFiltersRequest,
  ResolveFiltersResponse,
  ResolvedFilter,
  SuggestFiguresRequest,
  SuggestFiguresResponse,
  SummariesResponse,
  SummarizeSectionRequest,
  SummarizeSectionResponse,
  SummaryComponentPayload,
  SummaryEntry,
  ThresholdSpec,
} from './types';
