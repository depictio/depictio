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
import ActionsPreview, { type ApplyActionsPayload } from './ActionsPreview';
import ExecutionTrace from './ExecutionTrace';

interface Props {
  dashboardId: string;
  /** Optional component the user is currently focused on. */
  selectedComponentId?: string;
  /** Active InteractiveFilter list — forwarded to the backend so the
   *  executor and quantile thresholds see the rows the user sees. */
  activeFilters?: unknown[];
  /** True when the server holds a fallback LLM key, so the panel works
   *  without a user-supplied key. */
  serverKeyAvailable?: boolean;
  /** Apply a resolved plan to the host's stores. When omitted,
   *  ActionsPreview becomes read-only. */
  onApplyActions?: (payload: ApplyActionsPayload) => void;
}

/**
 * Always-visible analyze surface that lives at the top of the dashboard
 * grid. Ask a question, see the trace + answer + proposed actions
 * without losing the dashboard view.
 *
 * Compact by default — a single-line input with a minimal status row.
 * Expands inline when a transcript exists, with a collapse toggle so
 * the user can reclaim vertical space without losing history.
 */
const AIAnalyzePanel: React.FC<Props> = ({
  dashboardId,
  selectedComponentId,
  activeFilters,
  serverKeyAvailable = false,
  onApplyActions,
}) => {
  const session = useAISession(dashboardId);
  const reset = useAIStore((s) => s.reset);
  const { run: runAnalyze, cancel } = useAnalyze(dashboardId);
  const [prompt, setPrompt] = useState('');
  const [open, setOpen] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [appliedIds, setAppliedIds] = useState<Set<string>>(new Set());

  const hasCreds = Boolean(session.llmKey) || serverKeyAvailable;

  // All messages in the store are analyze messages; component-creation
  // requests go through the builder's AI fill modal, which doesn't
  // append to this transcript.
  const analyzeMessages = session.messages;

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [analyzeMessages.length, session.pending]);

  async function send() {
    const text = prompt.trim();
    if (!text || session.pending || !hasCreds) return;
    setPrompt('');
    setOpen(true);
    await runAnalyze(text, { selectedComponentId, activeFilters });
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

        {!hasCreds && (
          <Alert color="yellow" variant="light" p="xs">
            <Text size="xs">
              Set an LLM API key from the dashboard settings drawer to start.
            </Text>
          </Alert>
        )}

        <Group gap="xs" align="flex-start" wrap="nowrap">
          <Textarea
            placeholder="e.g. Show the top 3% by read count. Which samples fail QC?"
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
            disabled={session.pending || !prompt.trim() || !hasCreds}
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
                        resolved={m.result.resolved_filters ?? []}
                        onApply={
                          onApplyActions
                            ? (payload) => {
                                onApplyActions(payload);
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
