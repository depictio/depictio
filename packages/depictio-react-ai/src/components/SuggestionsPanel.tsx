import React, { useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { PlotSuggestion } from '../types';
import { useAISession } from '../store';
import { useSuggestFigures } from '../hooks';
import PythonCodeBlock from './PythonCodeBlock';

interface Props {
  dashboardId: string;
  dataCollectionId: string;
  /** Caller-provided hook so the suggestion lands on the actual
   *  dashboard grid. The AI package proposes; the host disposes. */
  onAdd?: (suggestion: PlotSuggestion) => void;
  /** Number of suggestions to ask for (default 4). */
  n?: number;
}

/**
 * Data-driven flow surface: triggers /ai/suggest-figures and renders the
 * resulting cards. Used by the host viewer when a user clicks "Suggest
 * figures" on a data collection (e.g. right after upload, or from the
 * data-collection detail page).
 */
const SuggestionsPanel: React.FC<Props> = ({
  dashboardId,
  dataCollectionId,
  onAdd,
  n = 4,
}) => {
  const session = useAISession(dashboardId);
  const { run, pending } = useSuggestFigures(dashboardId);
  const [items, setItems] = useState<PlotSuggestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function fetchSuggestions() {
    setError(null);
    try {
      const res = await run(dataCollectionId, n);
      setItems(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="center">
        <Group gap={6} align="center">
          <Icon icon="material-symbols:auto-graph" width={18} />
          <Text fw={600}>Suggested figures</Text>
        </Group>
        <Button
          size="xs"
          variant="light"
          leftSection={
            pending ? <Loader size={12} /> : <Icon icon="material-symbols:refresh" width={14} />
          }
          disabled={pending || !session.llmKey}
          onClick={fetchSuggestions}
        >
          {items ? 'Re-suggest' : 'Suggest'}
        </Button>
      </Group>

      {!session.llmKey && (
        <Alert color="yellow" variant="light">
          Add an LLM API key in the dashboard settings to enable suggestions.
        </Alert>
      )}

      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}

      {items && items.length === 0 && (
        <Alert color="gray" variant="light">
          No suggestions returned.
        </Alert>
      )}

      {items?.map((s, i) => (
        <Card key={i} withBorder padding="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2} style={{ flex: 1 }}>
              <Group gap="xs" align="center">
                <Badge variant="light" color="blue" size="sm">
                  {s.visu_type}
                </Badge>
                <Text fw={600} size="sm">
                  {s.title}
                </Text>
              </Group>
              <Text size="xs" c="dimmed">
                {s.explanation}
              </Text>
              {s.code && (
                <PythonCodeBlock
                  code={s.code}
                  flavor="Plotly Express"
                  tone="figure"
                  defaultOpen={false}
                />
              )}
            </Stack>
            {onAdd && (
              <Button
                size="xs"
                variant="filled"
                leftSection={<Icon icon="material-symbols:add" width={14} />}
                onClick={() => onAdd(s)}
              >
                Add
              </Button>
            )}
          </Group>
        </Card>
      ))}
    </Stack>
  );
};

export default SuggestionsPanel;
