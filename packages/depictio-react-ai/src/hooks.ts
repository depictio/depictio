/**
 * High-level hooks for the AI flows.
 *
 * Each hook reads the per-dashboard key from the store, calls the API
 * client, and exposes an imperative `run()` (plus `cancel()` for the
 * streaming analyze flow).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  componentFromPrompt as apiComponentFromPrompt,
  getAIHealth,
  getAnalyses as apiGetAnalyses,
  resolveFilters as apiResolveFilters,
  streamAnalyze as apiStreamAnalyze,
  suggestFigures as apiSuggestFigures,
  summarizeSection as apiSummarizeSection,
  type AIHealth,
} from './api';
import { useAISession, useAIStore } from './store';
import type {
  AIStreamEvent,
  AnalysisReport,
  AnalysisResult,
  AnalyzeMode,
  BudgetTick,
  ComponentFromPromptRequest,
  ComponentFromPromptResponse,
  DashboardActions,
  ExecutionStep,
  PlotSuggestion,
  ResolveFiltersResponse,
  SummarizeSectionRequest,
  SummarizeSectionResponse,
} from './types';

function newId(): string {
  return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

/** One-shot /ai/health probe. `enabled=false` (feature off) never fetches
 *  and reports a null health. Used to decide whether a server-side
 *  fallback key exists, i.e. whether the UI works without a user key. */
