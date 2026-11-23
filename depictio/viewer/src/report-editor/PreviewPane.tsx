import React from 'react';
import { Alert, Badge, Box, Button, Group, Loader, Skeleton, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { FrameBridge } from './useFrameBridge';
import type { PreviewJobApi } from './usePreviewJob';

function elapsedLabel(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
}

interface PreviewPaneProps {
  job: PreviewJobApi;
  bridge: FrameBridge;
}

/** The status chip above the frame. */
const StatusChip: React.FC<PreviewPaneProps> = ({ job, bridge }) => {
  if (job.error) {
    return (
      <Badge color="red" variant="light" leftSection={<Icon icon="mdi:alert-circle-outline" width={12} />}>
        Preview failed
      </Badge>
    );
  }
  if (job.rerendering) {
    return (
      <Badge color="yellow" variant="light" leftSection={<Loader size={10} />}>
        Re-rendering (filters changed)…
      </Badge>
    );
  }
  if (!job.previewUrl) return null;
  if (bridge.unresponsive) {
    return (
      <Badge color="gray" variant="light">
        Static preview: edits are not applied live
      </Badge>
    );
  }
  if (!bridge.frameReady) {
    return (
      <Badge color="gray" variant="light" leftSection={<Loader size={10} />}>
        Connecting…
      </Badge>
    );
  }
  return (
    <Badge color="green" variant="light" leftSection={<Icon icon="mdi:circle-medium" width={14} />}>
      Live
    </Badge>
  );
};

/** The right half of the page: the real report in a frame, kept in step with
 *  the edits on the left. */
const PreviewPane: React.FC<PreviewPaneProps> = ({ job, bridge }) => (
  <Stack gap="xs" h="100%" style={{ minHeight: 0 }} data-testid="report-preview-pane">
    <Group justify="space-between" wrap="nowrap">
      <Group gap="xs">
        <Text fw={600} size="sm">
          Preview
        </Text>
        <span data-testid="report-preview-status">
          <StatusChip job={job} bridge={bridge} />
        </span>
      </Group>
      <Button
        size="compact-xs"
        variant="subtle"
        color="gray"
        leftSection={<Icon icon="mdi:refresh" width={14} />}
        onClick={job.rerun}
        disabled={job.running}
        data-testid="report-preview-rerun"
      >
        Refresh data
      </Button>
    </Group>

    {job.error && (
      <Alert color="red" title="The preview failed">
        {job.error}
      </Alert>
    )}

    {!job.previewUrl && !job.error && (
      <Stack gap="sm" data-testid="report-preview-running">
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="sm">
            {job.phase} · {elapsedLabel(job.elapsed)}
          </Text>
        </Group>
        <Skeleton h={36} w="60%" />
        <Skeleton h={14} />
        <Skeleton h={14} w="90%" />
        <Skeleton h={220} />
        <Skeleton h={14} w="80%" />
        <Skeleton h={220} />
      </Stack>
    )}

    {job.previewUrl && (
      <Box
        style={{
          flex: 1,
          minHeight: 0,
          opacity: job.rerendering ? 0.6 : 1,
          transition: 'opacity 150ms',
        }}
      >
        <iframe
          ref={bridge.iframeRef}
          key={job.previewUrl}
          title="Report preview"
          src={job.previewUrl}
          sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
          onLoad={bridge.onFrameLoad}
          style={{ width: '100%', height: '100%', border: 0, background: 'var(--mantine-color-white)' }}
          data-testid="report-preview-frame"
        />
      </Box>
    )}
  </Stack>
);

export default PreviewPane;
