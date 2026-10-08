/**
 * The run records found in a folder (`pipeline_info`, `multiqc`), written
 * the same wherever a folder is described: the folder browser's detail pane
 * and every hit of a run search.
 */
import React from 'react';
import { Badge, Group } from '@mantine/core';
import { Icon } from '@iconify/react';

const MARKER_ICON: Record<string, string> = {
  pipeline_info: 'mdi:information-outline',
  multiqc: 'mdi:chart-box-outline',
};

export const RunMarkers: React.FC<{ markers: string[]; testId?: string }> = ({ markers, testId }) => (
  <Group gap={4} wrap="wrap" data-testid={testId}>
    {markers.map((marker) => (
      <Badge
        key={marker}
        variant="default"
        size="sm"
        radius="sm"
        tt="none"
        fw={500}
        ff="monospace"
        leftSection={<Icon icon={MARKER_ICON[marker] ?? 'mdi:folder-outline'} width={12} />}
        style={{ flexShrink: 0 }}
        data-marker={marker}
      >
        {marker}
      </Badge>
    ))}
  </Group>
);
