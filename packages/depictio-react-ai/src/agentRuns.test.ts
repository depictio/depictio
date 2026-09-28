import { describe, expect, it } from 'vitest';
import type { CommentThread } from 'depictio-react-core';

import {
  acceptableThreads,
  agentRunToTrace,
  EMPTY_AGENT_TRACE,
  filterThreads,
  reduceAgentRunEvent,
  runIdsOf,
  splitAgentId,
  threadRunId,
  traceReportId,
} from './agentRuns';
import type { AgentRun, AgentRunEvent } from './types';

const fold = (events: AgentRunEvent[]) => events.reduce(reduceAgentRunEvent, EMPTY_AGENT_TRACE);

const RUN: AgentRunEvent[] = [
  {
    type: 'run_started',
    data: {
      run_id: 'r1',
      team: ['analyst/qc@1', { agent_id: 'skeptic@1', role: 'skeptic' }],
      routing: { method: 'rules' },
      budget: { limit_usd: 0.5, max_tool_calls: 40 },
    },
  },
  { type: 'agent_started', data: { agent_id: 'analyst/qc@1', role: 'analyst', topic: 'qc' } },
  { type: 'tool_call', data: { agent_id: 'analyst/qc@1', call_id: 'c1', tool: 'query_data' } },
  {
    type: 'tool_result',
    data: { agent_id: 'analyst/qc@1', call_id: 'c1', ok: true, summary: '12 rows' },
  },
  {
    type: 'finding',
    data: {
      agent_id: 'analyst/qc@1',
      finding_id: 'f1',
      title: 'Sample S3 fails QC',
      confidence: 'high',
      evidence: [{ call_id: 'c1', note: 'S3 has 2% mapped reads' }],
    },
  },
  { type: 'agent_finished', data: { agent_id: 'analyst/qc@1', status: 'ok', summary: 'done' } },
  { type: 'verdict', data: { finding_id: 'f1', verdict: 'confirmed', agent_id: 'skeptic@1' } },
  {
    type: 'thread_created',
    data: { agent_id: 'annotator@1', thread_id: 't1', kind: 'comment', finding_id: 'f1' },
  },
  { type: 'report_created', data: { agent_id: 'reporter@1', report_id: 'rep1' } },
  { type: 'budget', data: { spent_usd: 0.12, limit_usd: 0.5, tool_calls: 7 } },
];

describe('splitAgentId', () => {
  it('splits role, topic and version', () => {
    expect(splitAgentId('analyst/qc@1')).toEqual({ role: 'analyst', topic: 'qc' });
    expect(splitAgentId('skeptic@2')).toEqual({ role: 'skeptic', topic: null });
  });
});

describe('reduceAgentRunEvent', () => {
  it('folds a run into lanes, verdicts and budget', () => {
    const t = fold(RUN);
    expect(t.runId).toBe('r1');
    expect(t.status).toBe('running');
    expect(t.team.map((m) => m.agent_id)).toEqual(['analyst/qc@1', 'skeptic@1']);
    expect(t.team[0]).toMatchObject({ role: 'analyst', topic: 'qc' });
    const analyst = t.lanes.find((l) => l.agent_id === 'analyst/qc@1')!;
    expect(analyst.status).toBe('ok');
    expect(analyst.toolCalls).toEqual([
      { call_id: 'c1', tool: 'query_data', args: undefined, ok: true, truncated: undefined, summary: '12 rows' },
    ]);
    expect(analyst.findings[0].title).toBe('Sample S3 fails QC');
    expect(t.verdicts.f1.verdict).toBe('confirmed');
    // Agents seen only through later events still get a lane.
    expect(t.lanes.map((l) => l.agent_id)).toEqual(['analyst/qc@1', 'annotator@1', 'reporter@1']);
    expect(t.lanes[1].threads[0].thread_id).toBe('t1');
    expect(t.budget).toEqual({ spent_usd: 0.12, limit_usd: 0.5, tool_calls: 7, max_tool_calls: 40 });
    expect(traceReportId(t)).toBe('rep1');
  });

  it('marks lanes still running when the run ends', () => {
    const t = fold([
      ...RUN.slice(0, 3),
      { type: 'run_finished', data: { run_id: 'r1', status: 'budget', outputs: { thread_ids: ['t1'] } } },
    ]);
    expect(t.status).toBe('budget');
    expect(t.lanes[0].status).toBe('budget');
    expect(t.outputs).toEqual({ thread_ids: ['t1'], report_id: null, draft_ids: [] });
  });

  it('routes errors to their lane or to the run', () => {
    const t = fold([
      { type: 'error', data: { detail: 'boom', agent_id: 'analyst/qc@1' } },
      { type: 'error', data: { detail: 'run-level' } },
    ]);
    expect(t.lanes[0].errors).toEqual(['boom']);
    expect(t.errors).toEqual(['run-level']);
  });

  it('keeps a tool result whose call was not seen', () => {
    const t = fold([
      { type: 'tool_result', data: { agent_id: 'a', call_id: 'x', ok: false, summary: 'denied' } },
    ]);
    expect(t.lanes[0].toolCalls[0]).toMatchObject({ call_id: 'x', ok: false, summary: 'denied' });
  });

  it('replaces a finding re-emitted with the same id', () => {
    const f = RUN[4];
    const t = fold([f, f]);
    expect(t.lanes[0].findings).toHaveLength(1);
  });
});

