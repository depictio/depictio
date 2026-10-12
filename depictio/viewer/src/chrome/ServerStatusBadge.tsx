import React from 'react';
import { Badge, UnstyledButton } from '@mantine/core';

import { useServerStatus } from '../hooks/useServerStatus';
import { ServerInfoPopover, UpdateDot } from './server';

/**
 * Mirrors the Dash sidebar footer status badge:
 * - online → green dot, "Server online · v{version}"
 * - offline / unknown → red outline, "Server offline"
 *
 * The badge is also the way into the server info popover (version, links,
 * and for an admin the update notice), so it sits in a real button; the
 * badge itself is drawn as before.
 */
const ServerStatusBadge: React.FC = () => {
  const { status, version } = useServerStatus();
  const online = status === 'online';

  return (
    <ServerInfoPopover>
      {({ label, updateDot }) => (
        <UnstyledButton
          aria-label={label(online ? 'Server information (online)' : 'Server information (offline)')}
          style={{ position: 'relative', color: 'inherit' }}
          data-testid="server-status-badge"
        >
          {online ? (
            <Badge variant="dot" color="green" size="sm" style={{ cursor: 'pointer' }}>
              {version ? `Server online · v${version}` : 'Server online'}
            </Badge>
          ) : (
            <Badge variant="outline" color="red" size="sm" style={{ cursor: 'pointer' }}>
              Server offline
            </Badge>
          )}
          {updateDot && <UpdateDot />}
        </UnstyledButton>
      )}
    </ServerInfoPopover>
  );
};

export default ServerStatusBadge;
