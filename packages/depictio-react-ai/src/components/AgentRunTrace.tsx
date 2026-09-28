import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Progress,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { AI_COLOR, AI_ICON, aiColorVar } from '../icons';
import { traceReportId } from '../agentRuns';
import type { AgentLane, AgentRunTraceState, TraceFinding, TraceVerdict } from '../agentRuns';
import type { AgentVerdict } from '../types';

export const VERDICT_COLOR: Record<AgentVerdict, string> = {
  confirmed: 'teal',
  weakened: 'yellow',
  refuted: 'red',
};

const VERDICT_ICON: Record<AgentVerdict, string> = {
  confirmed: 'material-symbols:check-circle-outline',
  weakened: 'material-symbols:warning-outline',
  refuted: 'material-symbols:cancel-outline',
};

const CONFIDENCE_COLOR: Record<TraceFinding['confidence'], string> = {
  low: 'gray',
  medium: 'blue',
  high: 'teal',
};

const LANE_STATUS: Record<AgentLane['status'], { color: string; icon: string; label: string }> = {
  running: { color: AI_COLOR, icon: 'mdi:loading', label: 'running' },
  ok: { color: 'teal', icon: 'material-symbols:check-circle-outline', label: 'done' },
  budget: { color: 'yellow', icon: 'material-symbols:savings-outline', label: 'out of budget' },
  error: { color: 'red', icon: 'material-symbols:error-outline', label: 'error' },
};

const RUN_STATUS_COLOR: Record<AgentRunTraceState['status'], string> = {
  idle: 'gray',
  running: AI_COLOR,
  complete: 'teal',
  cancelled: 'yellow',
  failed: 'red',
  budget: 'yellow',
};

/** A verdict badge, with the skeptic's reason on hover. */
export const VerdictBadge: React.FC<{ verdict: TraceVerdict | AgentVerdict }> = ({ verdict }) => {
  const v = typeof verdict === 'string' ? { verdict } : verdict;
  const badge = (
    <Badge
      size="xs"
      variant="light"
      color={VERDICT_COLOR[v.verdict] ?? 'gray'}
      leftSection={<Icon icon={VERDICT_ICON[v.verdict] ?? 'material-symbols:help-outline'} width={11} />}
    >
      {v.verdict}
    </Badge>
  );
  return 'reason' in v && v.reason ? (
    <Tooltip label={v.reason} multiline w={280} withArrow>
      {badge}
    </Tooltip>
  ) : (
    badge
  );
};

function laneTitle(lane: AgentLane): string {
  return lane.topic ? `${lane.role ?? 'agent'} · ${lane.topic}` : lane.role ?? lane.agent_id;
}

function formatUsd(n: number): string {
  return n < 0.01 && n > 0 ? '<$0.01' : `$${n.toFixed(2)}`;
}

interface Props {
  trace: AgentRunTraceState;
  /** Opens the comments drawer on a thread the run wrote. Without it the
   *  thread ids are listed as plain text. */
  onOpenThread?: (threadId: string) => void;
  /** Opens the run's report. */
  onOpenReport?: (reportId: string) => void;
}

/**
 * The trace of an agent-team run: a budget bar, then one lane per agent
 * listing its tool calls, its findings with the skeptic's verdicts, and the
 * threads and report it wrote.
 */
