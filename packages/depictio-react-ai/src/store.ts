/**
 * AI session store.
 *
 * Per-dashboard state: transcript, llm key, model selection.
 *
 * Persistence (revised after v1 in-memory-only decision): only the
 * `llmKey` and `model` fields per dashboard survive a reload — the
 * transcript stays in memory because it can be re-streamed and would
 * otherwise grow unbounded in localStorage. Persisting the key is a
 * deliberate trade-off the user requested for ergonomics; it lives in
 * localStorage under `depictio.ai.session` and inherits the same
 * security profile as any other JWT-style credential the app stores.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

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

/** Stable singleton returned by `useAISession` when no session has been
 *  created yet for a dashboard id. Returning a fresh `empty()` literal here
 *  would change the selector's referential identity on every render and
 *  trigger React error #185 ("Maximum update depth exceeded") because
 *  Zustand's default equality is `Object.is`. */
const EMPTY_SESSION: AISession = Object.freeze({
  llmKey: '',
  model: '',
  messages: [],
  pending: false,
  abort: null,
}) as AISession;

export const useAIStore = create<State & Actions>()(
  persist(
    (set, get) => ({
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
          return {
            sessions: { ...s.sessions, [dashboardId]: { ...cur, llmKey: key } },
          };
        }),

      setModel: (dashboardId, model) =>
        set((s) => {
          const cur = s.sessions[dashboardId] ?? empty();
          return {
            sessions: { ...s.sessions, [dashboardId]: { ...cur, model } },
          };
        }),

      clearKey: (dashboardId) =>
        set((s) => {
          const cur = s.sessions[dashboardId] ?? empty();
          return {
            sessions: { ...s.sessions, [dashboardId]: { ...cur, llmKey: '' } },
          };
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
              [dashboardId]: {
                ...cur,
                pending,
                abort: pending ? abort : null,
              },
            },
          };
        }),

      reset: (dashboardId) =>
        set((s) => ({
          sessions: {
            ...s.sessions,
            [dashboardId]: {
              // Preserve key + model on reset so the user doesn't
              // have to re-enter their credential after clearing the
              // transcript. Reset = clear conversation, not creds.
              ...empty(),
              llmKey: s.sessions[dashboardId]?.llmKey ?? '',
              model: s.sessions[dashboardId]?.model ?? '',
            },
          },
        })),
    }),
    {
      name: 'depictio.ai.session',
      storage: createJSONStorage(() => localStorage),
      // Persist ONLY credentials per dashboard. Transcript can be
      // recomputed by re-running the prompt; AbortController references
      // are not serializable; pending must always start false on reload.
      partialize: (state) => ({
        sessions: Object.fromEntries(
          Object.entries(state.sessions).map(([id, s]) => [
            id,
            { llmKey: s.llmKey, model: s.model },
          ]),
        ) as Record<string, AISession>,
      }),
      // Hydration produces partial sessions (only llmKey + model). Fill
      // in the rest with empty defaults so consumers always see a
      // complete AISession shape.
      merge: (persistedState, currentState) => {
        const persisted =
          (persistedState as { sessions?: Record<string, Partial<AISession>> })
            ?.sessions ?? {};
        const merged: Record<string, AISession> = {};
        for (const [id, s] of Object.entries(persisted)) {
          merged[id] = {
            ...empty(),
            llmKey: s.llmKey ?? '',
            model: s.model ?? '',
          };
        }
        return { ...currentState, sessions: merged };
      },
    },
  ),
);

/** Selector helper: returns the session for a given dashboard, or a stable
 *  frozen empty object when none exists. Do NOT inline a fresh literal
 *  here — it would re-trigger renders every cycle (see EMPTY_SESSION). */
export function useAISession(dashboardId: string): AISession {
  return useAIStore((s) => s.sessions[dashboardId] ?? EMPTY_SESSION);
}
