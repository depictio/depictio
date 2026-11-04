import React, { useState } from 'react';
import { Button } from '@mantine/core';
import type { ButtonProps } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useCurrentUser } from '../hooks/useCurrentUser';
import { useMigrationUi } from '../hooks/useMigrationUi';
import { canSeeMigrations } from './access';
import ReceiveProjectModal from './ReceiveProjectModal';

/** Entry point for an admin to issue an invite code. Absent for everyone else,
 *  and while the instance hides migration (`DEPICTIO_MIGRATION_UI_ENABLED`). */
export const ReceiveProjectButton: React.FC<Pick<ButtonProps, 'variant' | 'size' | 'color'>> = (
  props,
) => {
  const migrationUi = useMigrationUi();
  const { user, isPublicMode, isDemoMode, isSingleUserMode } = useCurrentUser();
  const [open, setOpen] = useState(false);
  const allowed =
    migrationUi &&
    Boolean(user?.is_admin) &&
    canSeeMigrations({ user, isPublicMode, isDemoMode, isSingleUserMode });
  if (!allowed) return null;
  return (
    <>
      <Button
        variant="default"
        leftSection={<Icon icon="mdi:transfer-down" width={16} />}
        onClick={() => setOpen(true)}
        data-testid="receive-project-button"
        {...props}
      >
        Receive a project
      </Button>
      <ReceiveProjectModal opened={open} onClose={() => setOpen(false)} />
    </>
  );
};