export function useAIHealth(enabled: boolean): AIHealth | null {
  const [health, setHealth] = useState<AIHealth | null>(null);

  useEffect(() => {
    if (!enabled) {
      setHealth(null);
      return;
    }
    let cancelled = false;
    getAIHealth()
      .then((h) => {
        if (!cancelled) setHealth(h);
      })
      .catch(() => {
        if (!cancelled) setHealth(null);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return health;
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

/** Data-grounded figure suggestions for one data collection. Suggestions
 *  reset when the target DC changes so a stale list is never shown against
 *  the wrong columns. */
export function useSuggestFigures(dashboardId: string) {
  const session = useAISession(dashboardId);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<PlotSuggestion[]>([]);

  const run = useCallback(
    async (dataCollectionId: string, n = 4): Promise<PlotSuggestion[]> => {
      setPending(true);
      setError(null);
      try {
        const res = await apiSuggestFigures(
          { data_collection_id: dataCollectionId, n },
          session.llmKey || null,
        );
        setSuggestions(res.suggestions);
        return res.suggestions;
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

  const reset = useCallback(() => {
    setSuggestions([]);
    setError(null);
  }, []);

  return useMemo(
    () => ({ run, reset, suggestions, pending, error }),
    [run, reset, suggestions, pending, error],
  );
}

/** Direct NL → dashboard filters (no ReAct loop, no transcript). */
export function useResolveFilters(dashboardId: string) {
  const session = useAISession(dashboardId);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResponse, setLastResponse] = useState<ResolveFiltersResponse | null>(null);

  const run = useCallback(
    async (prompt: string, activeFilters: unknown[] = []): Promise<ResolveFiltersResponse> => {
      setPending(true);
      setError(null);
      try {
        const res = await apiResolveFilters(
          { dashboard_id: dashboardId, prompt, filters: activeFilters },
          session.llmKey || null,
        );
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
    [dashboardId, session.llmKey],
  );

  return useMemo(
    () => ({ run, pending, error, lastResponse }),
    [run, pending, error, lastResponse],
  );
}

/** Section summary generation (see /ai/summarize-section). */
export function useSummarizeSection(dashboardId: string) {
  const session = useAISession(dashboardId);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (
      body: Omit<SummarizeSectionRequest, 'dashboard_id'>,
    ): Promise<SummarizeSectionResponse> => {
      setPending(true);
      setError(null);
      try {
        return await apiSummarizeSection(
          { dashboard_id: dashboardId, ...body },
          session.llmKey || null,
        );
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        throw e;
      } finally {
        setPending(false);
      }
    },
    [dashboardId, session.llmKey],
  );

  return useMemo(() => ({ run, pending, error }), [run, pending, error]);
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
        /** Active InteractiveFilter list — forwarded so server-side
         *  computation (executor, quantile thresholds) sees the same
         *  rows the user does. */
        activeFilters?: unknown[];
        /** Omit for the conversational (mutating) flow. `analyze` asks
         *  for the read-only surface: the server strips actions, so the
         *  caller must not render an Apply affordance. */
        mode?: AnalyzeMode;
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
            filters: opts.activeFilters ?? [],
            mode: opts.mode,
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

export interface AnalysisRunState {
  status: string;
  plan: string | null;
  budget: BudgetTick | null;
  steps: ExecutionStep[];
  report: AnalysisReport | null;
  error: string | null;
}

const EMPTY_RUN: AnalysisRunState = {
  status: '',
  plan: null,
  budget: null,
  steps: [],
  report: null,
  error: null,
};

/** Drive one read-only analysis run (`mode: "analyze"`) and expose its
 *  full live state: status line, the model's plan, the budget countdown,
 *  the step trace, and finally the persisted `AnalysisReport`.
 *
 *  Deliberately not backed by the chat store: a report is an artifact,
 *  not a message in a transcript. No Apply surface exists in this flow. */
export function useAnalysisReport(dashboardId: string) {
  const session = useAISession(dashboardId);
  const [state, setState] = useState<AnalysisRunState>(EMPTY_RUN);
  const [pending, setPending] = useState(false);
  const [controller, setController] = useState<AbortController | null>(null);
  const [history, setHistory] = useState<AnalysisReport[]>([]);

  const run = useCallback(
    async (prompt: string, opts: { activeFilters?: unknown[] } = {}) => {
      const abort = new AbortController();
      setController(abort);
      setPending(true);
      setState({ ...EMPTY_RUN, status: 'starting' });

      const steps: ExecutionStep[] = [];
      try {
        await apiStreamAnalyze(
          {
            dashboard_id: dashboardId,
            prompt,
            filters: opts.activeFilters ?? [],
            mode: 'analyze',
          },
          session.llmKey || null,
          {
            signal: abort.signal,
            onEvent: (event: AIStreamEvent) => {
              switch (event.type) {
                case 'status':
                  setState((s) => ({ ...s, status: String(event.data.message ?? '') }));
                  break;
                case 'plan':
                  setState((s) => ({ ...s, plan: String(event.data.plan ?? '') }));
                  break;
                case 'budget':
                  setState((s) => ({ ...s, budget: event.data as unknown as BudgetTick }));
                  break;
                case 'step': {
                  const step = event.data as unknown as ExecutionStep;
                  // A step arrives twice: first as "running", then with
                  // its outcome. Replace the placeholder instead of
                  // appending both.
                  if (steps.length && steps[steps.length - 1].status === 'running') {
                    steps[steps.length - 1] = step;
                  } else {
                    steps.push(step);
                  }
                  setState((s) => ({ ...s, steps: [...steps] }));
                  break;
                }
                case 'report':
                  setState((s) => ({
                    ...s,
                    report: event.data as unknown as AnalysisReport,
                  }));
                  break;
                case 'error':
                  setState((s) => ({
                    ...s,
                    error: String(event.data.detail ?? 'unknown error'),
                  }));
                  break;
                default:
                  break;
              }
            },
          },
        );
      } catch (e) {
        if (!abort.signal.aborted) {
          setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }));
        }
      } finally {
        setPending(false);
        setController(null);
      }
    },
    [dashboardId, session.llmKey],
  );

  const cancel = useCallback(() => {
    controller?.abort();
    setPending(false);
  }, [controller]);

  const reset = useCallback(() => setState(EMPTY_RUN), []);

  const loadHistory = useCallback(async () => {
    try {
      const res = await apiGetAnalyses(dashboardId);
      setHistory(res.analyses);
    } catch {
      setHistory([]);
    }
  }, [dashboardId]);

  return useMemo(
    () => ({ run, cancel, reset, pending, state, history, loadHistory }),
    [run, cancel, reset, pending, state, history, loadHistory],
  );
}

export type { DashboardActions };
