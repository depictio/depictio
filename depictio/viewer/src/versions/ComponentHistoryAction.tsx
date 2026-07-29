/**
 * The per-component entry point into version history.
 *
 * A hover-revealed action on each grid cell, mirroring the editor's edit
 * overlay in position and weight so the two read as the same affordance in
 * different modes. Read-only, so it belongs in the viewer where the editor's
 * writing counterpart does not.
 */

import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { StoredMetadata } from 'depictio-react-core';

interface ComponentHistoryActionProps {
  metadata: StoredMetadata;
  onOpen: (metadata: StoredMetadata) => void;
  /** Hidden when the dashboard has no recorded versions — an action that can
   *  only ever open an empty modal is worse than no action. */
  disabled?: boolean;
}

const ComponentHistoryAction: React.FC<ComponentHistoryActionProps> = ({
  metadata,
  onOpen,
  disabled,
}) => {
  if (disabled) return null;

  return (
    <Tooltip label="Component history" withArrow position="left" openDelay={400}>
      <ActionIcon
        variant="subtle"
        color="gray"
        size="sm"
        onClick={(event) => {
          // The cell behind this is a drag target in some hosts and a filter
          // source in others; neither should fire from opening history.
          event.stopPropagation();
          onOpen(metadata);
        }}
        aria-label="Component history"
        data-testid="component-history-action"
      >
        <Icon icon="mdi:history" width={15} />
      </ActionIcon>
    </Tooltip>
  );
};

export default ComponentHistoryAction;
