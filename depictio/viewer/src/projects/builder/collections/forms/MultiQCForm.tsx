/** MultiQC properties: there are none to set, so this only says what happens. */
import React from 'react';
import { Group, Text } from '@mantine/core';

import { DcTypeIcon } from '../../../dcTypeIcon';

export const MultiQCForm: React.FC = () => (
  <Group gap="xs" wrap="nowrap" align="flex-start">
    <DcTypeIcon type="multiqc" size={18} withTooltip={false} />
    <Text size="xs" c="dimmed">
      Each matched MultiQC parquet is read as a whole: the report&apos;s general stats and plots
      become available to dashboards. Nothing to set here.
    </Text>
  </Group>
);
