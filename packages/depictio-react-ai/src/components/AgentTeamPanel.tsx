import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  MultiSelect,
  Select,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { AI_COLOR, AI_ICON } from '../icons';
import { agentRunId, splitAgentId } from '../agentRuns';
import { useAgentProfiles, useAgentRoute, useAgentRun } from '../useAgentTeam';
import type { AgentProfile, AgentTeamMember } from '../types';
import AgentRunTrace from './AgentRunTrace';

/** Team options offered beside the routed team: each role paired with each
 *  topic pack, named like the server names them (`role/topic@<role version>`). */
export function composeTeamOptions(
  profiles: AgentProfile[],
  routed: AgentTeamMember[],
  selected: string[],
): { value: string; label: string }[] {
  const out = new Map<string, string>();
  const label = (id: string) => {
    const { role, topic } = splitAgentId(id);
    return topic ? `${role} · ${topic}` : role;
  };
  routed.forEach((m) => out.set(m.agent_id, label(m.agent_id)));
  const roles = profiles.filter((p) => p.kind === 'role');
  const topics = profiles.filter((p) => p.kind === 'topic');
  roles.forEach((r) =>
    topics.forEach((t) => {
      const id = `${r.id}/${t.id}@${r.version}`;
      if (!out.has(id)) out.set(id, `${r.name} · ${t.name}`);
    }),
  );
  selected.forEach((id) => {
    if (!out.has(id)) out.set(id, label(id));
  });
  return [...out.entries()].map(([value, l]) => ({ value, label: l }));
}

interface Props {
  dashboardId: string;
  hasCreds: boolean;
  onOpenThread?: (threadId: string) => void;
  onOpenReport?: (reportId: string) => void;
}

/**
 * Team mode of the analyze panel: a question, the team the router proposes
 * for it (editable), and the run's trace. The agents write proposals only:
 * threads land as "proposed" in the comments drawer, for a person to review.
 */
const AgentTeamPanel: React.FC<Props> = ({ dashboardId, hasCreds, onOpenThread, onOpenReport }) => {
  const [question, setQuestion] = useState('');
  const [team, setTeam] = useState<string[]>([]);
  // Once the user edits the team, routing stops overwriting it.
  const [teamTouched, setTeamTouched] = useState(false);
  const profiles = useAgentProfiles(true);
  const { route, loading: routing, error: routeError } = useAgentRoute(
    dashboardId,
    question,
    hasCreds,
  );
  const runState = useAgentRun(dashboardId);
  const { trace, pending, error, run, cancel, history, loadHistory, open } = runState;

  useEffect(() => {
    if (route && !teamTouched) setTeam(route.team.map((m) => m.agent_id));
  }, [route, teamTouched]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);
  // A finished run joins the history list.
  useEffect(() => {
    if (!pending && trace.runId) void loadHistory();
  }, [pending, trace.runId, loadHistory]);

  const options = useMemo(
    () => composeTeamOptions(profiles, route?.team ?? [], team),
    [profiles, route, team],
  );

  const submit = () => {
    const text = question.trim();
    if (!text || pending || !hasCreds) return;
    void run(text, { team: teamTouched ? team : undefined });
  };

  const reasons = (route?.team ?? []).filter((m) => m.reason);

  return (
    <Stack gap="xs" data-testid="agent-team-panel">
      <Group gap="xs" align="flex-start" wrap="nowrap">
        <Textarea
          placeholder="e.g. Which samples fail QC, and why? Flag them on the charts."
          value={question}
          onChange={(e) => setQuestion(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          autosize
          minRows={1}
          maxRows={4}
          disabled={pending}
          style={{ flex: 1 }}
          aria-label="Question for the agent team"
        />
        {pending ? (
          <Button size="sm" variant="light" color="red" onClick={() => void cancel()}>
            Cancel
          </Button>
        ) : (
          <Button
            size="sm"
            color={AI_COLOR}
            leftSection={<Icon icon={AI_ICON} width={14} />}
            onClick={submit}
            disabled={!question.trim() || !hasCreds}
          >
            Run team
          </Button>
        )}
      </Group>

      <MultiSelect
        size="xs"
        label={
          <Group gap={6} component="span">
            <span>Team</span>
            {routing && <Loader size={10} color={AI_COLOR} />}
            {route && !teamTouched && (
              <Badge size="xs" variant="outline" color="gray" component="span">
                routed by {route.routing.method}
              </Badge>
            )}
            {teamTouched && (
              <Button
                size="compact-xs"
                variant="subtle"
                color="gray"
                onClick={() => {
                  setTeamTouched(false);
                  if (route) setTeam(route.team.map((m) => m.agent_id));
                }}
              >
                Reset to routed team
              </Button>
            )}
          </Group>
        }
        placeholder={question.trim() ? 'Routed from the question' : 'Type a question to route a team'}
        data={options}
        value={team}
        onChange={(v) => {
          setTeam(v);
          setTeamTouched(true);
        }}
        searchable
        clearable
        disabled={pending}
        data-testid="agent-team-select"
      />

      {reasons.length > 0 && !teamTouched && (
        <Stack gap={2}>
          {reasons.map((m) => (
            <Group key={m.agent_id} gap={6} wrap="nowrap" align="flex-start">
              <Badge size="xs" variant="light" color={AI_COLOR} style={{ flexShrink: 0 }}>
                {m.topic ? `${m.role} · ${m.topic}` : m.role}
              </Badge>
              <Text size="xs" c="dimmed">
                {m.reason}
              </Text>
            </Group>
          ))}
        </Stack>
      )}
      {routeError && (
        <Text size="xs" c="dimmed">
          Could not route this question ({routeError}); the server picks the team at run time.
        </Text>
      )}

      {history.length > 0 && (
        <Group gap="xs" wrap="nowrap">
          <Icon icon="material-symbols:history" width={14} />
          <Select
            size="xs"
            placeholder="Open a previous run"
            data={history.map((h) => ({
              value: agentRunId(h),
              label: `${h.question.slice(0, 60)}${h.question.length > 60 ? '…' : ''} (${h.status})`,
            }))}
            value={trace.runId && !pending ? trace.runId : null}
            onChange={(v) => v && void open(v)}
            disabled={pending}
            style={{ flex: 1 }}
            comboboxProps={{ withinPortal: true }}
          />
        </Group>
      )}

      {error && (
        <Alert variant="light" color="red" p="xs" title="Team run failed">
          <Text size="xs">{error}</Text>
        </Alert>
      )}

      {runState.question && trace.status !== 'idle' && (
        <Tooltip label="Question of this run" openDelay={400}>
          <Text size="xs" fw={600} lineClamp={2}>
            {runState.question}
          </Text>
        </Tooltip>
      )}
      <AgentRunTrace trace={trace} onOpenThread={onOpenThread} onOpenReport={onOpenReport} />
    </Stack>
  );
};

export default AgentTeamPanel;
