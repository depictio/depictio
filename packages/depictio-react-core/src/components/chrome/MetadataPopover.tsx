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
 * from drifting. The trigger icon turns violet when the component was added
 * from the tools catalog, echoing the "Catalog" badge in the body itself.
 */
const MetadataPopover: React.FC<MetadataPopoverProps> = ({ metadata }) => {
  const isCatalog = Boolean(metadata.catalog_source);
  return (
    <Popover position="bottom-end" withArrow shadow="md" width={380}>
      <Popover.Target>
        <Tooltip label="Component metadata" withArrow>
          <ActionIcon
            variant="subtle"
            color={isCatalog ? 'violet' : 'cyan'}
            size="sm"
            aria-label="Component metadata"
          >
            <Icon icon="mdi:information-outline" width={16} height={16} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p="sm">
        <ScrollArea.Autosize mah={460} type="auto">
          <MetadataBody metadata={metadata} />
        </ScrollArea.Autosize>
      </Popover.Dropdown>
    </Popover>
  );
};

export default MetadataPopover;
