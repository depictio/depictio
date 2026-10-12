/**
 * The file picked in the tree: its path, what the server takes it for, and
 * its first rows with each column's dtype (the run-file preview, asked for
 * types). A store (`*.zarr`) is never previewed: what `/suggest` read of it
 * shows instead (format, NGFF version, images, tables). Nothing picked: how
 * to start.
 */
import React from 'react';
import { Badge, Group, Loader, Paper, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type { BuilderStoreSummary, BuilderSuggestion } from 'depictio-react-core';

import { RunFilePreviewView } from '../../fromRun/FilePreview';
import type { RunFilePreviewState } from '../../fromRun/FilePreview';
import { BuilderDcTypeIcon, DC_TYPE_META } from '../collections/dcTypes';
import { suggestedType } from '../collections/dcForm';

const STORE_FORMAT_LABEL: Record<BuilderStoreSummary['format'], string> = {
  'ome-zarr': 'OME-Zarr',
  spatialdata: 'SpatialData',
};

/** What a store holds, as `/suggest` read it. */
const StoreSummary: React.FC<{ store: BuilderStoreSummary | null | undefined; loading: boolean }> = ({
  store,
  loading,
}) => {
  if (!store) {
    return loading ? (
      <Group gap="xs">
        <Loader size="xs" />
        <Text size="xs" c="dimmed">
          Reading the store...
        </Text>
      </Group>
    ) : (
      <Text size="xs" c="dimmed">
        A zarr store: it is read as one, not file by file.
      </Text>
    );
  }
  const row = (label: string, items: string[]) => (
    <Group gap={6} wrap="wrap" align="flex-start">
      <Text size="xs" fw={700} c="dimmed" tt="uppercase" w={64}>
        {label}
      </Text>
      {items.length ? (
        items.map((item) => (
          <Badge key={item} size="sm" variant="default" radius="sm" tt="none" ff="monospace">
            {item}
          </Badge>
        ))
      ) : (
        <Text size="xs" c="dimmed">
          none
        </Text>
      )}
    </Group>
  );
  return (
    <Stack gap={6} data-testid="builder-store-summary" data-format={store.format}>
      <Group gap="xs">
        <Badge size="sm" variant="light" color="pink" tt="none">
          {STORE_FORMAT_LABEL[store.format]}
        </Badge>
        <Badge size="sm" variant="light" color="gray" tt="none">
          NGFF {store.ngff_version ?? 'unknown'}
        </Badge>
      </Group>
      {row('Images', store.images)}
      {store.format === 'spatialdata' && row('Tables', store.tables)}
    </Stack>
  );
};

export const FilePane: React.FC<{
  activeFile: string | null;
  /** The picked entry is a store: never previewed. */
  store: boolean;
  preview: RunFilePreviewState;
  suggestion: BuilderSuggestion | null;
  suggesting: boolean;
  /** How many files are ticked as examples. */
  examples: number;
  workflowName: string;
}> = ({ activeFile, store, preview, suggestion, suggesting, examples, workflowName }) => {
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
          <Icon
            icon={store ? 'mdi:cube-outline' : 'mdi:file-eye-outline'}
            width={18}
            color={`var(--mantine-color-${accent.secondary}-6)`}
          />
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
        {store ? (
          <StoreSummary store={suggestion?.store} loading={suggesting} />
        ) : (
          <RunFilePreviewView state={preview} />
        )}
      </Stack>
    </Paper>
  );
};
