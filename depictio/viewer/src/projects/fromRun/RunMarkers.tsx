/**
 * The records a pipeline run leaves beside its results, which is how
 * Depictio tells a run folder from any other folder: a `pipeline_info`
 * folder (the engine's report of the run) and a MultiQC report. Written the
 * same wherever a folder is described: the folder browser's detail pane and
 * every hit of a run search.
 */
import React from 'react';
import { Badge, Group, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { Z_LAYERS } from 'depictio-react-core';

import { DcTypeIcon } from '../dcTypeIcon';

export const MARKER_META: Record<string, { label: string; description: string }> = {
  pipeline_info: {
    label: 'pipeline_info',
    description:
      'The report the workflow engine writes about the run: pipeline and version, parameters, tools run.',
  },
  multiqc: {
    label: 'MultiQC',
    description: 'The MultiQC report: the quality control summary of every sample in the run.',
  },
};

/** The mark of a run record: the MultiQC logo, or the engine report's icon. */
export const MarkerIcon: React.FC<{ marker: string; size?: number }> = ({ marker, size = 12 }) =>
  marker === 'multiqc' ? (
    <DcTypeIcon type="multiqc" size={size} withTooltip={false} />
  ) : (
    <Icon icon="mdi:folder-information-outline" width={size} />
  );

export const RunMarkers: React.FC<{ markers: string[]; testId?: string }> = ({ markers, testId }) => (
  <Group gap={4} wrap="wrap" data-testid={testId}>
    {markers.map((marker) => (
      <Tooltip
        key={marker}
        label={MARKER_META[marker]?.description ?? marker}
        withArrow
        multiline
        maw={280}
        zIndex={Z_LAYERS.tooltip}
      >
        <Badge
          variant="default"
          size="sm"
          radius="sm"
          tt="none"
          fw={500}
          leftSection={<MarkerIcon marker={marker} />}
          style={{ flexShrink: 0 }}
          data-marker={marker}
        >
          {MARKER_META[marker]?.label ?? marker}
        </Badge>
      </Tooltip>
    ))}
  </Group>
);
