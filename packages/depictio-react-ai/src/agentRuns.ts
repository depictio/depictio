/**
 * Pure state for agent-team runs: the trace a run's SSE events fold into,
 * the same trace rebuilt from a stored run, and the thread helpers the
 * comments drawer uses to filter and bulk-accept a run's proposals.
 *
 * No React here, so every rule is unit-tested in node.
 */

import type { CommentThread } from 'depictio-react-core';

import type {
  AgentEvidenceRef,
  AgentRouting,
  AgentRun,
  AgentRunEvent,
  AgentRunOutputs,
  AgentRunStatus,
  AgentRunSummary,
  AgentStatus,
  AgentTeamMember,
  AgentVerdict,
} from './types';

export interface TraceToolCall {
  call_id: string;
  tool: string;
  args?: unknown;
  /** Undefined while the call is in flight. */
  ok?: boolean;
  truncated?: boolean;
  summary?: string | null;
}

export interface TraceFinding {
  finding_id: string;
  title: string;
  detail?: string | null;
  component_index?: string | null;
  confidence: 'low' | 'medium' | 'high';
  evidence: AgentEvidenceRef[];
}

export interface TraceThread {
  thread_id: string;
  kind: 'comment' | 'question';
  component_index?: string | null;
  finding_id?: string | null;
}

export interface TraceVerdict {
  verdict: AgentVerdict;
  reason?: string | null;
  agent_id?: string;
}

/** One agent's lane: what it called, found and wrote. */
export interface AgentLane {
  agent_id: string;
  role?: string;
  topic?: string | null;
  status: 'running' | AgentStatus;
  summary?: string | null;
  /** What the agent produced, by kind, once it finished. */
  counts?: Record<string, number>;
  toolCalls: TraceToolCall[];
  findings: TraceFinding[];
  threads: TraceThread[];
  reportIds: string[];
  errors: string[];
}

export interface AgentRunTraceState {
  runId: string | null;
  status: 'idle' | AgentRunStatus;
  team: AgentTeamMember[];
  routing: AgentRouting | null;
  budget: {
    spent_usd: number;
    limit_usd: number | null;
    tool_calls: number;
    max_tool_calls: number | null;
  };
  lanes: AgentLane[];
  /** Verdicts by finding id. Kept apart from the lanes: the skeptic judges
   *  findings of other agents, and a verdict may name one not seen yet. */
  verdicts: Record<string, TraceVerdict>;
  /** Run-level errors (those naming no agent). */
  errors: string[];
  outputs: AgentRunOutputs | null;
}

export const EMPTY_AGENT_TRACE: AgentRunTraceState = {
  runId: null,
  status: 'idle',
  team: [],
  routing: null,
  budget: { spent_usd: 0, limit_usd: null, tool_calls: 0, max_tool_calls: null },
  lanes: [],
  verdicts: {},
  errors: [],
  outputs: null,
};

/** `analyst/qc@1` -> role `analyst`, topic `qc`. */
export function splitAgentId(agentId: string): { role: string; topic: string | null } {
  const bare = agentId.split('@')[0];
  const slash = bare.indexOf('/');
  return slash === -1
    ? { role: bare, topic: null }
    : { role: bare.slice(0, slash), topic: bare.slice(slash + 1) || null };
}

function toMember(m: AgentTeamMember | string): AgentTeamMember {
  if (typeof m !== 'string') return m;
  const { role, topic } = splitAgentId(m);
  return { agent_id: m, role, topic };
}

function emptyLane(agent_id: string, role?: string, topic?: string | null): AgentLane {
  const parsed = splitAgentId(agent_id);
  return {
    agent_id,
    role: role ?? parsed.role,
    topic: topic ?? parsed.topic,
    status: 'running',
    toolCalls: [],
    findings: [],
    threads: [],
    reportIds: [],
    errors: [],
  };
}

/** Apply `fn` to the lane of `agentId`, creating it when an event names an
 *  agent whose `agent_started` was missed. */
