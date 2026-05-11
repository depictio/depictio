/**
 * Public surface of depictio-react-ai.
 */

// Components
export { default as AIAnalyzePanel } from './components/AIAnalyzePanel';
export { default as AIKeySection } from './components/AIKeySection';
export { default as ActionsPreview } from './components/ActionsPreview';
export { default as AiFillModal } from './components/AiFillModal';
export { default as ExecutionTrace } from './components/ExecutionTrace';

export { componentFromPrompt, streamAnalyze } from './api';
export type { AnalyzeStreamHandlers } from './api';

export { useAISession, useAIStore } from './store';
export type { AIChatMessage, AISession } from './store';

export { useAnalyze, useComponentFromPrompt } from './hooks';

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
} from './types';
