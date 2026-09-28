/**
 * Hooks for agent-team runs: the profiles to staff a team with, the
 * debounced routing dry run, and one run's live trace.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  cancelAgentRun,
  fetchAgentProfiles,
  fetchAgentRun,
  fetchAgentRuns,
  routeAgentRun,
  streamAgentRun,
} from './api';
import { agentRunToTrace, EMPTY_AGENT_TRACE, reduceAgentRunEvent } from './agentRuns';
import type { AgentRunTraceState } from './agentRuns';
import { useAISession } from './store';
import type { AgentProfile, AgentRouteResponse, AgentRunSummary } from './types';

/** Shorter questions are not routed: the rules match on keywords, and a
 *  half-typed word routes to noise. */
const MIN_ROUTE_CHARS = 8;
const ROUTE_DEBOUNCE_MS = 600;

export function useAgentProfiles(enabled: boolean): AgentProfile[] {
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    fetchAgentProfiles()
      .then((p) => {
        if (!cancelled) setProfiles(p);
      })
      // No profiles only means the MultiSelect offers the routed team alone.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return profiles;
}

export interface AgentRouteState {
  route: AgentRouteResponse | null;
  loading: boolean;
  error: string | null;
}

/** The team the router would pick for `question`, refreshed as the user
 *  types (debounced; a stale answer never replaces a newer one). */
export function useAgentRoute(
  dashboardId: string,
  question: string,
  enabled: boolean,
): AgentRouteState {
  const { llmKey } = useAISession(dashboardId);
  const [state, setState] = useState<AgentRouteState>({ route: null, loading: false, error: null });
  const text = question.trim();

  useEffect(() => {
    if (!enabled || text.length < MIN_ROUTE_CHARS) {
      setState((s) => (s.loading ? { ...s, loading: false } : s));
      return;
    }
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      setState((s) => ({ ...s, loading: true, error: null }));
      routeAgentRun({ dashboard_id: dashboardId, question: text }, llmKey || null, abort.signal)
        .then((route) => setState({ route, loading: false, error: null }))
        .catch((e) => {
          if (abort.signal.aborted) return;
          setState((s) => ({
            ...s,
            loading: false,
            error: e instanceof Error ? e.message : String(e),
          }));
        });
    }, ROUTE_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      abort.abort();
    };
  }, [dashboardId, text, enabled, llmKey]);

  return state;
}

export interface AgentRunOptions {
  team?: string[];
  budgetUsd?: number;
}

/** One agent-team run at a time on a dashboard: start it, follow its trace,
 *  cancel it, or reopen a past one. */
export function useAgentRun(dashboardId: string) {
  const { llmKey } = useAISession(dashboardId);
  const [trace, setTrace] = useState<AgentRunTraceState>(EMPTY_AGENT_TRACE);
  const [question, setQuestion] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<AgentRunSummary[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const runIdRef = useRef<string | null>(null);

  const run = useCallback(
    async (text: string, opts: AgentRunOptions = {}) => {
      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;
      runIdRef.current = null;
      setPending(true);
      setError(null);
      setQuestion(text);
      setTrace({ ...EMPTY_AGENT_TRACE, status: 'running' });
      try {
        await streamAgentRun(
          {
            dashboard_id: dashboardId,
            question: text,
            ...(opts.team && opts.team.length ? { team: opts.team } : {}),
            ...(opts.budgetUsd != null ? { budget_usd: opts.budgetUsd } : {}),
          },
          llmKey || null,
          {
            signal: abort.signal,
            onEvent: (event) => {
              if (event.type === 'run_started') runIdRef.current = event.data.run_id;
              setTrace((s) => reduceAgentRunEvent(s, event));
            },
          },
        );
      } catch (e) {
        if (!abort.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (abortRef.current === abort) {
          abortRef.current = null;
          setPending(false);
          // A stream that closed without run_finished did not finish.
          setTrace((s) => (s.status === 'running' ? { ...s, status: 'failed' } : s));
        }
      }
    },
    [dashboardId, llmKey],
  );

  /** Stops the run server-side (the stream alone would leave the agents
   *  spending), then drops the stream. */
  const cancel = useCallback(async () => {
    const runId = runIdRef.current;
    if (runId) await cancelAgentRun(runId).catch(() => undefined);
    abortRef.current?.abort();
    abortRef.current = null;
    setPending(false);
    setTrace((s) => ({ ...s, status: 'cancelled' }));
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await fetchAgentRuns(dashboardId));
    } catch {
      setHistory([]);
    }
  }, [dashboardId]);

  const open = useCallback(async (runId: string) => {
    try {
      const stored = await fetchAgentRun(runId);
      setTrace(agentRunToTrace(stored));
      setQuestion(stored.question);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  // Leaving the dashboard stops following the stream (the run itself goes on
  // server-side and stays listed in the history).
  useEffect(() => () => abortRef.current?.abort(), []);

  return { trace, question, pending, error, run, cancel, history, loadHistory, open };
}
