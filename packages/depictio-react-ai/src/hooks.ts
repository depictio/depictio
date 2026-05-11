/**
 * High-level hooks for the AI flows.
 *
 * Each hook reads the per-dashboard key from the store, calls the API
 * client, and exposes an imperative `run()` (plus `cancel()` for the
 * streaming analyze flow).
 */

import { useCallback, useMemo, useState } from 'react';

import {
  componentFromPrompt as apiComponentFromPrompt,
  streamAnalyze as apiStreamAnalyze,
} from './api';
import { useAISession, useAIStore } from './store';
import type {
  AIStreamEvent,
  AnalysisResult,
  ComponentFromPromptRequest,
  ComponentFromPromptResponse,
  DashboardActions,
  ExecutionStep,
} from './types';

function newId(): string {
  return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

/** Prompt-driven typed component creation.
 *
 *  Returns the validated component dict (plus YAML for "show your
 *  work" displays). Callers are expected to drop `parsed` into the
 *  builder store's `config` and let the existing builder + per-type
 *  preview render the result.
 */
export function useComponentFromPrompt(dashboardId: string) {
  const session = useAISession(dashboardId);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResponse, setLastResponse] =
    useState<ComponentFromPromptResponse | null>(null);

  const run = useCallback(
    async (
      body: ComponentFromPromptRequest,
    ): Promise<ComponentFromPromptResponse> => {
      setPending(true);
      setError(null);
      try {
        const res = await apiComponentFromPrompt(body, session.llmKey || null);
        setLastResponse(res);
        return res;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        throw e;
      } finally {
        setPending(false);
      }
    },
    [session.llmKey],
  );

  return useMemo(
    () => ({ run, pending, error, lastResponse }),
    [run, pending, error, lastResponse],
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
