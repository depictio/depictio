import React, { useState } from 'react';
import { Button, Tooltip } from '@mantine/core';
import { Send } from 'lucide-react';

import MigrateProjectModal from '../MigrateProjectModal';
import { usePublishAvailable } from '../usePushTargets';
import { useMigrationUi } from '../../hooks/useMigrationUi';

/** Page-head action: publish a copy of this project to another Depictio instance
 *  (to a registered target, or with a destination URL + invite code). Owners and
 *  admins only, and absent when this instance has neither a target nor URL
 *  publishing, or hides migration (`DEPICTIO_MIGRATION_UI_ENABLED`). */
export const ProjectMigrateButton: React.FC<{
  projectId: string;
  projectName?: string;
  canPush: boolean;
  /** Glass pages use bordered buttons in their head; the classic shell, subtle ones. */
  glass?: boolean;
}> = ({ projectId, projectName, canPush, glass }) => {
  const migrationUi = useMigrationUi();
  const available = usePublishAvailable(canPush && migrationUi);
  const [open, setOpen] = useState(false);
  if (!canPush || !migrationUi || !available) return null;
  return (
    <>
      <Tooltip label="Publish a copy of this project to another Depictio instance" withinPortal>
        <Button
          variant={glass ? 'default' : 'subtle'}
          color={glass ? undefined : 'gray'}
          leftSection={<Send size={glass ? 17 : 16} strokeWidth={1.8} aria-hidden />}
          onClick={() => setOpen(true)}
          data-testid="project-push-button"
        >
          Publish to…
        </Button>
      </Tooltip>
      <MigrateProjectModal
        opened={open}
        onClose={() => setOpen(false)}
        projectId={projectId}
        projectName={projectName}
      />
    </>
  );
};
