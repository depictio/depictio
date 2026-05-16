/**
 * Funnel-pin icon button for a filter card. Mirrors GlobeToggle: when the
 * filter is currently pinned to the active funnel, the icon renders filled;
 * clicking unpins. Otherwise it renders subtle and clicking pins.
 *
 * Edit-mode-only by convention — App.tsx gates rendering of this control
 * via the existing `extraActionsByIndex` map.
 */

import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

export interface FunnelPinToggleProps {
  pinned: boolean;
  onClick: () => void;
  /** Override the default tooltip text. */
  tooltip?: string;
  size?: number;
  disabled?: boolean;
}

const DEFAULT_PIN_TIP = 'Pin to funnel — adds this filter as a step in the active funnel';
const DEFAULT_UNPIN_TIP = 'Unpin from funnel';

const FunnelPinToggle: React.FC<FunnelPinToggleProps> = ({
  pinned,
  onClick,
  tooltip,
  size = 18,
  disabled = false,
}) => {
  const label = tooltip ?? (pinned ? DEFAULT_UNPIN_TIP : DEFAULT_PIN_TIP);
  return (
    <Tooltip label={label} withArrow position="top">
      <ActionIcon
        variant={pinned ? 'filled' : 'subtle'}
        color={pinned ? 'violet' : 'gray'}
        size="sm"
        aria-label={label}
        onClick={onClick}
        disabled={disabled}
      >
        <Icon icon={pinned ? 'tabler:filter-check' : 'tabler:filter-plus'} width={size} />
      </ActionIcon>
    </Tooltip>
  );
};

export default FunnelPinToggle;