const AgentRunTrace: React.FC<Props> = ({ trace, onOpenThread, onOpenReport }) => {
  const { budget } = trace;
  const budgetPct =
    budget.limit_usd && budget.limit_usd > 0
      ? Math.min(100, (budget.spent_usd / budget.limit_usd) * 100)
      : null;
  const reportId = traceReportId(trace);
  const running = trace.status === 'running';

  // Each lane opens once, when it first appears; after that the user's
  // folding is left alone. A different run starts over.
  const [opened, setOpened] = useState<string[]>([]);
  const seen = useRef<{ runId: string | null; ids: Set<string> }>({ runId: null, ids: new Set() });
  useEffect(() => {
    if (seen.current.runId !== trace.runId) {
      seen.current = { runId: trace.runId, ids: new Set() };
      setOpened([]);
    }
    const fresh = trace.lanes.map((l) => l.agent_id).filter((id) => !seen.current.ids.has(id));
    if (!fresh.length) return;
    fresh.forEach((id) => seen.current.ids.add(id));
    setOpened((prev) => [...prev, ...fresh]);
  }, [trace.lanes, trace.runId]);

  const verdictCounts = useMemo(() => {
    const c: Record<AgentVerdict, number> = { confirmed: 0, weakened: 0, refuted: 0 };
    Object.values(trace.verdicts).forEach((v) => {
      c[v.verdict] = (c[v.verdict] ?? 0) + 1;
    });
    return c;
  }, [trace.verdicts]);

  if (trace.status === 'idle') return null;

  return (
    <Stack gap="xs" data-testid="agent-run-trace">
      <Group gap="xs" wrap="wrap" align="center">
        <Badge variant="light" color={RUN_STATUS_COLOR[trace.status]}>
          {trace.status}
        </Badge>
        {trace.routing && (
          <Tooltip label="How the team was chosen">
            <Badge variant="outline" color="gray">
              routing: {trace.routing.method}
            </Badge>
          </Tooltip>
        )}
        {(Object.keys(verdictCounts) as AgentVerdict[])
          .filter((k) => verdictCounts[k] > 0)
          .map((k) => (
            <Badge key={k} variant="light" color={VERDICT_COLOR[k]}>
              {verdictCounts[k]} {k}
            </Badge>
          ))}
        {reportId && onOpenReport && (
          <Button
            ml="auto"
            size="compact-xs"
            variant="light"
            color={AI_COLOR}
            leftSection={<Icon icon="material-symbols:description-outline" width={14} />}
            onClick={() => onOpenReport(reportId)}
          >
            Open report
          </Button>
        )}
      </Group>

      <Stack gap={2}>
        <Group gap="xs" justify="space-between">
          <Text size="xs" c="dimmed">
            Budget {formatUsd(budget.spent_usd)}
            {budget.limit_usd != null ? ` of ${formatUsd(budget.limit_usd)}` : ''}
          </Text>
          <Text size="xs" c="dimmed">
            {budget.tool_calls}
            {budget.max_tool_calls != null ? `/${budget.max_tool_calls}` : ''} tool calls
          </Text>
        </Group>
        {budgetPct !== null && (
          <Progress
            value={budgetPct}
            size="sm"
            color={budgetPct >= 90 ? 'red' : budgetPct >= 70 ? 'yellow' : AI_COLOR}
            animated={running}
            aria-label="Budget spent"
          />
        )}
      </Stack>

      {trace.errors.map((e, i) => (
        <Alert key={i} variant="light" color="red" p="xs">
          <Text size="xs">{e}</Text>
        </Alert>
      ))}

      {trace.lanes.length === 0 && running && (
        <Group gap="xs">
          <Loader size="xs" color={AI_COLOR} />
          <Text size="xs" c="dimmed">
            Assembling the team…
          </Text>
        </Group>
      )}

      <Accordion
        multiple
        value={opened}
        onChange={setOpened}
        variant="separated"
        styles={{ control: { paddingTop: 4, paddingBottom: 4 } }}
      >
        {trace.lanes.map((lane) => {
          const st = LANE_STATUS[lane.status];
          const failed = lane.toolCalls.filter((c) => c.ok === false).length;
          return (
            <Accordion.Item key={lane.agent_id} value={lane.agent_id}>
              <Accordion.Control>
                <Group gap="xs" wrap="nowrap">
                  {lane.status === 'running' ? (
                    <Loader size={14} color={AI_COLOR} />
                  ) : (
                    <Icon icon={st.icon} width={16} color={`var(--mantine-color-${st.color}-6)`} />
                  )}
                  <Text size="sm" fw={600} lineClamp={1} flex={1}>
                    {laneTitle(lane)}
                  </Text>
                  <Badge size="xs" variant="light" color="gray">
                    {lane.toolCalls.length} calls
                  </Badge>
                  {failed > 0 && (
                    <Badge size="xs" variant="light" color="red">
                      {failed} failed
                    </Badge>
                  )}
                  {lane.findings.length > 0 && (
                    <Badge size="xs" variant="light" color={AI_COLOR}>
                      {lane.findings.length} findings
                    </Badge>
                  )}
                  {lane.threads.length > 0 && (
                    <Badge size="xs" variant="light" color="violet">
                      {lane.threads.length} threads
                    </Badge>
                  )}
                  <Badge size="xs" variant="light" color={st.color}>
                    {st.label}
                  </Badge>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <LaneBody
                  lane={lane}
                  verdicts={trace.verdicts}
                  onOpenThread={onOpenThread}
                  onOpenReport={onOpenReport}
                />
              </Accordion.Panel>
            </Accordion.Item>
          );
        })}
      </Accordion>
    </Stack>
  );
};