function withLane(
  state: AgentRunTraceState,
  agentId: string,
  fn: (lane: AgentLane) => AgentLane,
): AgentRunTraceState {
  const i = state.lanes.findIndex((l) => l.agent_id === agentId);
  const lanes = [...state.lanes];
  if (i === -1) lanes.push(fn(emptyLane(agentId)));
  else lanes[i] = fn(lanes[i]);
  return { ...state, lanes };
}

function normaliseOutputs(o: Partial<AgentRunOutputs> | null | undefined): AgentRunOutputs {
  return {
    thread_ids: o?.thread_ids ?? [],
    report_id: o?.report_id ?? null,
    draft_ids: o?.draft_ids ?? [],
  };
}

/** Fold one SSE event into the trace. Unknown events leave it unchanged. */
export function reduceAgentRunEvent(
  state: AgentRunTraceState,
  event: AgentRunEvent,
): AgentRunTraceState {
  switch (event.type) {
    case 'run_started': {
      const d = event.data;
      return {
        ...state,
        runId: d.run_id,
        status: 'running',
        team: (d.team ?? []).map(toMember),
        routing: d.routing ?? null,
        budget: {
          ...state.budget,
          limit_usd: d.budget?.limit_usd ?? state.budget.limit_usd,
          max_tool_calls: d.budget?.max_tool_calls ?? state.budget.max_tool_calls,
        },
      };
    }
    case 'agent_started': {
      const d = event.data;
      return withLane(state, d.agent_id, (lane) => ({
        ...lane,
        role: d.role ?? lane.role,
        topic: d.topic ?? lane.topic,
        status: 'running',
      }));
    }
    case 'tool_call': {
      const d = event.data;
      return withLane(state, d.agent_id, (lane) => ({
        ...lane,
        toolCalls: [...lane.toolCalls, { call_id: d.call_id, tool: d.tool, args: d.args }],
      }));
    }
    case 'tool_result': {
      const d = event.data;
      return withLane(state, d.agent_id, (lane) => {
        const known = lane.toolCalls.some((c) => c.call_id === d.call_id);
        const result = { ok: d.ok, truncated: d.truncated, summary: d.summary };
        return {
          ...lane,
          toolCalls: known
            ? lane.toolCalls.map((c) => (c.call_id === d.call_id ? { ...c, ...result } : c))
            : [...lane.toolCalls, { call_id: d.call_id, tool: '?', ...result }],
        };
      });
    }
    case 'finding': {
      const { agent_id, ...finding } = event.data;
      return withLane(state, agent_id, (lane) => ({
        ...lane,
        findings: [
          ...lane.findings.filter((f) => f.finding_id !== finding.finding_id),
          { ...finding, evidence: finding.evidence ?? [] },
        ],
      }));
    }
    case 'verdict': {
      const d = event.data;
      return {
        ...state,
        verdicts: {
          ...state.verdicts,
          [d.finding_id]: { verdict: d.verdict, reason: d.reason, agent_id: d.agent_id },
        },
      };
    }
    case 'thread_created': {
      const { agent_id, ...thread } = event.data;
      return withLane(state, agent_id, (lane) => ({
        ...lane,
        threads: [...lane.threads.filter((t) => t.thread_id !== thread.thread_id), thread],
      }));
    }
    case 'report_created': {
      const d = event.data;
      return withLane(state, d.agent_id, (lane) => ({
        ...lane,
        reportIds: lane.reportIds.includes(d.report_id)
          ? lane.reportIds
          : [...lane.reportIds, d.report_id],
      }));
    }
    case 'budget': {
      const d = event.data;
      return {
        ...state,
        budget: {
          spent_usd: d.spent_usd ?? state.budget.spent_usd,
          limit_usd: d.limit_usd ?? state.budget.limit_usd,
          tool_calls: d.tool_calls ?? state.budget.tool_calls,
          max_tool_calls: d.max_tool_calls ?? state.budget.max_tool_calls,
        },
      };
    }
    case 'agent_finished': {
      const d = event.data;
      return withLane(state, d.agent_id, (lane) => ({
        ...lane,
        status: d.status,
        summary: d.summary ?? lane.summary,
        counts: d.counts ?? lane.counts,
      }));
    }
    case 'error': {
      const d = event.data;
      const detail = String(d.detail ?? 'unknown error');
      if (d.agent_id) {
        return withLane(state, d.agent_id, (lane) => ({
          ...lane,
          errors: [...lane.errors, detail],
        }));
      }
      return { ...state, errors: [...state.errors, detail] };
    }
    case 'run_finished': {
      const d = event.data;
      return {
        ...state,
        runId: d.run_id ?? state.runId,
        status: d.status,
        outputs: normaliseOutputs(d.outputs),
        // A lane still "running" when the run ends did not report back.
        lanes: state.lanes.map((l) =>
          l.status === 'running' ? { ...l, status: d.status === 'budget' ? 'budget' : 'error' } : l,
        ),
      };
    }
    default:
      return state;
  }
}