function thread(
  id: string,
  opts: { run?: string | null; status?: CommentThread['status']; kind?: 'comment' | 'question'; agent?: boolean; runOnAuthor?: boolean } = {},
): CommentThread {
  const { run = null, status = 'proposed', kind = 'comment', agent = true, runOnAuthor = false } = opts;
  return {
    id,
    project_id: 'p',
    parent_dashboard_id: 'd',
    anchor: { dashboard_id: 'd' },
    kind,
    status,
    run_id: runOnAuthor ? null : run,
    created_by: {
      kind: agent ? 'agent' : 'human',
      user_id: 'u',
      agent: agent ? { name: 'annotator@1', run_id: runOnAuthor ? run : null } : null,
    },
    created_at: '',
    updated_at: '',
    comments: [],
    staleness: { component_missing: false, component_changed: false, data_changed: false },
  };
}

describe('thread helpers', () => {
  const threads = [
    thread('a', { run: 'r1' }),
    thread('b', { run: 'r1', kind: 'question' }),
    thread('c', { run: 'r2', runOnAuthor: true }),
    thread('d', { agent: false, status: 'open' }),
  ];

  it('reads the run from the thread or its agent author', () => {
    expect(threadRunId(threads[0])).toBe('r1');
    expect(threadRunId(threads[2])).toBe('r2');
    expect(threadRunId(threads[3])).toBeNull();
    expect(runIdsOf(threads)).toEqual(['r1', 'r2']);
  });

  it('filters by run and by questions', () => {
    expect(filterThreads(threads, { runId: 'r1' }).map((t) => t.id)).toEqual(['a', 'b']);
    expect(filterThreads(threads, { questionsOnly: true }).map((t) => t.id)).toEqual(['b']);
    expect(filterThreads(threads, { runId: 'r2', questionsOnly: true })).toEqual([]);
    expect(filterThreads(threads, {})).toHaveLength(4);
  });

  it('accepts every proposal of the run when no verdict links a thread', () => {
    const extra = [...threads, thread('e', { run: 'r1', status: 'open' })];
    expect(acceptableThreads(extra, 'r1').map((t) => t.id)).toEqual(['a', 'b']);
  });

  it('leaves out threads whose finding was weakened or refuted', () => {
    const run: AgentRun = {
      id: 'r1',
      dashboard_id: 'd',
      question: 'q',
      status: 'complete',
      created_at: '',
      agents: [
        {
          agent_id: 'analyst/qc@1',
          findings: [
            { finding_id: 'f1', title: 't', confidence: 'high', evidence: [], thread_ids: ['a'] },
          ],
        },
      ],
      verdicts: [
        { finding_id: 'f1', verdict: 'confirmed' },
        { finding_id: 'f2', verdict: 'refuted' },
      ],
      threads: [{ thread_id: 'b', finding_id: 'f2' }],
    };
    expect(acceptableThreads(threads, 'r1', run).map((t) => t.id)).toEqual(['a']);
  });

  it('leaves out threads whose finding is unverified', () => {
    const run: AgentRun = {
      id: 'r1',
      dashboard_id: 'd',
      question: 'q',
      status: 'budget',
      created_at: '',
      verdicts: [
        { finding_id: 'f1', verdict: 'confirmed' },
        { finding_id: 'f2', verdict: 'unverified' },
      ],
      threads: [
        { thread_id: 'a', finding_id: 'f1' },
        { thread_id: 'b', finding_id: 'f2' },
      ],
    };
    expect(acceptableThreads(threads, 'r1', run).map((t) => t.id)).toEqual(['a']);
    expect(agentRunToTrace(run).verdicts.f2.verdict).toBe('unverified');
  });
});

describe('agentRunToTrace', () => {
  it('rebuilds lanes, verdicts and threads from a stored run', () => {
    const t = agentRunToTrace({
      run_id: 'r9',
      dashboard_id: 'd',
      question: 'q',
      status: 'complete',
      created_at: '',
      team: ['analyst/qc@1'],
      budget: { spent_usd: 0.2, limit_usd: 1 },
      agents: [
        {
          agent_id: 'analyst/qc@1',
          status: 'ok',
          tool_calls: [{ call_id: 'c1', tool: 'query_data', ok: false, error: 'bad column' }],
          findings: [
            { finding_id: 'f1', title: 't', confidence: 'low', evidence: [], verdict: 'weakened' },
          ],
        },
      ],
      threads: [{ thread_id: 't1', agent_id: 'analyst/qc@1', kind: 'question' }],
      outputs: { report_id: 'rep' },
    });
    expect(t.runId).toBe('r9');
    expect(t.lanes[0].toolCalls[0]).toMatchObject({ ok: false, summary: 'bad column' });
    expect(t.verdicts.f1.verdict).toBe('weakened');
    expect(t.lanes[0].threads[0]).toMatchObject({ thread_id: 't1', kind: 'question' });
    expect(t.budget.spent_usd).toBe(0.2);
    expect(traceReportId(t)).toBe('rep');
  });
});
