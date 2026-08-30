import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

interface InspectButtonProps {
  componentId: string;
  /** Drives the filled/subtle variant so the inspected component is identifiable
   *  from the grid, not only from the panel's own header. */
  active: boolean;
  onInspect: (componentId: string) => void;
}

/**
 * Opens the inspector on this component. Only rendered when the app provides an
 * `InspectorContext`, i.e. when the inspector feature is enabled.
 */
const InspectButton: React.FC<InspectButtonProps> = ({ componentId, active, onInspect }) => (
  <Tooltip label={active ? 'Close inspector' : 'Inspect'} withArrow>
    <ActionIcon
      variant={active ? 'filled' : 'subtle'}
      color="grape"
      size="sm"
      onClick={() => onInspect(componentId)}
      aria-label={active ? 'Close inspector' : 'Inspect component'}
      aria-pressed={active}
    >
      <Icon icon="mdi:dock-right" width={16} height={16} />
    </ActionIcon>
  </Tooltip>
);

export default InspectButton;
