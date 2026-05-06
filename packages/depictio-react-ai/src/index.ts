/**
 * Public surface of depictio-react-ai.
 *
 * Components are added in Layer 5; this barrel currently exports the
 * client + state primitives so other packages can start consuming the
 * AI endpoints without waiting for the chrome to land.
 */

export {
  figureFromPrompt,
  streamAnalyze,
  suggestFigures,
} from './api';
export type { AnalyzeStreamHandlers } from './api';

export { useAISession, useAIStore } from './store';
export type { AIChatMessage, AISession } from './store';

export { useAnalyze, useFigureFromPrompt, useSuggestFigures } from './hooks';

export type {
  AIStreamEvent,
  AIStreamEventType,
  AnalysisResult,
  AnalyzeRequest,
  DashboardActions,
  ExecutionStep,
  FigureFromPromptRequest,
  FigureFromPromptResponse,
  FigureMutation,
  FilterAction,
  PlotSuggestion,
  SuggestFiguresRequest,
  SuggestFiguresResponse,
  VisuType,
} from './types';
