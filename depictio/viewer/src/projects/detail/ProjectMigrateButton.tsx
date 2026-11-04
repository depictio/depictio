import React, { useState } from 'react';
import { Button, Tooltip } from '@mantine/core';
import { Send } from 'lucide-react';

import MigrateProjectModal from '../MigrateProjectModal';
import { usePushTargets } from '../usePushTargets';
import { useMigrationUi } from '../../hooks/useMigrationUi';

/** Page-head action: send a copy of this project to another Depictio instance
 *  (the word matches `depictio migrate` and Admin > Migrations). Owners and
 *  admins only, and absent when this instance has no target configured or
 *  hides migration (`DEPICTIO_MIGRATION_UI_ENABLED`). */
export const ProjectMigrateButton: React.FC<{
  projectId: string;
  projectName?: string;
  canPush: boolean;
  /** Glass pages use bordered buttons in their head; the classic shell, subtle ones. */
  glass?: boolean;
}> = ({ projectId, projectName, canPush, glass }) => {
  const migrationUi = useMigrationUi();
  const targets = usePushTargets(canPush && migrationUi);
  const [open, setOpen] = useState(false);
  if (!canPush || !migrationUi || targets.length === 0) return null;
  return (
    <>
      <Tooltip label="Send a copy of this project to another Depictio instance" withinPortal>
        <Button
          variant={glass ? 'default' : 'subtle'}
          color={glass ? undefined : 'gray'}
          leftSection={<Send size={glass ? 17 : 16} strokeWidth={1.8} aria-hidden />}
          onClick={() => setOpen(true)}
          data-testid="project-push-button"
        >
          Migrate…
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
