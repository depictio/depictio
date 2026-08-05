import React from 'react';
import { ActionIcon, Popover, ScrollArea, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';
import MetadataBody from './MetadataBody';

interface MetadataPopoverProps {
  metadata: StoredMetadata;
}

/**
 * Popover wrapper around `MetadataBody`. The inspector's Info tab renders the
 * same body docked; keeping the content in one component is what stops the two
 * from drifting.
 */
const MetadataPopover: React.FC<MetadataPopoverProps> = ({ metadata }) => (
  <Popover position="bottom-end" withArrow shadow="md" width={420}>
    <Popover.Target>
      <Tooltip label="Component metadata" withArrow>
        <ActionIcon variant="light" color="cyan" size="sm" aria-label="Component metadata">
          <Icon icon="mdi:information-outline" width={16} height={16} />
        </ActionIcon>
      </Tooltip>
    </Popover.Target>
    <Popover.Dropdown p="xs">
      <ScrollArea.Autosize mah={440} type="auto">
        <MetadataBody metadata={metadata} />
      </ScrollArea.Autosize>
    </Popover.Dropdown>
  </Popover>
);

export default MetadataPopover;
