/**
 * Globe icon button that promotes a per-tab interactive filter to "global"
 * (cross-tab) scope. Renders both in the viewer (in component headers, click
 * → promote against the current local snapshot) and in the editor (in the
 * component config drawer, click → toggle the draft `globalFilterLink`).
 */

import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

export interface GlobeToggleProps {
  active: boolean;
  onClick: () => void;
  /** Override the default tooltip text — useful in the editor where the
   *  semantic is "include in global filters" rather than "promote now". */
  tooltip?: string;
  size?: number;
  disabled?: boolean;
}

const DEFAULT_PROMOTE_TIP = 'Promote to global filter — applies across all tabs';
const DEFAULT_DEMOTE_TIP = 'Demote — this filter applies only on the current tab';

const GlobeToggle: React.FC<GlobeToggleProps> = ({
  active,
  onClick,
  tooltip,
  size = 18,
  disabled = false,
}) => {
  const label = tooltip ?? (active ? DEFAULT_DEMOTE_TIP : DEFAULT_PROMOTE_TIP);
  return (
    <Tooltip label={label} withArrow position="top">
      <ActionIcon
        variant={active ? 'filled' : 'subtle'}
        color={active ? 'blue' : 'gray'}
        size="sm"
        aria-label={label}
        onClick={onClick}
        disabled={disabled}
      >
        <Icon icon={active ? 'tabler:world' : 'tabler:world-off'} width={size} />
      </ActionIcon>
    </Tooltip>
  );
};

export default GlobeToggle;
