/**
 * AI session store.
 *
 * Per the v1 product decision: the LLM API key is set per-dashboard from
 * the Settings Drawer and lives ONLY in this in-memory Zustand store.
 * Never written to localStorage / sessionStorage / cookies. A page
 * reload clears it; opening a new tab requires re-entering it.
 *
 * Each dashboard owns its own AISession (transcript, key, model). When
 * the user navigates away, the session is left intact in memory so they
 * can come back to it within the same SPA session.
 */

import { create } from 'zustand';

import type { AnalysisResult, ExecutionStep, PlotSuggestion } from './types';

export interface AIChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  steps?: ExecutionStep[];
  /** Filled in once the analyze stream produces a final result. */
  result?: AnalysisResult;
  /** Filled in for prompt-driven figure-creation messages. */
  suggestion?: PlotSuggestion;
  ts: number;
}

export interface AISession {
  llmKey: string;
  /** Provider/model string passed to LiteLLM, e.g.
   *  "openrouter/anthropic/claude-sonnet-4-6". Empty = use server default. */
  model: string;
  messages: AIChatMessage[];
  /** Set while a request is in flight so we can show a spinner / cancel. */
  pending: boolean;
  /** AbortController bound to the current in-flight request (if any). */
  abort: AbortController | null;
}

interface State {
  sessions: Record<string, AISession>;
}

interface Actions {
  ensureSession: (dashboardId: string) => AISession;
  setKey: (dashboardId: string, key: string) => void;
  setModel: (dashboardId: string, model: string) => void;
  clearKey: (dashboardId: string) => void;
  appendMessage: (dashboardId: string, msg: AIChatMessage) => void;
  patchMessage: (
    dashboardId: string,
    messageId: string,
    patch: Partial<AIChatMessage>,
  ) => void;
  setPending: (
    dashboardId: string,
    pending: boolean,
    abort?: AbortController | null,
  ) => void;
  reset: (dashboardId: string) => void;
}

const empty = (): AISession => ({
  llmKey: '',
  model: '',
  messages: [],
  pending: false,
  abort: null,
});

export const useAIStore = create<State & Actions>((set, get) => ({
  sessions: {},

  ensureSession: (dashboardId) => {
    const existing = get().sessions[dashboardId];
    if (existing) return existing;
    const created = empty();
    set((s) => ({ sessions: { ...s.sessions, [dashboardId]: created } }));
    return created;
  },

  setKey: (dashboardId, key) =>
    set((s) => {
      const cur = s.sessions[dashboardId] ?? empty();
      return { sessions: { ...s.sessions, [dashboardId]: { ...cur, llmKey: key } } };
    }),

  setModel: (dashboardId, model) =>
    set((s) => {
      const cur = s.sessions[dashboardId] ?? empty();
      return { sessions: { ...s.sessions, [dashboardId]: { ...cur, model } } };
    }),

  clearKey: (dashboardId) =>
    set((s) => {
      const cur = s.sessions[dashboardId] ?? empty();
      return { sessions: { ...s.sessions, [dashboardId]: { ...cur, llmKey: '' } } };
    }),

  appendMessage: (dashboardId, msg) =>
    set((s) => {
      const cur = s.sessions[dashboardId] ?? empty();
      return {
        sessions: {
          ...s.sessions,
          [dashboardId]: { ...cur, messages: [...cur.messages, msg] },
        },
      };
    }),

  patchMessage: (dashboardId, messageId, patch) =>
    set((s) => {
      const cur = s.sessions[dashboardId];
      if (!cur) return s;
      return {
        sessions: {
          ...s.sessions,
          [dashboardId]: {
            ...cur,
            messages: cur.messages.map((m) =>
              m.id === messageId ? { ...m, ...patch } : m,
            ),
          },
        },
      };
    }),

  setPending: (dashboardId, pending, abort = null) =>
    set((s) => {
      const cur = s.sessions[dashboardId] ?? empty();
      return {
        sessions: {
          ...s.sessions,
          [dashboardId]: { ...cur, pending, abort: pending ? abort : null },
        },
      };
    }),

  reset: (dashboardId) =>
    set((s) => ({ sessions: { ...s.sessions, [dashboardId]: empty() } })),
}));

/** Selector helper: returns the session for a given dashboard, creating
 *  an empty one if it doesn't exist yet. Use inside a component to read
 *  the current session reactively. */
export function useAISession(dashboardId: string): AISession {
  return useAIStore(
    (s) => s.sessions[dashboardId] ?? empty(),
  );
}
