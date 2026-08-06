import React from 'react';
import { Badge, Indicator, Tooltip } from '@mantine/core';

import { useServerStatus } from '../hooks/useServerStatus';

interface ServerStatusBadgeProps {
  /** Drop the label and keep the coloured dot, with the full text in a
   *  tooltip. For the sidebar footer, where four controls share a 250px rail
   *  and "Server online — v1.5.0" alone would claim the whole row. */
  compact?: boolean;
}

/**
 * Mirrors the Dash sidebar footer status badge:
 * - online → green dot, "Server online — v{version}"
 * - offline / unknown → red outline, "Server offline"
 */
const ServerStatusBadge: React.FC<ServerStatusBadgeProps> = ({ compact = false }) => {
  const { status, version } = useServerStatus();
  const online = status === 'online';
  const label = online
    ? version
      ? `Server online — v${version}`
      : 'Server online'
    : 'Server offline';

  if (compact) {
    return (
      <Tooltip label={label} withArrow>
        {/* `processing` only while online: a pulsing red dot reads as "working
            on it" when the truth is "not reachable". */}
        <Indicator
          color={online ? 'green' : 'red'}
          size={10}
          processing={online}
          aria-label={label}
        >
          <span style={{ display: 'block', width: 8, height: 8 }} />
        </Indicator>
      </Tooltip>
    );
  }

  if (online) {
    return (
      <Badge variant="dot" color="green" size="sm">
        {label}
      </Badge>
    );
  }

  return (
    <Badge variant="outline" color="red" size="sm">
      {label}
    </Badge>
  );
};

export default ServerStatusBadge;
