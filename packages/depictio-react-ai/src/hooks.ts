/**
 * High-level hooks for the three AI flows.
 *
 * Each hook is responsible for: reading the per-dashboard key from the
 * store, calling the API client, threading streaming events into the
 * session transcript, and exposing imperative `run()` / `cancel()`
 * functions to the UI.
 */

import { useCallback, useMemo } from 'react';

import {
  figureFromPrompt as apiFigureFromPrompt,
  streamAnalyze as apiStreamAnalyze,
  suggestFigures as apiSuggestFigures,
} from './api';
import { useAISession, useAIStore } from './store';
import type {
  AIStreamEvent,
  AnalysisResult,
  DashboardActions,
  ExecutionStep,
  PlotSuggestion,
} from './types';

function newId(): string {
  return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

/** Prompt-driven viz creation. */
export function useFigureFromPrompt(dashboardId: string) {
  const session = useAISession(dashboardId);
  const { setPending, appendMessage } = useAIStore.getState();

  const run = useCallback(
    async (
      dataCollectionId: string,
      prompt: string,
    ): Promise<PlotSuggestion> => {
      const userMsgId = newId();
      const assistantId = newId();
      appendMessage(dashboardId, {
        id: userMsgId,
        role: 'user',
        content: prompt,
        ts: Date.now(),
      });
      setPending(dashboardId, true);
      try {
        const res = await apiFigureFromPrompt(
          { data_collection_id: dataCollectionId, prompt },
          session.llmKey || null,
        );
        appendMessage(dashboardId, {
          id: assistantId,
          role: 'assistant',
          content: res.suggestion.explanation,
          suggestion: res.suggestion,
          ts: Date.now(),
        });
        return res.suggestion;
      } finally {
        setPending(dashboardId, false);
      }
    },
    [dashboardId, session.llmKey, appendMessage, setPending],
  );

  return useMemo(
    () => ({ run, pending: session.pending }),
    [run, session.pending],
  );
}

/** Data-driven viz suggestion: ask for N proposals at once. */
export function useSuggestFigures(dashboardId: string) {
  const session = useAISession(dashboardId);
  const { setPending } = useAIStore.getState();

  const run = useCallback(
    async (dataCollectionId: string, n = 4): Promise<PlotSuggestion[]> => {
      setPending(dashboardId, true);
      try {
        const res = await apiSuggestFigures(
          { data_collection_id: dataCollectionId, n },
          session.llmKey || null,
        );
        return res.suggestions;
      } finally {
        setPending(dashboardId, false);
      }
    },
    [dashboardId, session.llmKey, setPending],
  );

  return useMemo(
    () => ({ run, pending: session.pending }),
    [run, session.pending],
  );
}

/** Streaming analysis. Caller can subscribe to incremental events via
 *  `onEvent` if it wants per-step UI updates beyond the transcript. */
export function useAnalyze(dashboardId: string) {
  const session = useAISession(dashboardId);
  const { setPending, appendMessage, patchMessage } = useAIStore.getState();

  const run = useCallback(
    async (
      prompt: string,
      opts: {
        selectedComponentId?: string;
        onEvent?: (event: AIStreamEvent) => void;
      } = {},
    ): Promise<AnalysisResult | null> => {
      const userMsgId = newId();
      const assistantId = newId();
      appendMessage(dashboardId, {
        id: userMsgId,
        role: 'user',
        content: prompt,
        ts: Date.now(),
      });
      appendMessage(dashboardId, {
        id: assistantId,
        role: 'assistant',
        content: '',
        steps: [],
        ts: Date.now(),
      });

      const controller = new AbortController();
      setPending(dashboardId, true, controller);

      let result: AnalysisResult | null = null;
      const steps: ExecutionStep[] = [];
      try {
        await apiStreamAnalyze(
          {
            dashboard_id: dashboardId,
            prompt,
            selected_component_id: opts.selectedComponentId,
          },
          session.llmKey || null,
          {
            signal: controller.signal,
            onEvent: (event) => {
              opts.onEvent?.(event);
              switch (event.type) {
                case 'step': {
                  const step = event.data as unknown as ExecutionStep;
                  steps.push(step);
                  patchMessage(dashboardId, assistantId, { steps: [...steps] });
                  break;
                }
                case 'answer': {
                  const answer = String(event.data.answer ?? '');
                  patchMessage(dashboardId, assistantId, { content: answer });
                  break;
                }
                case 'result': {
                  result = event.data as unknown as AnalysisResult;
                  patchMessage(dashboardId, assistantId, {
                    content: result.answer,
                    steps: result.steps,
                    result,
                  });
                  break;
                }
                case 'error': {
                  const detail = String(event.data.detail ?? 'unknown error');
                  patchMessage(dashboardId, assistantId, {
                    content: `Error: ${detail}`,
                  });
                  break;
                }
                default:
                  break;
              }
            },
          },
        );
      } finally {
        setPending(dashboardId, false);
      }
      return result;
    },
    [dashboardId, session.llmKey, appendMessage, patchMessage, setPending],
  );

  const cancel = useCallback(() => {
    session.abort?.abort();
    setPending(dashboardId, false);
  }, [dashboardId, session.abort, setPending]);

  return useMemo(
    () => ({ run, cancel, pending: session.pending }),
    [run, cancel, session.pending],
  );
}

export type { DashboardActions };