const LaneBody: React.FC<{
  lane: AgentLane;
  verdicts: Record<string, TraceVerdict>;
  onOpenThread?: (threadId: string) => void;
  onOpenReport?: (reportId: string) => void;
}> = ({ lane, verdicts, onOpenThread, onOpenReport }) => (
  <Stack gap="xs">
    <Text size="xs" c="dimmed" ff="monospace">
      {lane.agent_id}
    </Text>
    {lane.summary && (
      <Text size="xs" fs="italic">
        {lane.summary}
      </Text>
    )}
    {lane.errors.map((e, i) => (
      <Text key={i} size="xs" c="red">
        {e}
      </Text>
    ))}

    {lane.toolCalls.length > 0 && (
      <Stack gap={2}>
        <Text size="xs" fw={600}>
          Tool calls
        </Text>
        {lane.toolCalls.map((c) => (
          <Group key={c.call_id} gap={6} wrap="nowrap" align="flex-start">
            {c.ok === undefined ? (
              <Loader size={12} color={AI_COLOR} />
            ) : (
              <Icon
                icon={c.ok ? 'material-symbols:check' : 'material-symbols:close'}
                width={14}
                color={`var(--mantine-color-${c.ok ? 'teal' : 'red'}-6)`}
                style={{ flexShrink: 0, marginTop: 2 }}
              />
            )}
            <Badge size="xs" variant="outline" color="gray" style={{ flexShrink: 0 }}>
              {c.tool}
            </Badge>
            <Text size="xs" c={c.ok === false ? 'red' : 'dimmed'} style={{ minWidth: 0 }} lineClamp={3}>
              {c.summary || ''}
              {c.truncated ? ' (truncated)' : ''}
            </Text>
            <Text size="xs" c="dimmed" ff="monospace" ml="auto" style={{ flexShrink: 0 }}>
              {c.call_id.slice(0, 8)}
            </Text>
          </Group>
        ))}
      </Stack>
    )}

    {lane.findings.length > 0 && (
      <Stack gap={4}>
        <Text size="xs" fw={600}>
          Findings
        </Text>
        {lane.findings.map((f) => (
          <Stack
            key={f.finding_id}
            gap={2}
            p={6}
            style={{
              borderLeft: `2px solid ${aiColorVar(4)}`,
              borderRadius: 'var(--mantine-radius-xs)',
            }}
          >
            <Group gap={6} wrap="wrap">
              <Badge size="xs" variant="light" color={CONFIDENCE_COLOR[f.confidence] ?? 'gray'}>
                {f.confidence}
              </Badge>
              {verdicts[f.finding_id] ? (
                <VerdictBadge verdict={verdicts[f.finding_id]} />
              ) : (
                <Badge size="xs" variant="outline" color="gray">
                  awaiting skeptic
                </Badge>
              )}
              <Text size="sm" fw={500} style={{ flex: 1, minWidth: 0 }}>
                {f.title}
              </Text>
            </Group>
            {f.detail && (
              <Text size="xs" c="dimmed">
                {f.detail}
              </Text>
            )}
            {f.evidence.map((ev, i) => (
              <Group key={i} gap={4} wrap="nowrap" align="flex-start">
                <Icon icon="material-symbols:data-object" width={12} style={{ flexShrink: 0, marginTop: 2 }} />
                <Text size="xs" style={{ minWidth: 0 }}>
                  {ev.note}
                </Text>
                <Text size="xs" c="dimmed" ff="monospace" ml="auto" style={{ flexShrink: 0 }}>
                  {ev.call_id.slice(0, 8)}
                </Text>
              </Group>
            ))}
          </Stack>
        ))}
      </Stack>
    )}

    {lane.threads.length > 0 && (
      <Stack gap={2}>
        <Text size="xs" fw={600}>
          Threads proposed
        </Text>
        {lane.threads.map((t) => (
          <Group key={t.thread_id} gap={6} wrap="nowrap">
            <Icon
              icon={t.kind === 'question' ? 'mdi:help-circle-outline' : 'mdi:comment-outline'}
              width={14}
            />
            {onOpenThread ? (
              <Anchor component="button" size="xs" onClick={() => onOpenThread(t.thread_id)}>
                {t.kind === 'question' ? 'Question' : 'Comment'}
                {t.component_index ? ` on ${t.component_index.slice(0, 8)}` : ' on the tab'}
              </Anchor>
            ) : (
              <Text size="xs" ff="monospace">
                {t.thread_id}
              </Text>
            )}
          </Group>
        ))}
      </Stack>
    )}

    {lane.reportIds.length > 0 && onOpenReport && (
      <Group gap={6}>
        <Icon icon={AI_ICON} width={14} color={aiColorVar(6)} />
        {lane.reportIds.map((id) => (
          <Anchor key={id} component="button" size="xs" onClick={() => onOpenReport(id)}>
            Report
          </Anchor>
        ))}
      </Group>
    )}
  </Stack>
);

export default AgentRunTrace;
