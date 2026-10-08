import React from 'react';
import { ActionIcon, Popover, ScrollArea, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';
import MetadataBody from './MetadataBody';
import { TILE_ACTION_STYLE } from './actionStyles';

const STYLE = TILE_ACTION_STYLE.metadata;

interface MetadataPopoverProps {
  metadata: StoredMetadata;
}

/**
 * Popover wrapper around `MetadataBody`. The inspector's Info tab renders the
 * same body docked; keeping the content in one component is what stops the two
 * from drifting.
 *
 * One colour, always. The trigger used to turn violet for a catalog-added
 * component, which made the same component's icon violet on a dashboard and
 * cyan in the catalog preview (where nothing is stamped as catalog-sourced yet):
 * a colour that meant "which surface am I on" rather than "what is this".
 * Catalog origin has its own violet action in the same cluster (`CatalogButton`),
 * so this one is free to just mean metadata.
 */
const MetadataPopover: React.FC<MetadataPopoverProps> = ({ metadata }) => {
  return (
    <Popover position="bottom-end" withArrow shadow="md" width={380}>
      <Popover.Target>
        <Tooltip label={STYLE.label} withArrow>
          <ActionIcon
            variant="subtle"
            color={STYLE.color}
            size="sm"
            aria-label={STYLE.label}
          >
            <Icon icon={STYLE.icon} width={16} height={16} />
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
