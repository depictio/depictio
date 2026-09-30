import React, { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Grid,
  Group,
  Loader,
  Modal,
  Progress,
  ScrollArea,
  Stack,
  Text,
  Textarea,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { fetchAgentRun } from '../api';
import { useAnalysisReport } from '../hooks';
import { AI_COLOR, AI_ICON, aiColorVar } from '../icons';
import { fetchDashboard, renderInlineMarkdown } from 'depictio-react-core';
import MarkdownLite from './MarkdownLite';
import type { AgentReportFinding, AgentRun, AnalysisReport, Finding } from '../types';
import { VerdictBadge } from './AgentRunTrace';
import ExecutionTrace from './ExecutionTrace';

interface Props {
  dashboardId: string;
  opened: boolean;
  onClose: () => void;
  /** Active InteractiveFilter list, forwarded so the default collection
   *  is loaded with the rows the user currently sees. */
  activeFilters?: unknown[];
  /** Report to show on opening (a team run's report), picked from the
   *  dashboard's history once it loads. */
  initialReportId?: string | null;
}

const CONFIDENCE_COLOR: Record<Finding['confidence'], string> = {
  low: 'gray',
  medium: 'blue',
  high: 'teal',
};

const STATUS_COLOR: Record<AnalysisReport['status'], string> = {
  running: 'blue',
  complete: 'teal',
  failed: 'red',
  cancelled: 'yellow',
};

function formatDuration(ms: number): string {
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

/** The stats line under a report: the analysis budget for `/ai/analyze`
 *  reports; for an agent's report, the run behind it (team, tool calls, cost,
 *  duration) once loaded. Zero stats an agent report never fills are left out. */
export function reportStats(report: AnalysisReport, run: AgentRun | null): string {
  const parts: string[] = [report.model];
  if (report.agent) {
    if (run) {
      const team = run.team?.length ?? 0;
      if (team) parts.push(`team of ${team}`);
      const calls = run.budget?.tool_calls ?? 0;
      if (calls) parts.push(`${calls} tool ${calls === 1 ? 'call' : 'calls'}`);
      const spent = run.budget?.spent_usd ?? 0;
      if (spent > 0) parts.push(spent < 0.01 ? '<$0.01' : `$${spent.toFixed(2)}`);
      const start = Date.parse(run.created_at);
      const end = run.finished_at ? Date.parse(run.finished_at) : NaN;
      if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
        parts.push(formatDuration(end - start));
      }
    }
    const b = report.budget_spent;
    if (b.steps > 0) parts.push(`${b.steps} steps`);
    if (b.tokens > 0) parts.push(`${b.tokens.toLocaleString()} tokens`);
    return parts.filter(Boolean).join(' · ');
  }
  const b = report.budget_spent;
  parts.push(`${b.steps} steps`, `${b.tokens.toLocaleString()} tokens`, `${Math.round(b.seconds)}s`);
  return parts.filter(Boolean).join(' · ');
}

/**
 * Full-screen surface for read-only analysis runs.
 *
 * This is deliberately not a chat: the deliverable is a report — a
 * narrative plus findings, each finding pinned to the executed steps
 * that prove it. There is no Apply button anywhere in this surface and
 * never will be; the server strips actions in this mode.
 */
const AIAnalysisModal: React.FC<Props> = ({
  dashboardId,
  opened,
  onClose,
  activeFilters,
  initialReportId,
}) => {
  const { run, cancel, reset, pending, state, history, loadHistory } =
    useAnalysisReport(dashboardId);
  const [prompt, setPrompt] = useState('');
  const [viewing, setViewing] = useState<AnalysisReport | null>(null);

  useEffect(() => {
    if (opened) void loadHistory();
  }, [opened, loadHistory]);

  // Open on the requested report once the history holds it.
  useEffect(() => {
    if (!opened || !initialReportId) return;
    const target = history.find((h) => h.id === initialReportId);
    if (target) {
      reset();
      setViewing(target);
    }
  }, [opened, initialReportId, history, reset]);

  // The live run wins over a history selection.
  const report = state.report ?? viewing;

  // An agent report's own budget is empty: its stats come from the run.
  const runId = report?.agent?.run_id ?? null;
  const [teamRun, setTeamRun] = useState<AgentRun | null>(null);
  useEffect(() => {
    setTeamRun(null);
    if (!opened || !runId) return;
    let alive = true;
    fetchAgentRun(runId)
      .then((r) => alive && setTeamRun(r))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [opened, runId]);

  // Component titles for the agent findings' chips (the index means nothing).
  const [titles, setTitles] = useState<Record<string, string>>({});
  const needsTitles = (report?.agent_findings ?? []).some((f) => f.component_index);
  useEffect(() => {
    if (!opened || !needsTitles) return;
    let alive = true;
    fetchDashboard(dashboardId)
      .then((d) => {
        if (!alive) return;
        const out: Record<string, string> = {};
        (d.stored_metadata ?? []).forEach((m) => {
          const title = (m as { title?: unknown }).title;
          if (m.index && typeof title === 'string' && title.trim()) out[String(m.index)] = title.trim();
        });
        setTitles(out);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [opened, needsTitles, dashboardId]);
  const steps = state.report ? state.report.steps : state.steps.length ? state.steps : (viewing?.steps ?? []);

  const submit = () => {
    const text = prompt.trim();
    if (!text || pending) return;
    setViewing(null);
    void run(text, { activeFilters });
  };

  const budgetPct =
    state.budget && state.budget.max_steps > 0
      ? Math.min(100, (state.budget.steps_used / state.budget.max_steps) * 100)
      : null;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      fullScreen
      title={
        <Group gap="xs">
          <Icon icon={AI_ICON} width={20} />
          <Title order={4}>Analyze this dashboard</Title>
          <Badge variant="light" color={AI_COLOR}>
            read-only
          </Badge>
        </Group>
      }
    >
      <Grid gutter="md">
        <Grid.Col span={{ base: 12, md: 8 }}>
          <Stack gap="md">
            <Group align="flex-end" gap="xs">
              <Textarea
                flex={1}
                autosize
                minRows={2}
                maxRows={5}
                label="Question"
                placeholder="e.g. Which samples are atypical relative to their own group, and on which metric?"
                value={prompt}
                onChange={(e) => setPrompt(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    submit();
                  }
                }}
              />
              {pending ? (
                <Button color="red" variant="light" onClick={cancel}>
                  Cancel
                </Button>
              ) : (
                <Button onClick={submit} disabled={!prompt.trim()}>
                  Analyze
                </Button>
              )}
            </Group>

            {pending && (
              <Group gap="xs">
                <Loader size="xs" />
                <Text size="sm" c="dimmed">
                  {state.status || 'working'}
                </Text>
                {state.budget && (
                  <Text size="xs" c="dimmed" ml="auto">
                    step {state.budget.steps_used}/{state.budget.max_steps} ·{' '}
                    {state.budget.tokens_used.toLocaleString()} tokens ·{' '}
                    {Math.round(state.budget.seconds)}s
                  </Text>
                )}
              </Group>
            )}
            {budgetPct !== null && pending && <Progress value={budgetPct} size="xs" />}

            {state.plan && (
              <Alert
                variant="light"
                color={AI_COLOR}
                icon={<Icon icon="material-symbols:route" width={16} />}
                title="Plan"
              >
                <MarkdownLite text={state.plan} />
              </Alert>
            )}

            {state.error && (
              <Alert variant="light" color="red" title="Analysis failed">
                {state.error}
              </Alert>
            )}

            {report && (
              <Stack gap="md">
                <Group gap="xs">
                  <Badge variant="light" color={STATUS_COLOR[report.status]}>
                    {report.status}
                  </Badge>
                  {report.agent && (
                    <Tooltip label={report.agent.run_id ? `Run ${report.agent.run_id}` : 'Agent'}>
                      <Badge
                        variant="light"
                        color="violet"
                        leftSection={<Icon icon="mdi:robot-outline" width={12} />}
                      >
                        {report.agent.name}
                      </Badge>
                    </Tooltip>
                  )}
                  <Text size="xs" c="dimmed">
                    {reportStats(report, teamRun)}
                  </Text>
                </Group>

                {report.narrative_md && (
                  <Card withBorder radius="md" p="md">
                    <MarkdownLite text={report.narrative_md} />
                  </Card>
                )}

                {report.findings.length > 0 && (
                  <Stack gap="xs">
                    <Title order={6}>Findings</Title>
                    {report.findings.map((f, i) => (
                      <Card key={i} withBorder radius="md" p="sm">
                        <Group gap="xs" wrap="nowrap" align="flex-start">
                          <Badge
                            size="sm"
                            variant="light"
                            color={CONFIDENCE_COLOR[f.confidence]}
                          >
                            {f.confidence}
                          </Badge>
                          <Text size="sm" flex={1}>
                            {renderInlineMarkdown(f.claim)}
                          </Text>
                          <Tooltip label="Steps this claim is grounded in">
                            <Badge size="sm" variant="outline" color="gray">
                              evidence: {f.evidence_step_ids.map((n) => `#${n}`).join(', ')}
                            </Badge>
                          </Tooltip>
                        </Group>
                      </Card>
                    ))}
                  </Stack>
                )}

                {(report.agent_findings?.length ?? 0) > 0 && (
                  <AgentFindings findings={report.agent_findings ?? []} titles={titles} />
                )}

                {report.warnings.length > 0 && (
                  <Stack gap={2}>
                    {report.warnings.map((w, i) => (
                      <Text key={i} size="xs" c="dimmed">
                        {w}
                      </Text>
                    ))}
                  </Stack>
                )}
              </Stack>
            )}

            {steps.length > 0 && (
              <Stack gap="xs">
                <Title order={6}>Execution trace</Title>
                <ExecutionTrace steps={steps} />
              </Stack>
            )}
          </Stack>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 4 }}>
          <Stack gap="xs">
            <Group gap="xs">
              <Icon icon="material-symbols:history" width={16} />
              <Title order={6}>Previous analyses</Title>
            </Group>
            <Divider />
            <ScrollArea style={{ maxHeight: 'calc(100vh - 180px)' }} offsetScrollbars>
              <Stack gap="xs">
                {history.length === 0 && (
                  <Text size="xs" c="dimmed">
                    No analyses yet for this dashboard.
                  </Text>
                )}
                {history.map((h) => (
                  <Card
                    key={h.id}
                    withBorder
                    radius="md"
                    p="sm"
                    style={{ cursor: 'pointer' }}
                    onClick={() => {
                      reset();
                      setViewing(h);
                    }}
                  >
                    <Stack gap={4}>
                      <Text size="sm" lineClamp={2}>
                        {h.prompt}
                      </Text>
                      <Group gap="xs">
                        <Badge size="xs" variant="light" color={STATUS_COLOR[h.status]}>
                          {h.status}
                        </Badge>
                        <Text size="xs" c="dimmed">
                          {new Date(h.created_at).toLocaleString()}
                        </Text>
                        {h.agent && (
                          <Badge size="xs" variant="light" color="violet">
                            agent
                          </Badge>
                        )}
                        <Text size="xs" c="dimmed" ml="auto">
                          {h.findings.length + (h.agent_findings?.length ?? 0)} findings
                        </Text>
                      </Group>
                    </Stack>
                  </Card>
                ))}
              </Stack>
            </ScrollArea>
          </Stack>
        </Grid.Col>
      </Grid>
    </Modal>
  );
};

/** Findings of an agent-written report: each with its confidence, the
 *  skeptic's verdict when the server attaches one, and the evidence notes
 *  with the tool call ids that back them. */
const AgentFindings: React.FC<{
  findings: AgentReportFinding[];
  /** Component titles by index; a finding on an unknown component shows no chip. */
  titles: Record<string, string>;
}> = ({ findings, titles }) => (
  <Stack gap="xs" data-testid="agent-report-findings">
    <Title order={6}>Agent findings</Title>
    {findings.map((f, i) => (
      <Card key={f.finding_id ?? i} withBorder radius="md" p="sm">
        <Stack gap={6}>
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <Badge size="sm" variant="light" color={CONFIDENCE_COLOR[f.confidence] ?? 'gray'}>
              {f.confidence}
            </Badge>
            {f.verdict && (
              <VerdictBadge verdict={{ verdict: f.verdict, reason: f.verdict_reason }} />
            )}
            <Text size="sm" fw={600} flex={1}>
              {f.title}
            </Text>
            {f.component_index && titles[f.component_index] && (
              <Badge
                size="sm"
                variant="outline"
                color="gray"
                maw={220}
                leftSection={<Icon icon="mdi:chart-box-outline" width={12} />}
              >
                {titles[f.component_index]}
              </Badge>
            )}
          </Group>
          <Text size="sm">{renderInlineMarkdown(f.detail)}</Text>
          {f.evidence.map((ev, j) => (
            <Group key={j} gap={6} wrap="nowrap" align="flex-start">
              <Icon icon="material-symbols:data-object" width={14} style={{ flexShrink: 0, marginTop: 3 }} />
              <Text size="xs" style={{ minWidth: 0 }}>
                {ev.note}
              </Text>
              {ev.call_id && (
                <Tooltip label={ev.query || 'Tool call behind this evidence'} multiline w={320}>
                  <Badge size="xs" variant="outline" color="gray" ml="auto" style={{ flexShrink: 0 }}>
                    call {ev.call_id.slice(0, 8)}
                  </Badge>
                </Tooltip>
              )}
            </Group>
          ))}
        </Stack>
      </Card>
    ))}
  </Stack>
);

export default AIAnalysisModal;