/** The verdicts `agentId` gave, in the order its findings were listed, with
 *  the title of the finding each one judges. */
export function laneVerdicts(
  state: AgentRunTraceState,
  agentId: string,
): { finding_id: string; title: string; verdict: TraceVerdict }[] {
  const titles = new Map<string, string>();
  state.lanes.forEach((l) => l.findings.forEach((f) => titles.set(f.finding_id, f.title)));
  return Object.entries(state.verdicts)
    .filter(([, v]) => v.agent_id === agentId)
    .map(([finding_id, verdict]) => ({
      finding_id,
      title: titles.get(finding_id) ?? finding_id,
      verdict,
    }));
}

/** The id a run row carries (`id` on stored documents, `run_id` on events). */
export function agentRunId(run: Pick<AgentRunSummary, 'id' | 'run_id'>): string {
  return run.id ?? run.run_id ?? '';
}

const RUN_LABEL_QUESTION_CHARS = 40;

/** A run as one line of a picker: the question (cut), the date and time it
 *  started, the team size and, unless it completed, its status. Runs of the
 *  same question stay apart by their time. */
export function agentRunLabel(run: AgentRunSummary): string {
  const q = run.question.trim();
  const question =
    q.length > RUN_LABEL_QUESTION_CHARS ? `${q.slice(0, RUN_LABEL_QUESTION_CHARS).trimEnd()}…` : q;
  const at = new Date(run.created_at);
  const pad = (n: number) => String(n).padStart(2, '0');
  const when = Number.isNaN(at.getTime())
    ? ''
    : `${at.toLocaleDateString()} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
  const team = run.team?.length ?? 0;
  return [
    question || `Run ${agentRunId(run).slice(0, 8)}`,
    when,
    team ? `${team} agents` : '',
    run.status !== 'complete' ? run.status : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

/** The report of a finished trace: the run's output, else the last one a
 *  lane announced. */
export function traceReportId(state: AgentRunTraceState): string | null {
  if (state.outputs?.report_id) return state.outputs.report_id;
  const ids = state.lanes.flatMap((l) => l.reportIds);
  return ids.length ? ids[ids.length - 1] : null;
}

/** Rebuild the trace from a stored run: one opened from history, or a run
 *  still going that is followed by polling. */
export function agentRunToTrace(run: AgentRun): AgentRunTraceState {
  const verdicts: Record<string, TraceVerdict> = {};
  (run.verdicts ?? []).forEach((v) => {
    verdicts[v.finding_id] = { verdict: v.verdict, reason: v.reason, agent_id: v.agent_id };
  });
  const lanes: AgentLane[] = (run.agents ?? []).map((a) => {
    const lane = emptyLane(a.agent_id, a.role, a.topic);
    (a.findings ?? []).forEach((f) => {
      if (f.verdict && !verdicts[f.finding_id]) {
        verdicts[f.finding_id] = { verdict: f.verdict, reason: f.verdict_reason };
      }
    });
    return {
      ...lane,
      // A lane still running is shown so only while the run itself is.
      status:
        a.status === 'running' && run.status === 'running'
          ? 'running'
          : a.status && a.status !== 'running'
            ? a.status
            : 'ok',
      // Runs stored before counts became a field carry them in the prose.
      summary: a.summary?.replace(/\s*\(\d+ finding\(s\) kept\)$/, ''),
      counts: a.counts ?? undefined,
      toolCalls: (a.tool_calls ?? []).map((c) => ({
        call_id: c.call_id,
        tool: c.tool,
        args: c.args,
        ok: c.ok ?? undefined,
        truncated: c.truncated,
        summary: c.summary ?? c.error ?? null,
      })),
      findings: (a.findings ?? []).map((f) => ({
        finding_id: f.finding_id,
        title: f.title,
        detail: f.detail,
        component_index: f.component_index,
        confidence: f.confidence,
        evidence: f.evidence ?? [],
      })),
    };
  });
  (run.threads ?? []).forEach((t) => {
    const owner = lanes.find((l) => l.agent_id === t.agent_id) ?? lanes[lanes.length - 1];
    if (!owner) return;
    owner.threads.push({
      thread_id: t.thread_id,
      kind: t.kind ?? 'comment',
      component_index: t.component_index,
      finding_id: t.finding_id,
    });
  });
  const b = run.budget ?? {};
  return {
    runId: agentRunId(run),
    status: run.status,
    team: (run.team ?? []).map(toMember),
    routing: run.routing ?? null,
    budget: {
      spent_usd: b.spent_usd ?? 0,
      limit_usd: b.limit_usd ?? null,
      tool_calls: b.tool_calls ?? 0,
      max_tool_calls: b.max_tool_calls ?? null,
    },
    lanes,
    verdicts,
    errors: [],
    outputs: normaliseOutputs(run.outputs),
  };
}

// ---------- Threads of a run (comments drawer) ----------

/** The run a thread was written by, from the thread itself or its author. */
export function threadRunId(thread: CommentThread): string | null {
  return thread.run_id ?? thread.created_by.agent?.run_id ?? null;
}

/** Distinct run ids among `threads`, in first-seen order. */
export function runIdsOf(threads: CommentThread[]): string[] {
  const seen = new Set<string>();
  threads.forEach((t) => {
    const id = threadRunId(t);
    if (id) seen.add(id);
  });
  return [...seen];
}

export interface ThreadFilter {
  /** Keep only threads of this run (null: every thread). */
  runId?: string | null;
  /** Keep only question threads. */
  questionsOnly?: boolean;
}

export function filterThreads(threads: CommentThread[], f: ThreadFilter): CommentThread[] {
  return threads.filter(
    (t) =>
      (!f.runId || threadRunId(t) === f.runId) && (!f.questionsOnly || t.kind === 'question'),
  );
}

/** Verdict of each thread the run wrote, by thread id, when the stored run
 *  says which finding a thread came from. */
export function threadVerdicts(run: AgentRun | null | undefined): Record<string, AgentVerdict> {
  if (!run) return {};
  const trace = agentRunToTrace(run);
  const out: Record<string, AgentVerdict> = {};
  const link = (threadId: string, findingId: string | null | undefined) => {
    const v = findingId ? trace.verdicts[findingId]?.verdict : undefined;
    if (v) out[threadId] = v;
  };
  (run.threads ?? []).forEach((t) => link(t.thread_id, t.finding_id));
  (run.agents ?? []).forEach((a) =>
    (a.findings ?? []).forEach((f) => (f.thread_ids ?? []).forEach((id) => link(id, f.finding_id))),
  );
  return out;
}

/** Proposed agent threads of `runId` that "Accept all confirmed" accepts.
 *
 *  The team only turns confirmed findings into threads, so every proposal of
 *  the run qualifies by default. When the stored run links a thread to a
 *  finding the skeptic weakened or refuted (a thread written before the
 *  verdict, or by an MCP client), that thread is left for a person. */
export function acceptableThreads(
  threads: CommentThread[],
  runId: string,
  run?: AgentRun | null,
): CommentThread[] {
  const verdicts = threadVerdicts(run);
  return threads.filter(
    (t) =>
      t.status === 'proposed' &&
      t.created_by.kind === 'agent' &&
      threadRunId(t) === runId &&
      (verdicts[t.id] === undefined || verdicts[t.id] === 'confirmed'),
  );
}
