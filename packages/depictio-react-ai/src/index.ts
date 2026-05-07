/**
 * Public surface of depictio-react-ai.
 */

// Components
export { default as AIAnalyzePanel } from './components/AIAnalyzePanel';
export { default as AIDrawer } from './components/AIDrawer';
export { default as AIKeySection } from './components/AIKeySection';
export { default as AISuggestedFigures } from './components/AISuggestedFigures';
export type { AISuggestedFigure } from './components/AISuggestedFigures';
export { default as ActionsPreview } from './components/ActionsPreview';
export { default as ExecutionTrace } from './components/ExecutionTrace';
export { default as FigurePreview } from './components/FigurePreview';
export { default as PythonCodeBlock } from './components/PythonCodeBlock';
export { default as SuggestionsPanel } from './components/SuggestionsPanel';

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
