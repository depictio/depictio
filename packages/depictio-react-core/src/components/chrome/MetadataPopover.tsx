import React from 'react';
import { ActionIcon, Code, Popover, ScrollArea, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';

interface MetadataPopoverProps {
  metadata: StoredMetadata;
}

/**
 * Read-only metadata inspector. Mirrors the behaviour of
 * `create_metadata_button` in `depictio/dash/layouts/edit.py:676-832`, but
 * trimmed to the view-accessible subset: a JSON dump of the component's
 * stored_metadata. Uses Mantine `Code` (not @mantine/code-highlight) to keep
 * the dependency footprint minimal.
 */
const MetadataPopover: React.FC<MetadataPopoverProps> = ({ metadata }) => {
  const json = React.useMemo(() => JSON.stringify(metadata, null, 2), [metadata]);

  return (
    <Popover position="bottom-end" withArrow shadow="md" width={420}>
      <Popover.Target>
        <Tooltip label="Component metadata" withArrow>
          <ActionIcon variant="light" color="cyan" size="sm" aria-label="Component metadata">
            <Icon icon="mdi:information-outline" width={16} height={16} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p="xs">
        <ScrollArea.Autosize mah={400} type="auto">
          <Code block style={{ fontSize: 11, lineHeight: 1.4 }}>
            {json}
          </Code>
        </ScrollArea.Autosize>
      </Popover.Dropdown>
    </Popover>
  );
};

export default MetadataPopover;
