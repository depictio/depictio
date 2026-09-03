/**
 * AI session store.
 *
 * Per-dashboard state: transcript, llm key, model selection.
 *
 * It also holds the one whole-dashboard generation run, which is not
 * per-dashboard (no dashboard exists yet) and, unlike everything else here,
 * outlives the component that started it: a run takes minutes and the dialog
 * it runs in is closed and reopened while it streams. See `GenerationRun`.
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

import type {
  AnalysisResult,
  AnalyzeMode,
  BudgetTick,
  DashboardPlan,
  ExecutionStep,
  GenerateDashboardRequest,
  GeneratedComponentEvent,
  GeneratedDashboardEvent,
} from './types';

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
  /** Which prompt level ran this exchange — set on both messages at send
   *  time so the transcript can label an exchange before (and even
   *  without) a final result. */
  mode?: AnalyzeMode;
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

/** Live state of one whole-dashboard generation call, as its stream fills
 *  it: the status line, the plan, the budget countdown, the per-component
 *  outcomes and finally the saved draft. */
export interface GenerateDashboardRunState {
  status: string;
  plan: DashboardPlan | null;
  budget: BudgetTick | null;
  /** One entry per reported component tag, the latest event winning. */
  components: GeneratedComponentEvent[];
  dashboard: GeneratedDashboardEvent | null;
  error: string | null;
}

/** Stable empty run state. Frozen and shared for the same reason as
 *  EMPTY_SESSION: a fresh literal per selector call would re-render forever. */
export const EMPTY_GENERATION: GenerateDashboardRunState = Object.freeze({
  status: '',
  plan: null,
  budget: null,
  components: [],
  dashboard: null,
  error: null,
}) as GenerateDashboardRunState;

/** What the calls of one generation session have spent between them.
 *  Reviewing a plan before building it costs two calls and each call resets
 *  the run state, so the first one's spend only survives here. */
export interface RunSpend {
  /** Calls counted, the one in flight excluded (it is still on the budget). */
  runs: number;
  tokens: number;
  seconds: number;
  /** Null when no call could be priced. */
  cost: number | null;
}

export const EMPTY_SPEND: RunSpend = Object.freeze({
  runs: 0,
  tokens: 0,
  seconds: 0,
  cost: null,
}) as RunSpend;

/**
 * The whole-dashboard generation run: everything about it that must outlive
 * the panel, which is unmounted every time the New Dashboard dialog closes.
 *
 * One slot, so one run is tracked at a time. Deliberately not persisted: an
 * AbortController and an open stream cannot survive a reload, and a "still
 * generating" flag restored without the fetch behind it would be a lie.
 */
export interface GenerationRun {
  /** New per call. A listener uses it to tell a fresh run from a re-render
   *  of the one it has already reacted to. */
  id: string;
  /** What this call was started with. The panel restores its form from it
   *  after a remount, and the fill phase re-sends it with the approved plan. */
  request: GenerateDashboardRequest;
  /** Label of the project being generated into, so a host that has no
   *  project list to hand can still name the run. */
  projectName: string;
  /** This call asked for a plan and nothing else, so a plan that arrives is
   *  waiting for the user's verdict rather than being filled. */
  planPhase: boolean;
  /** True while the stream is open. The only flag anything should read to
   *  decide whether a run is going. */
  pending: boolean;
  /** Bound to the open stream. Only an explicit stop aborts it: unmounting
   *  the panel must leave the run alone. */
  abort: AbortController | null;
  /** Spend of the calls before this one. */
  spent: RunSpend;
  state: GenerateDashboardRunState;
}

/** The planning call ended with a plan and nothing built: the run stops
 *  there until the user says what to do with it. The panel and any host
 *  affordance both read a run through this, so "still going" means one
 *  thing in both places. */
export function awaitingVerdict(run: GenerationRun | null): boolean {
  if (!run || run.pending || !run.planPhase) return false;
  return Boolean(run.state.plan) && !run.state.error && !run.state.dashboard;
}

/** Fold an ending call's budget into what the session had already spent. */
function bankSpend(prev: GenerationRun | null): RunSpend {
  if (!prev) return EMPTY_SPEND;
  const ending = prev.state.budget;
  if (!ending) return prev.spent;
  return {
    runs: prev.spent.runs + 1,
    tokens: prev.spent.tokens + ending.tokens_used,
    seconds: prev.spent.seconds + ending.seconds,
    cost:
      typeof ending.cost_usd === 'number'
        ? (prev.spent.cost ?? 0) + ending.cost_usd
        : prev.spent.cost,
  };
}

function newRunId(): string {
  return `gen_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

interface State {
  sessions: Record<string, AISession>;
  /** The whole-dashboard generation run, null until one is started. */
  generation: GenerationRun | null;
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
  /** Drop specific messages (one exchange = its user + assistant ids). */
  removeMessages: (dashboardId: string, messageIds: string[]) => void;
  reset: (dashboardId: string) => void;
  /** Take the generation slot for a new call. Returns the run id to patch
   *  under, or null when the slot is busy (see the refusal rule on the
   *  implementation). */
  startGeneration: (args: {
    request: GenerateDashboardRequest;
    projectName: string;
    planPhase: boolean;
    abort: AbortController;
  }) => string | null;
  /** Merge stream events into the run state, ignoring anything arriving
   *  under an id that is no longer the current run. */
  patchGeneration: (runId: string, patch: Partial<GenerateDashboardRunState>) => void;
  /** The stream is over (finished, failed or aborted): drop the pending flag
   *  and the abort handle, keep what the run produced. */
  endGeneration: (runId: string) => void;
  /** Abort the open stream, which is what "Stop generating" does. */
  stopGeneration: () => void;
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
  generation: null,

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

  removeMessages: (dashboardId, messageIds) =>
    set((s) => {
      const cur = s.sessions[dashboardId];
      if (!cur) return s;
      const drop = new Set(messageIds);
      return {
        sessions: {
          ...s.sessions,
          [dashboardId]: {
            ...cur,
            messages: cur.messages.filter((m) => !drop.has(m.id)),
          },
        },
      };
    }),

  startGeneration: ({ request, projectName, planPhase, abort }) => {
    // Refuse rather than replace: a run in flight owns the slot, and taking
    // it from under an open stream would interleave two streams into one
    // state. The panel disables its button while pending, so this only
    // fires for a caller the panel does not own (a second tab of the
    // dialog, a host-level retry).
    const current = get().generation;
    if (current?.pending) return null;
    const id = newRunId();
    set({
      generation: {
        id,
        request,
        projectName,
        planPhase,
        pending: true,
        abort,
        // Each call resets the run state, so the session total the panel
        // shows spans both phases only because the ending call is banked here.
        spent: bankSpend(current),
        state: { ...EMPTY_GENERATION, status: 'starting' },
      },
    });
    return id;
  },

  patchGeneration: (runId, patch) =>
    set((s) => {
      const cur = s.generation;
      if (!cur || cur.id !== runId) return s;
      return { generation: { ...cur, state: { ...cur.state, ...patch } } };
    }),

  endGeneration: (runId) =>
    set((s) => {
      const cur = s.generation;
      if (!cur || cur.id !== runId) return s;
      return { generation: { ...cur, pending: false, abort: null } };
    }),

  stopGeneration: () => {
    const cur = get().generation;
    if (!cur) return;
    cur.abort?.abort();
    // The stream's own `finally` also clears these, but a fetch that never
    // settles must not leave the flag stuck on.
    set({ generation: { ...cur, pending: false, abort: null } });
  },

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
