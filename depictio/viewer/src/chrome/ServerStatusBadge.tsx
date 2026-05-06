import React from 'react';
import { Badge } from '@mantine/core';

import { useServerStatus } from '../hooks/useServerStatus';

/**
 * Mirrors the Dash sidebar footer status badge:
 * - online → green dot, "Server online — v{version}"
 * - offline / unknown → red outline, "Server offline"
 */
const ServerStatusBadge: React.FC = () => {
  const { status, version } = useServerStatus();

  if (status === 'online') {
    return (
      <Badge variant="dot" color="green" size="sm">
        {version ? `Server online — v${version}` : 'Server online'}
      </Badge>
    );
  }

  return (
    <Badge variant="outline" color="red" size="sm">
      Server offline
    </Badge>
  );
};

export default ServerStatusBadge;
