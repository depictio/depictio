import React, { useState } from 'react';
import { Button, Menu } from '@mantine/core';
import { ChevronDown, Lock, LockOpen, Send } from 'lucide-react';

import MigrateProjectModal from '../MigrateProjectModal';
import { usePushTargets } from '../usePushTargets';
import { PublishedLockModal } from './PublishedLockControl';

/** Page-head action grouping what publishes a project: pushing it to another
 *  instance (owners and admins, when a target exists) and the read-only lock
 *  (admins). Its state is shown by the "Published (read-only)" badge in the
 *  project card; this menu only holds the actions. Absent when it would be empty. */
export const ProjectPublishMenu: React.FC<{
  projectId: string;
  projectName?: string;
  canPush: boolean;
  isAdmin: boolean;
  locked: boolean;
  onLockChanged: () => void;
  /** Glass pages use bordered buttons in their head; the classic shell, subtle ones. */
  glass?: boolean;
}> = ({ projectId, projectName, canPush, isAdmin, locked, onLockChanged, glass }) => {
  const targets = usePushTargets(canPush);
  const [pushOpen, setPushOpen] = useState(false);
  const [lockOpen, setLockOpen] = useState(false);

  const showPush = canPush && targets.length > 0;
  if (!showPush && !isAdmin) return null;

  return (
    <>
      <Menu position="bottom-end" shadow="md" withinPortal>
        <Menu.Target>
          <Button
            variant={glass ? 'default' : 'subtle'}
            color={glass ? undefined : 'gray'}
            leftSection={<Send size={glass ? 17 : 16} strokeWidth={1.8} aria-hidden />}
            rightSection={<ChevronDown size={14} strokeWidth={2} aria-hidden />}
            data-testid="project-publish-menu"
          >
            Publish
          </Button>
        </Menu.Target>
        <Menu.Dropdown>
          {showPush && (
            <Menu.Item
              leftSection={<Send size={15} strokeWidth={1.8} aria-hidden />}
              onClick={() => setPushOpen(true)}
              data-testid="project-push-button"
            >
              Push to another instance…
            </Menu.Item>
          )}
          {showPush && isAdmin && <Menu.Divider />}
          {isAdmin &&
            (locked ? (
              <Menu.Item
                color="orange"
                leftSection={<LockOpen size={15} strokeWidth={1.8} aria-hidden />}
                onClick={() => setLockOpen(true)}
                data-testid="project-unlock-button"
              >
                Unlock project
              </Menu.Item>
            ) : (
              <Menu.Item
                leftSection={<Lock size={15} strokeWidth={1.8} aria-hidden />}
                onClick={() => setLockOpen(true)}
                data-testid="project-lock-button"
              >
                Publish read-only…
              </Menu.Item>
            ))}
        </Menu.Dropdown>
      </Menu>
      {showPush && (
        <MigrateProjectModal
          opened={pushOpen}
          onClose={() => setPushOpen(false)}
          projectId={projectId}
          projectName={projectName}
        />
      )}
      {isAdmin && (
        <PublishedLockModal
          opened={lockOpen}
          onClose={() => setLockOpen(false)}
          projectId={projectId}
          locked={locked}
          onChanged={onLockChanged}
        />
      )}
    </>
  );
};
