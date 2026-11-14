import React, { useEffect, useState } from 'react';
import { ActionIcon, Popover, ScrollArea, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';
import MetadataBody from './MetadataBody';
import { TILE_ACTION_STYLE } from './actionStyles';

const STYLE = TILE_ACTION_STYLE.metadata;

interface MetadataPopoverProps {
  metadata: StoredMetadata;
}

const OPEN_EVENT = 'depictio:open-component-info';

/** Open a component's Info popover from inside its tile (a badge that says
 *  "more about this" opens the panel that has it). */
export function openComponentInfo(index: string): void {
  window.dispatchEvent(new CustomEvent<string>(OPEN_EVENT, { detail: index }));
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
  const [opened, setOpened] = useState(false);
  const index = String(metadata.index);
  useEffect(() => {
    const onOpen = (e: Event) => {
      if ((e as CustomEvent<string>).detail === index) setOpened(true);
    };
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_EVENT, onOpen);
  }, [index]);
  return (
    <Popover
      position="bottom-end"
      withArrow
      shadow="md"
      width={380}
      opened={opened}
      onChange={setOpened}
    >
      <Popover.Target>
        <Tooltip label={STYLE.label} withArrow>
          <ActionIcon
            variant="subtle"
            color={STYLE.color}
            size="sm"
            aria-label={STYLE.label}
            onClick={() => setOpened((o) => !o)}
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
