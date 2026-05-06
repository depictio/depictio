import React, { useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Drawer,
  Group,
  Loader,
  ScrollArea,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useAnalyze, useFigureFromPrompt } from '../hooks';
import { useAISession, useAIStore } from '../store';
import type { DashboardActions, PlotSuggestion } from '../types';
import ActionsPreview from './ActionsPreview';
import ExecutionTrace from './ExecutionTrace';
import FigurePreview from './FigurePreview';

interface Props {
  opened: boolean;
  onClose: () => void;
  dashboardId: string;
  /** Best-guess primary data collection id used by the figure-from-prompt
   *  flow. The host typically derives this from the dashboard's first
   *  figure component. */
  primaryDataCollectionId?: string;
  /** Workflow id paired with the primary DC. Forwarded to FigurePreview so
   *  the /figure/preview endpoint resolves the right Delta location. */
  primaryWorkflowId?: string;
  /** Project id of the current dashboard. Forwarded to FigurePreview so the
   *  preview metadata matches what the figure builder would send. */
  projectId?: string;
  /** Optional component the user is currently focused on; passed to
   *  /ai/analyze so the LLM can reason about it specifically. */
  selectedComponentId?: string;
  /** Apply a DashboardActions plan to the host's stores (filters,
   *  existing figures). When omitted, ActionsPreview becomes read-only. */
  onApplyActions?: (actions: DashboardActions) => void;
  /** Insert a new figure suggestion onto the dashboard grid. */
  onAddSuggestion?: (suggestion: PlotSuggestion) => void;
}

type Mode = 'analyze' | 'figure';

/**
 * Right-side AI assistant drawer. Composes the prompt-driven analysis
 * flow (default) and the prompt-driven figure-creation flow into a
 * single chat-style transcript so the user can switch fluidly between
 * "explain something" and "build me a chart".
 */
const AIDrawer: React.FC<Props> = ({
  opened,
  onClose,
  dashboardId,
  primaryDataCollectionId,
  primaryWorkflowId,
  projectId,
  selectedComponentId,
  onApplyActions,
  onAddSuggestion,
}) => {
  const session = useAISession(dashboardId);
  const reset = useAIStore((s) => s.reset);
  const { run: runAnalyze, cancel } = useAnalyze(dashboardId);
  const { run: runFigure } = useFigureFromPrompt(dashboardId);
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<Mode>('analyze');
  const scrollRef = useRef<HTMLDivElement>(null);
  const [appliedIds, setAppliedIds] = useState<Set<string>>(new Set());

  // Auto-scroll the transcript when new messages arrive.
  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [session.messages.length, session.pending]);

  async function send() {
    const text = prompt.trim();
    if (!text || session.pending) return;
    if (!session.llmKey) return;
    setPrompt('');
    if (mode === 'analyze') {
      await runAnalyze(text, { selectedComponentId });
    } else if (primaryDataCollectionId) {
      await runFigure(primaryDataCollectionId, text);
    }
  }

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="md"
      title={
        <Group gap="xs" align="center">
          <Icon icon="material-symbols:smart-toy-outline" width={20} />
          <Text fw={600}>AI Assistant</Text>
          {session.model && (
            <Badge size="xs" variant="light" color="blue">
              {session.model.split('/').pop()}
            </Badge>
          )}
        </Group>
      }
      padding="md"
    >
      <Stack gap="sm" h="100%">
        {!session.llmKey && (
          <Alert color="yellow" variant="light">
            Set an LLM API key from the dashboard settings drawer to start.
          </Alert>
        )}

        <Group justify="space-between" align="center">
          <Group gap="xs">
            <Button
              size="xs"
              variant={mode === 'analyze' ? 'filled' : 'light'}
              onClick={() => setMode('analyze')}
              leftSection={<Icon icon="material-symbols:psychology" width={14} />}
            >
              Analyze
            </Button>
            <Button
              size="xs"
              variant={mode === 'figure' ? 'filled' : 'light'}
              onClick={() => setMode('figure')}
              leftSection={<Icon icon="material-symbols:add-chart" width={14} />}
              disabled={!primaryDataCollectionId}
            >
              New figure
            </Button>
          </Group>
          {session.messages.length > 0 && (
            <Tooltip label="Clear conversation">
              <ActionIcon
                variant="subtle"
                color="gray"
                onClick={() => reset(dashboardId)}
              >
                <Icon icon="material-symbols:delete-outline" width={16} />
              </ActionIcon>
            </Tooltip>
          )}
        </Group>

        <ScrollArea
          viewportRef={scrollRef}
          style={{ flex: 1, minHeight: 200 }}
          offsetScrollbars
        >
          <Stack gap="md" pr="xs">
            {session.messages.length === 0 && (
              <Text size="sm" c="dimmed" ta="center" mt="lg">
                Ask a question about your data, or describe a chart you want.
              </Text>
            )}
            {session.messages.map((m) => (
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
                {m.suggestion && (
                  <Stack gap={6}>
                    <Alert color="blue" variant="light">
                      <Stack gap={4}>
                        <Group gap="xs">
                          <Badge size="xs" variant="light" color="blue">
                            {m.suggestion.visu_type}
                          </Badge>
                          <Text size="sm" fw={600}>
                            {m.suggestion.title}
                          </Text>
                        </Group>
                        <Text size="xs" c="dimmed">
                          {m.suggestion.explanation}
                        </Text>
                        {onAddSuggestion && (
                          <Button
                            size="xs"
                            variant="filled"
                            mt={4}
                            leftSection={<Icon icon="material-symbols:add" width={14} />}
                            onClick={() => onAddSuggestion(m.suggestion!)}
                          >
                            Add to dashboard
                          </Button>
                        )}
                      </Stack>
                    </Alert>
                    {primaryDataCollectionId && (
                      <FigurePreview
                        suggestion={m.suggestion}
                        dataCollectionId={primaryDataCollectionId}
                        workflowId={primaryWorkflowId}
                        projectId={projectId}
                      />
                    )}
                  </Stack>
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
            {session.pending && (
              <Group gap="xs" align="center">
                <Loader size="xs" />
                <Text size="xs" c="dimmed">
                  Working...
                </Text>
                <Button size="xs" variant="subtle" color="gray" onClick={cancel}>
                  Cancel
                </Button>
              </Group>
            )}
          </Stack>
        </ScrollArea>

        <Stack gap={4}>
          <Textarea
            placeholder={
              mode === 'analyze'
                ? 'e.g. Which samples have the highest read count? Filter by Run > 2024-01.'
                : 'e.g. Boxplot of read length per sample, colored by run.'
            }
            value={prompt}
            onChange={(e) => setPrompt(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void send();
              }
            }}
            autosize
            minRows={2}
            maxRows={6}
            disabled={session.pending}
          />
          <Group justify="space-between" align="center">
            <Text size="xs" c="dimmed">
              Cmd/Ctrl+Enter to send
            </Text>
            <Button
              size="xs"
              variant="filled"
              onClick={() => void send()}
              disabled={
                session.pending ||
                !prompt.trim() ||
                !session.llmKey ||
                (mode === 'figure' && !primaryDataCollectionId)
              }
              rightSection={<Icon icon="material-symbols:send" width={14} />}
            >
              Send
            </Button>
          </Group>
        </Stack>
      </Stack>
    </Drawer>
  );
};

export default AIDrawer;
