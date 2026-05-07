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

import { useFigureFromPrompt } from '../hooks';
import { useAISession, useAIStore } from '../store';
import type { PlotSuggestion } from '../types';
import FigurePreview from './FigurePreview';
import PythonCodeBlock from './PythonCodeBlock';

interface Props {
  opened: boolean;
  onClose: () => void;
  dashboardId: string;
  /** Best-guess primary data collection id. The drawer is disabled
   *  without it, since "New figure" needs a DC to render against. */
  primaryDataCollectionId?: string;
  primaryWorkflowId?: string;
  projectId?: string;
  /** Insert a new figure suggestion onto the dashboard. The host owns
   *  what "add" means — append to a session-only list, or persist via
   *  the editor app. */
  onAddSuggestion?: (suggestion: PlotSuggestion) => void;
}

/**
 * Right-side drawer focused exclusively on figure creation. Analyze
 * lives in the always-visible AIAnalyzePanel above the grid — keeping
 * the drawer narrow so the user can compose a prompt + see the chart
 * preview side-by-side with the dashboard.
 */
const AIDrawer: React.FC<Props> = ({
  opened,
  onClose,
  dashboardId,
  primaryDataCollectionId,
  primaryWorkflowId,
  projectId,
  onAddSuggestion,
}) => {
  const session = useAISession(dashboardId);
  const reset = useAIStore((s) => s.reset);
  const { run: runFigure } = useFigureFromPrompt(dashboardId);
  const [prompt, setPrompt] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set());

  // Only figure messages render here — analyze messages flow into the
  // AIAnalyzePanel. Filtering keeps the drawer focused on charts.
  const figureMessages = session.messages.filter((m) => m.suggestion);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [figureMessages.length, session.pending]);

  async function send() {
    const text = prompt.trim();
    if (!text || session.pending) return;
    if (!session.llmKey) return;
    if (!primaryDataCollectionId) return;
    setPrompt('');
    await runFigure(primaryDataCollectionId, text);
  }

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="md"
      title={
        <Group gap="xs" align="center">
          <Icon icon="material-symbols:add-chart" width={20} />
          <Text fw={600}>New figure</Text>
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
        {!primaryDataCollectionId && (
          <Alert color="yellow" variant="light">
            This dashboard has no data collection yet — add a figure / table
            first so the AI knows what to plot against.
          </Alert>
        )}

        <Group justify="space-between" align="center">
          <Text size="xs" c="dimmed">
            Describe a chart and the AI will build it for you.
          </Text>
          {figureMessages.length > 0 && (
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
            {figureMessages.length === 0 && (
              <Text size="sm" c="dimmed" ta="center" mt="lg">
                Ask for a chart — e.g. "Boxplot of sepal width per variety".
              </Text>
            )}
            {figureMessages.map((m) => (
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
                            variant={addedIds.has(m.id) ? 'light' : 'filled'}
                            color={addedIds.has(m.id) ? 'teal' : 'violet'}
                            mt={4}
                            leftSection={
                              <Icon
                                icon={
                                  addedIds.has(m.id)
                                    ? 'material-symbols:check'
                                    : 'material-symbols:add'
                                }
                                width={14}
                              />
                            }
                            disabled={addedIds.has(m.id)}
                            onClick={() => {
                              onAddSuggestion(m.suggestion!);
                              setAddedIds((s) => new Set(s).add(m.id));
                            }}
                          >
                            {addedIds.has(m.id)
                              ? 'Added to dashboard'
                              : 'Add to dashboard'}
                          </Button>
                        )}
                      </Stack>
                    </Alert>
                    {m.suggestion.code && (
                      <PythonCodeBlock
                        code={m.suggestion.code}
                        flavor="Plotly Express"
                        tone="figure"
                      />
                    )}
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
              </Stack>
            ))}
            {session.pending && (
              <Group gap="xs" align="center">
                <Loader size="xs" />
                <Text size="xs" c="dimmed">
                  Building chart…
                </Text>
              </Group>
            )}
          </Stack>
        </ScrollArea>

        <Stack gap={4}>
          <Textarea
            placeholder="e.g. Boxplot of sepal width per variety."
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
                !primaryDataCollectionId
              }
              rightSection={<Icon icon="material-symbols:send" width={14} />}
            >
              Build
            </Button>
          </Group>
        </Stack>
      </Stack>
    </Drawer>
  );
};

export default AIDrawer;
