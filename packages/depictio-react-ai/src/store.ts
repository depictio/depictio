/**
 * AI session store.
 *
 * Per-dashboard state: transcript, llm key, model selection.
 *
 * Persistence: only the `llmKey` and `model` fields per dashboard
 * survive a reload. We use *direct* localStorage I/O instead of
 * zustand/persist middleware — easier to verify in DevTools, no
 * hydration-timing surprises, and we sidestep any version-specific
 * middleware quirks. Writes happen synchronously in `setKey` /
 * `setModel`; reads happen once at module load to seed initial state.
 *
 * The transcript stays in memory because it can be re-streamed and
 * would otherwise grow unbounded in localStorage.
 *
 * Storage key: ``depictio.ai.creds`` (object form):
 *   { [dashboardId]: { llmKey: string; model: string } }
 *
 * Persisting the key is a deliberate trade-off the user requested for
 * ergonomics; it inherits the same security profile as any other
 * JWT-style credential the app stores.
 */

import { create } from 'zustand';

import type { AnalysisResult, ExecutionStep, PlotSuggestion } from './types';

const STORAGE_KEY = 'depictio.ai.creds';

interface PersistedCreds {
  llmKey: string;
  model: string;
}

type PersistedShape = Record<string, PersistedCreds>;

function readPersisted(): PersistedShape {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      if (parsed && typeof parsed === 'object') {
        const out: PersistedShape = {};
        for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
          if (v && typeof v === 'object') {
            const c = v as Partial<PersistedCreds>;
            out[k] = {
              llmKey: typeof c.llmKey === 'string' ? c.llmKey : '',
              model: typeof c.model === 'string' ? c.model : '',
            };
          }
        }
        return out;
      }
    }

    // Backward-compat: a previous build used zustand's persist middleware
    // under the key ``depictio.ai.session`` with shape
    // ``{ state: { sessions: { id: { llmKey, model } } }, version: ... }``.
    // Migrate it on first read so existing users don't have to re-enter
    // their key, then drop the legacy entry to keep storage tidy.
    const legacy = window.localStorage.getItem('depictio.ai.session');
    if (legacy) {
      const parsed = JSON.parse(legacy) as {
        state?: { sessions?: Record<string, Partial<PersistedCreds>> };
      };
      const sessions = parsed?.state?.sessions ?? {};
      const out: PersistedShape = {};
      for (const [k, v] of Object.entries(sessions)) {
        out[k] = {
          llmKey: typeof v?.llmKey === 'string' ? v.llmKey : '',
          model: typeof v?.model === 'string' ? v.model : '',
        };
      }
      if (Object.keys(out).length > 0) {
        writePersisted(out);
      }
      window.localStorage.removeItem('depictio.ai.session');
      return out;
    }

    return {};
  } catch {
    return {};
  }
}

function writePersisted(next: PersistedShape): void {
  if (typeof window === 'undefined') return;
  try {
    // Drop entries with empty creds so we don't leave stale {} blobs.
    const trimmed: PersistedShape = {};
    for (const [k, v] of Object.entries(next)) {
      if (v.llmKey || v.model) trimmed[k] = v;
    }
    if (Object.keys(trimmed).length === 0) {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
    }
  } catch {
    // localStorage can throw under quota / privacy modes — silently no-op.
  }
}

function patchPersisted(
  dashboardId: string,
  patch: Partial<PersistedCreds>,
): void {
  const cur = readPersisted();
  const existing = cur[dashboardId] ?? { llmKey: '', model: '' };
  cur[dashboardId] = { ...existing, ...patch };
  writePersisted(cur);
}

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

/** Build the initial sessions map by hydrating creds from localStorage. */
function initialSessions(): Record<string, AISession> {
  const persisted = readPersisted();
  const out: Record<string, AISession> = {};
  for (const [id, c] of Object.entries(persisted)) {
    out[id] = { ...empty(), llmKey: c.llmKey, model: c.model };
  }
  return out;
}

export const useAIStore = create<State & Actions>((set, get) => ({
  sessions: initialSessions(),

  ensureSession: (dashboardId) => {
    const existing = get().sessions[dashboardId];
    if (existing) return existing;
    const created = empty();
    set((s) => ({ sessions: { ...s.sessions, [dashboardId]: created } }));
    return created;
  },

  setKey: (dashboardId, key) => {
    patchPersisted(dashboardId, { llmKey: key });
    set((s) => {
      const cur = s.sessions[dashboardId] ?? empty();
      return {
        sessions: { ...s.sessions, [dashboardId]: { ...cur, llmKey: key } },
      };
    });
  },

  setModel: (dashboardId, model) => {
    patchPersisted(dashboardId, { model });
    set((s) => {
      const cur = s.sessions[dashboardId] ?? empty();
      return {
        sessions: { ...s.sessions, [dashboardId]: { ...cur, model } },
      };
    });
  },

  clearKey: (dashboardId) => {
    patchPersisted(dashboardId, { llmKey: '' });
    set((s) => {
      const cur = s.sessions[dashboardId] ?? empty();
      return {
        sessions: { ...s.sessions, [dashboardId]: { ...cur, llmKey: '' } },
      };
    });
  },

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
    set((s) => {
      const cur = s.sessions[dashboardId];
      // Reset = clear conversation, NOT credentials. The user manages the
      // key explicitly via the X button on AIKeySection (which calls
      // clearKey and removes the localStorage entry).
      return {
        sessions: {
          ...s.sessions,
          [dashboardId]: {
            ...empty(),
            llmKey: cur?.llmKey ?? '',
            model: cur?.model ?? '',
          },
        },
      };
    }),
}));

/** Selector helper: returns the session for a given dashboard, or a stable
 *  frozen empty object when none exists. Do NOT inline a fresh literal
 *  here — it would re-trigger renders every cycle (see EMPTY_SESSION). */
export function useAISession(dashboardId: string): AISession {
  return useAIStore((s) => s.sessions[dashboardId] ?? EMPTY_SESSION);
}
