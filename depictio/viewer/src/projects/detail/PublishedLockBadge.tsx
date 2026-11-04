import React from 'react';
import { Badge, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { PublishedLock } from 'depictio-react-core';

/** Shown when editing of a project (or its dashboards) is locked. Says nothing
 *  about visibility: a read-only project can be public or private. */
export const PublishedLockBadge: React.FC<{
  lock?: Pick<PublishedLock, 'locked_at' | 'reason'> &
    Partial<Pick<PublishedLock, 'locked_by_email' | 'source'>> | null;
}> = ({ lock }) => {
  if (!lock) return null;
  const by = lock.locked_by_email ?? (lock.source === 'migration' ? 'migration' : null);
  return (
    <Tooltip
      multiline
      withinPortal
      w={300}
      label={
        <div>
          <div>Editing is locked: nobody can change it, owners included.</div>
          <div>Locked at: {lock.locked_at}</div>
          {lock.reason && <div>Reason: {lock.reason}</div>}
          {by && <div>By: {by}</div>}
        </div>
      }
    >
      <Badge
        size="sm"
        variant="light"
        color="orange"
        radius="sm"
        leftSection={<Icon icon="mdi:lock-outline" width={12} />}
        style={{ cursor: 'default' }}
      >
        Read-only
      </Badge>
    </Tooltip>
  );
};
