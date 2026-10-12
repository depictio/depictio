/**
 * The file picked in the tree: its path, what the server takes it for, and
 * its first rows with each column's dtype (the run-file preview, asked for
 * types). Nothing picked: how to start.
 */
import React from 'react';
import { Badge, Group, Paper, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type { BuilderSuggestion } from 'depictio-react-core';

import { RunFilePreviewView } from '../../fromRun/FilePreview';
import type { RunFilePreviewState } from '../../fromRun/FilePreview';
import { BuilderDcTypeIcon, DC_TYPE_META } from '../collections/dcTypes';
import { suggestedType } from '../collections/dcForm';

export const FilePane: React.FC<{
  activeFile: string | null;
  preview: RunFilePreviewState;
  suggestion: BuilderSuggestion | null;
  /** How many files are ticked as examples. */
  examples: number;
  workflowName: string;
}> = ({ activeFile, preview, suggestion, examples, workflowName }) => {
  const accent = useBrandAccents();
  if (!activeFile) {
    return (
      <Paper withBorder radius="md" p="xl" style={{ borderStyle: 'dashed' }} data-testid="builder-file-empty">
        <Stack gap="xs" align="center">
          <ThemeIcon variant="light" color={accent.secondary} size={56} radius="xl">
            <Icon icon="mdi:table-search" width={30} />
          </ThemeIcon>
          <Text fw={600}>Pick a file in the tree</Text>
          <Text size="sm" c="dimmed" ta="center" maw={440}>
            Its first rows show here and a data collection for{' '}
            <Text span fw={600} inherit>
              {workflowName}
            </Text>{' '}
            starts from it. Tick sibling files to cover many samples with one scan.
          </Text>
        </Stack>
      </Paper>
    );
  }
  const columns =
    preview.status === 'ready' && preview.preview.format === 'table' ? preview.preview.columns.length : null;
  return (
    <Paper withBorder radius="md" p="sm" data-testid="builder-file-pane" data-path={activeFile}>
      <Stack gap={6}>
        <Group gap="xs" wrap="nowrap">
          <Icon icon="mdi:file-eye-outline" width={18} color={`var(--mantine-color-${accent.secondary}-6)`} />
          <Text fw={600} size="sm" ff="monospace" truncate style={{ minWidth: 0 }}>
            {activeFile}
          </Text>
          {suggestion && (
            <Badge
              size="sm"
              variant="light"
              color="gray"
              tt="none"
              leftSection={<BuilderDcTypeIcon type={suggestedType(suggestion)} size={12} />}
              style={{ flexShrink: 0 }}
            >
              {DC_TYPE_META[suggestedType(suggestion)].label}
              {suggestion.format ? ` · ${suggestion.format}` : ''}
            </Badge>
          )}
          {columns !== null && (
            <Badge size="sm" variant="light" color="gray" tt="none" style={{ flexShrink: 0 }}>
              {columns} column{columns === 1 ? '' : 's'}
            </Badge>
          )}
          {examples > 1 && (
            <Badge size="sm" variant="light" color={accent.secondary} tt="none" style={{ flexShrink: 0 }}>
              {examples} examples
            </Badge>
          )}
        </Group>
        <RunFilePreviewView state={preview} />
      </Stack>
    </Paper>
  );
};
