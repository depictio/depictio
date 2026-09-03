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
  streamGenerateDashboard as apiStreamGenerateDashboard,
  streamRegenerateComponent as apiStreamRegenerateComponent,
  streamRegenerateSection as apiStreamRegenerateSection,
  suggestComponents as apiSuggestComponents,
  summarizeSection as apiSummarizeSection,
  type AIHealth,
  type AIStreamHandlers,
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
  ComponentSuggestion,
  DashboardActions,
  DashboardPlan,
  ExecutionStep,
  GenerateDashboardRequest,
  GeneratedComponentEvent,
  GeneratedDashboardEvent,
  ResolveFiltersResponse,
  SuggestComponentsRequest,
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
      // The hook already knows the dashboard, so callers only spell out
      // `dashboard_id` to override it (or pass null to withhold it). This is
      // what gives a `text` request its context without every caller
      // repeating the id.
      const request: ComponentFromPromptRequest =
        body.dashboard_id === undefined ? { ...body, dashboard_id: dashboardId } : body;
      try {
        const res = await apiComponentFromPrompt(request, session.llmKey || null);
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

/** Typed component suggestions for one dashboard ("what would you add?").
 *  Either pin is optional; null means Auto. Callers are expected to `reset()`
 *  when the pins change so a stale list is never applied against the wrong
 *  collection. `warnings` carries what the server could not do (an LLM
 *  failure with ranked suggestions still shown, for instance). */
export function useSuggestComponents(dashboardId: string) {
  const session = useAISession(dashboardId);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<ComponentSuggestion[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);

  const run = useCallback(
    async (
      body: Omit<SuggestComponentsRequest, 'dashboard_id'>,
    ): Promise<ComponentSuggestion[]> => {
      setPending(true);
      setError(null);
      try {
        const res = await apiSuggestComponents(
          { ...body, dashboard_id: dashboardId, n: body.n ?? 4 },
          session.llmKey || null,
        );
        setSuggestions(res.suggestions);
        setWarnings(res.warnings ?? []);
        return res.suggestions;
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

  const reset = useCallback(() => {
    setSuggestions([]);
    setWarnings([]);
    setError(null);
  }, []);

  return useMemo(
    () => ({ run, reset, suggestions, warnings, pending, error }),
    [run, reset, suggestions, warnings, pending, error],
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
      // Server default is the mutating flow when mode is omitted.
      const mode = opts.mode ?? 'mutate';
      appendMessage(dashboardId, {
        id: userMsgId,
        role: 'user',
        content: prompt,
        mode,
        ts: Date.now(),
      });
      appendMessage(dashboardId, {
        id: assistantId,
        role: 'assistant',
        content: '',
        steps: [],
        mode,
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
      } catch (err) {
        // Transport-level failures (HTTP status, network drop, aborted
        // stream) never come through as an SSE `error` event — surface
        // them on the assistant message so the run doesn't end silently.
        const aborted = err instanceof DOMException && err.name === 'AbortError';
        if (!aborted) {
          patchMessage(dashboardId, assistantId, {
            content: `Error: ${err instanceof Error ? err.message : String(err)}`,
          });
        }
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

/** Session id the whole-dashboard generator keys its LLM credentials on.
 *  There is no dashboard yet when it runs, so the key cannot live under a
 *  dashboard id; one shared entry means the user enters it once for every
 *  project. `AIKeySection` and `useGenerateDashboard` must agree on it. */
export const GENERATE_DASHBOARD_SESSION_ID = 'generate-dashboard';

export interface GenerateDashboardRunState {
  status: string;
  plan: DashboardPlan | null;
  budget: BudgetTick | null;
  /** One entry per reported component tag, the latest event winning. */
  components: GeneratedComponentEvent[];
  dashboard: GeneratedDashboardEvent | null;
  error: string | null;
}

const EMPTY_GENERATION: GenerateDashboardRunState = {
  status: '',
  plan: null,
  budget: null,
  components: [],
  dashboard: null,
  error: null,
};

/** The plan arrives from a model-facing schema; default the lists so the
 *  panel never has to guard against a missing array. */
function normalizePlan(raw: unknown): DashboardPlan | null {
  if (!raw || typeof raw !== 'object') return null;
  const p = raw as Partial<DashboardPlan>;
  return {
    title: String(p.title ?? ''),
    subtitle: p.subtitle ?? null,
    filter_sections: Array.isArray(p.filter_sections) ? p.filter_sections : [],
    grid_sections: Array.isArray(p.grid_sections) ? p.grid_sections : [],
    components: Array.isArray(p.components) ? p.components : [],
  };
}

function normalizeDashboardEvent(raw: Record<string, unknown>): GeneratedDashboardEvent {
  const d = raw as unknown as Partial<GeneratedDashboardEvent>;
  return {
    dashboard_id: String(d.dashboard_id ?? ''),
    title: String(d.title ?? ''),
    project_id: String(d.project_id ?? ''),
    yaml: String(d.yaml ?? ''),
    warnings: Array.isArray(d.warnings) ? d.warnings.map(String) : [],
    dropped: Array.isArray(d.dropped) ? d.dropped.map(String) : [],
  };
}

/** Drive one whole-dashboard generation run and expose its live state: the
 *  status line, the plan, the budget countdown, per-component outcomes and
 *  finally the persisted draft (`dashboard`). Modelled on useAnalysisReport
 *  and, like it, not backed by the chat store. */
export function useGenerateDashboard() {
  const session = useAISession(GENERATE_DASHBOARD_SESSION_ID);
  const [state, setState] = useState<GenerateDashboardRunState>(EMPTY_GENERATION);
  const [pending, setPending] = useState(false);
  const [controller, setController] = useState<AbortController | null>(null);

  const run = useCallback(
    async (body: GenerateDashboardRequest) => {
      const abort = new AbortController();
      setController(abort);
      setPending(true);
      setState({ ...EMPTY_GENERATION, status: 'starting' });

      const components: GeneratedComponentEvent[] = [];
      try {
        await apiStreamGenerateDashboard(body, session.llmKey || null, {
          signal: abort.signal,
          onEvent: (event: AIStreamEvent) => {
            switch (event.type) {
              case 'status':
                setState((s) => ({ ...s, status: String(event.data.message ?? '') }));
                break;
              case 'plan':
                setState((s) => ({ ...s, plan: normalizePlan(event.data.plan) }));
                break;
              case 'budget':
                setState((s) => ({ ...s, budget: event.data as unknown as BudgetTick }));
                break;
              case 'component': {
                const c = event.data as unknown as GeneratedComponentEvent;
                // A tag reports more than once (filled, then repaired or
                // dropped): the latest outcome replaces the earlier row.
                const at = components.findIndex((x) => x.tag === c.tag);
                if (at === -1) components.push(c);
                else components[at] = c;
                setState((s) => ({ ...s, components: [...components] }));
                break;
              }
              case 'dashboard':
                setState((s) => ({ ...s, dashboard: normalizeDashboardEvent(event.data) }));
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
        });
      } catch (e) {
        if (!abort.signal.aborted) {
          setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }));
        }
      } finally {
        setPending(false);
        setController(null);
      }
    },
    [session.llmKey],
  );

  const cancel = useCallback(() => {
    controller?.abort();
    setPending(false);
  }, [controller]);

  return useMemo(() => ({ run, cancel, pending, state }), [run, cancel, pending, state]);
}

/** Live state of one regeneration run: the status line, the budget
 *  countdown, the per-tile outcomes and the component dicts that came back
 *  to replace the tiles on the dashboard. Same shape as
 *  `GenerateDashboardRunState`, minus the plan a regeneration has no need
 *  for (the plan is the draft it is editing). */
export interface RegenerateRunState {
  status: string;
  budget: BudgetTick | null;
  /** One row per reported tag, the latest outcome winning. */
  rows: GeneratedComponentEvent[];
  /** Replacing components in `stored_metadata` shape, keyed by their own
   *  `index`: the host swaps them into its local dashboard. */
  replaced: Record<string, unknown>[];
  error: string | null;
}

const EMPTY_REGENERATION: RegenerateRunState = {
  status: '',
  budget: null,
  rows: [],
  replaced: [],
  error: null,
};

/** Pull the replacing component dict(s) out of a regenerate stream's
 *  terminal `regenerated` event (RegeneratedEvent server-side).
 *
 *  `components` is the complete list of tiles written back and is what the
 *  section route answers with; the single-tile route repeats its one tile
 *  in `component`, so that is the fallback rather than the first read. The
 *  event is matched by its payload rather than by its name so a rename on
 *  the server surfaces as a no-op, not as a silently stale tile. */
function normalizeReplacement(data: Record<string, unknown>): Record<string, unknown>[] {
  const many = data.components ?? data.stored_metadata;
  if (Array.isArray(many) && many.length) {
    return many.filter(
      (c): c is Record<string, unknown> => Boolean(c) && typeof c === 'object',
    );
  }
  const single = data.component;
  if (single && typeof single === 'object' && !Array.isArray(single)) {
    return [single as Record<string, unknown>];
  }
  return [];
}

/**
 * Regenerate one tile of an AI-generated draft, or every tile of one of its
 * sections.
 *
 * Modelled on `useGenerateDashboard`: one run at a time, an imperative
 * `run` / `runSection`, live state for the status line and the budget, and
 * `cancel()` for the abort. Both entry points resolve with the components
 * that came back, so a host can swap them into its own dashboard state
 * without a refetch; the run itself is persisted server-side, so nothing
 * here saves the dashboard.
 */
export function useRegenerateComponent(dashboardId: string) {
  const session = useAISession(dashboardId);
  const [state, setState] = useState<RegenerateRunState>(EMPTY_REGENERATION);
  const [pending, setPending] = useState(false);
  const [controller, setController] = useState<AbortController | null>(null);

  /** Both routes stream the same events; only the URL differs, so the whole
   *  state machine lives here and the two entry points just pick a caller. */
  const stream = useCallback(
    async (
      call: (handlers: AIStreamHandlers) => Promise<void>,
    ): Promise<Record<string, unknown>[]> => {
      const abort = new AbortController();
      setController(abort);
      setPending(true);
      setState({ ...EMPTY_REGENERATION, status: 'starting' });

      const rows: GeneratedComponentEvent[] = [];
      let replaced: Record<string, unknown>[] = [];
      try {
        await call({
          signal: abort.signal,
          onEvent: (event: AIStreamEvent) => {
            switch (event.type) {
              case 'status':
                setState((s) => ({ ...s, status: String(event.data.message ?? '') }));
                break;
              case 'budget':
                setState((s) => ({ ...s, budget: event.data as unknown as BudgetTick }));
                break;
              case 'component': {
                const c = event.data as unknown as GeneratedComponentEvent;
                // As in generation, a tag reports again after a repair: the
                // latest outcome replaces the earlier row.
                const at = rows.findIndex((x) => x.tag === c.tag);
                if (at === -1) rows.push(c);
                else rows[at] = c;
                setState((s) => ({ ...s, rows: [...rows] }));
                break;
              }
              case 'error':
                setState((s) => ({
                  ...s,
                  error: String(event.data.detail ?? 'unknown error'),
                }));
                break;
              case 'done':
                break;
              default: {
                // Every other event is a candidate terminal one — see
                // `normalizeReplacement` on why the name is not assumed.
                const found = normalizeReplacement(event.data);
                if (found.length) {
                  replaced = found;
                  setState((s) => ({ ...s, replaced: found }));
                }
                break;
              }
            }
          },
        });
      } catch (e) {
        if (!abort.signal.aborted) {
          setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }));
        }
      } finally {
        setPending(false);
        setController(null);
      }
      return replaced;
    },
    [],
  );

  /** One tile, addressed by its `stored_metadata.index`. */
  const run = useCallback(
    ({ index, instruction }: { index: string; instruction?: string }) =>
      stream((handlers) =>
        apiStreamRegenerateComponent(
          dashboardId,
          index,
          { instruction: instruction?.trim() || undefined },
          session.llmKey || null,
          handlers,
        ),
      ),
    [dashboardId, session.llmKey, stream],
  );

  /** Every tile of one grid section, addressed by the section's name. */
  const runSection = useCallback(
    ({ section, instruction }: { section: string; instruction?: string }) =>
      stream((handlers) =>
        apiStreamRegenerateSection(
          dashboardId,
          section,
          { instruction: instruction?.trim() || undefined },
          session.llmKey || null,
          handlers,
        ),
      ),
    [dashboardId, session.llmKey, stream],
  );

  const cancel = useCallback(() => {
    controller?.abort();
    setPending(false);
  }, [controller]);

  const reset = useCallback(() => setState(EMPTY_REGENERATION), []);

  return useMemo(
    () => ({ run, runSection, cancel, reset, pending, state }),
    [run, runSection, cancel, reset, pending, state],
  );
}

export type { DashboardActions };
