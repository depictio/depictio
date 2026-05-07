import React, { useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Collapse,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useAnalyze } from '../hooks';
import { useAISession, useAIStore } from '../store';
import type { DashboardActions } from '../types';
import ActionsPreview from './ActionsPreview';
import ExecutionTrace from './ExecutionTrace';

interface Props {
  dashboardId: string;
  /** Optional component the user is currently focused on. */
  selectedComponentId?: string;
  /** Apply a DashboardActions plan to the host's stores. When omitted,
   *  ActionsPreview becomes read-only. */
  onApplyActions?: (actions: DashboardActions) => void;
}

/**
 * Always-visible analyze surface that lives at the top of the dashboard
 * grid (next to the timeline / TopPanel area). The figure-creation flow
 * still lives in a drawer; analyze is the persistent companion the user
 * wanted: ask a question, see the trace + answer + proposed actions
 * without losing the dashboard view.
 *
 * Compact by default — a single-line input with a minimal status row.
 * Expands inline when a transcript exists, with a collapse toggle so
 * the user can reclaim vertical space without losing history.
 */
const AIAnalyzePanel: React.FC<Props> = ({
  dashboardId,
  selectedComponentId,
  onApplyActions,
}) => {
  const session = useAISession(dashboardId);
  const reset = useAIStore((s) => s.reset);
  const { run: runAnalyze, cancel } = useAnalyze(dashboardId);
  const [prompt, setPrompt] = useState('');
  const [open, setOpen] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [appliedIds, setAppliedIds] = useState<Set<string>>(new Set());

  // Only analyze messages render here — figure suggestions are handled
  // by the drawer / inline figure list. This filters the shared session
  // transcript so the panel stays focused on Q&A.
  const analyzeMessages = session.messages.filter((m) => !m.suggestion);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [analyzeMessages.length, session.pending]);

  async function send() {
    const text = prompt.trim();
    if (!text || session.pending) return;
    if (!session.llmKey) return;
    setPrompt('');
    setOpen(true);
    await runAnalyze(text, { selectedComponentId });
  }

  const hasTranscript = analyzeMessages.length > 0;

  return (
    <Paper
      withBorder
      radius="md"
      p="xs"
      mb="xs"
      style={{ borderColor: 'var(--mantine-color-violet-3)' }}
    >
      <Stack gap="xs">
        <Group gap="xs" align="center" wrap="nowrap">
          <Icon
            icon="material-symbols:smart-toy-outline"
            width={18}
            color="var(--mantine-color-violet-6)"
          />
          <Text size="sm" fw={600}>
            Ask the dashboard
          </Text>
          {session.model && (
            <Badge size="xs" variant="light" color="blue">
              {session.model.split('/').pop()}
            </Badge>
          )}
          {session.pending && (
            <Group gap={6} ml="xs">
              <Loader size="xs" />
              <Text size="xs" c="dimmed">
                Thinking…
              </Text>
              <Button size="compact-xs" variant="subtle" color="gray" onClick={cancel}>
                Cancel
              </Button>
            </Group>
          )}
          <Group gap={2} ml="auto">
            {hasTranscript && (
              <Tooltip label="Clear">
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  onClick={() => reset(dashboardId)}
                  aria-label="Clear analyze transcript"
                >
                  <Icon icon="material-symbols:delete-outline" width={16} />
                </ActionIcon>
              </Tooltip>
            )}
            {hasTranscript && (
              <Tooltip label={open ? 'Collapse' : 'Expand'}>
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  onClick={() => setOpen((v) => !v)}
                  aria-label="Toggle transcript"
                >
                  <Icon
                    icon={
                      open
                        ? 'material-symbols:keyboard-arrow-up'
                        : 'material-symbols:keyboard-arrow-down'
                    }
                    width={18}
                  />
                </ActionIcon>
              </Tooltip>
            )}
          </Group>
        </Group>

        {!session.llmKey && (
          <Alert color="yellow" variant="light" p="xs">
            <Text size="xs">
              Set an LLM API key from the dashboard settings drawer to start.
            </Text>
          </Alert>
        )}

        <Group gap="xs" align="flex-start" wrap="nowrap">
          <Textarea
            placeholder="e.g. Which samples have the highest read count? Filter by Run > 2024-01."
            value={prompt}
            onChange={(e) => setPrompt(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void send();
              }
            }}
            autosize
            minRows={1}
            maxRows={4}
            disabled={session.pending}
            style={{ flex: 1 }}
          />
          <Button
            size="sm"
            variant="filled"
            onClick={() => void send()}
            disabled={session.pending || !prompt.trim() || !session.llmKey}
            rightSection={<Icon icon="material-symbols:send" width={14} />}
          >
            Ask
          </Button>
        </Group>

        {hasTranscript && (
          <Collapse in={open}>
            <ScrollArea
              viewportRef={scrollRef}
              style={{ maxHeight: 320 }}
              offsetScrollbars
            >
              <Stack gap="md" pr="xs">
                {analyzeMessages.map((m) => (
                  <Stack key={m.id} gap={4}>
                    <Group gap={6}>
                      <Icon
                        icon={
                          m.role === 'user'
                            ? 'material-symbols:person-outline'
                            : 'material-symbols:smart-toy-outline'
                        }
                        width={14}
                      />
                      <Text size="xs" c="dimmed" fw={600}>
                        {m.role === 'user' ? 'You' : 'Assistant'}
                      </Text>
                    </Group>
                    {m.content && (
                      <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                        {m.content}
                      </Text>
                    )}
                    {m.steps && m.steps.length > 0 && (
                      <ExecutionTrace steps={m.steps} />
                    )}
                    {m.result?.actions && (
                      <ActionsPreview
                        actions={m.result.actions}
                        onApply={
                          onApplyActions
                            ? (actions) => {
                                onApplyActions(actions);
                                setAppliedIds((s) => new Set(s).add(m.id));
                              }
                            : undefined
                        }
                        applied={appliedIds.has(m.id)}
                      />
                    )}
                  </Stack>
                ))}
              </Stack>
            </ScrollArea>
          </Collapse>
        )}
      </Stack>
    </Paper>
  );
};

export default AIAnalyzePanel;
