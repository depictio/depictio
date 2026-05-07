import React from 'react';
import {
  ActionIcon,
  Badge,
  Group,
  Paper,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { PlotSuggestion } from '../types';
import FigurePreview from './FigurePreview';
import PythonCodeBlock from './PythonCodeBlock';

export interface AISuggestedFigure {
  /** Stable id so the parent can key on it / dedupe / remove. */
  id: string;
  suggestion: PlotSuggestion;
  /** DC + WF the figure should resolve against (mirrors what
   *  /figure/preview expects in metadata). */
  dataCollectionId: string;
  workflowId?: string;
  projectId?: string;
}

interface Props {
  figures: AISuggestedFigure[];
  onRemove: (id: string) => void;
}

/**
 * Renders the user-accepted AI figure suggestions inline on the
 * dashboard. Lives above the grid so newly added figures are visible
 * without opening the drawer. Read-only against the dashboard's
 * stored_metadata — the viewer cannot persist; the host can wire an
 * "open in editor" follow-up later.
 */
const AISuggestedFigures: React.FC<Props> = ({ figures, onRemove }) => {
  if (figures.length === 0) return null;
  return (
    <Stack gap="xs" mb="xs">
      <Group gap="xs" align="center">
        <Icon icon="material-symbols:auto-awesome" width={16} color="var(--mantine-color-violet-6)" />
        <Text size="sm" fw={600}>
          AI-added figures
        </Text>
        <Badge size="xs" variant="light" color="violet">
          {figures.length}
        </Badge>
        <Text size="xs" c="dimmed">
          (session-only — open the editor to persist)
        </Text>
      </Group>
      {figures.map((f) => (
        <Paper
          key={f.id}
          withBorder
          p="sm"
          radius="md"
          style={{ borderColor: 'var(--mantine-color-violet-3)' }}
        >
          <Group justify="space-between" align="flex-start" mb={6}>
            <Stack gap={2} style={{ flex: 1 }}>
              <Group gap="xs" align="center">
                <Badge size="xs" variant="light" color="blue">
                  {f.suggestion.visu_type}
                </Badge>
                <Text size="sm" fw={600}>
                  {f.suggestion.title}
                </Text>
              </Group>
              {f.suggestion.explanation && (
                <Text size="xs" c="dimmed">
                  {f.suggestion.explanation}
                </Text>
              )}
            </Stack>
            <Tooltip label="Remove">
              <ActionIcon
                variant="subtle"
                color="gray"
                onClick={() => onRemove(f.id)}
                aria-label="Remove AI figure"
              >
                <Icon icon="material-symbols:close" width={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
          {f.suggestion.code && (
            <PythonCodeBlock
              code={f.suggestion.code}
              flavor="Plotly Express"
              tone="figure"
              defaultOpen={false}
            />
          )}
          <FigurePreview
            suggestion={f.suggestion}
            dataCollectionId={f.dataCollectionId}
            workflowId={f.workflowId}
            projectId={f.projectId}
          />
        </Paper>
      ))}
    </Stack>
  );
};

export default AISuggestedFigures;
