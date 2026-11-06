import React, { useState } from 'react';
import { Button, Tooltip } from '@mantine/core';
import type { ButtonProps } from '@mantine/core';
import { Icon } from '@iconify/react';

import { canSeeMigrations } from '../admin/access';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { useMigrationUi } from '../hooks/useMigrationUi';
import ImportProjectModal from './ImportProjectModal';

interface ImportProjectButtonProps extends Pick<ButtonProps, 'variant' | 'size' | 'color'> {
  onImport: (file: File, overwrite: boolean) => Promise<void>;
  /** Importing creates a project: off where creating one is (public mode, non-admin). */
  disabled?: boolean;
}

/**
 * The Projects page's one way in for a project that exists elsewhere: another
 * instance (administrators, where migration is on) or a .zip bundle.
 */
export const ImportProjectButton: React.FC<ImportProjectButtonProps> = ({
  onImport,
  disabled = false,
  ...props
}) => {
  const migrationUi = useMigrationUi();
  const { user, isPublicMode, isDemoMode, isSingleUserMode } = useCurrentUser();
  const [open, setOpen] = useState(false);
  const canReceive =
    migrationUi &&
    Boolean(user?.is_admin) &&
    canSeeMigrations({ user, isPublicMode, isDemoMode, isSingleUserMode });
  return (
    <>
      <Tooltip
        label="Importing is disabled in public or demo mode for non-admin users"
        disabled={!disabled}
        withArrow
      >
        <Button
          variant="default"
          leftSection={<Icon icon="mdi:transfer-down" width={16} />}
          onClick={() => setOpen(true)}
          disabled={disabled}
          data-disabled={disabled ? true : undefined}
          data-testid="import-project-button"
          {...props}
        >
          Import
        </Button>
      </Tooltip>
      <ImportProjectModal
        opened={open}
        onClose={() => setOpen(false)}
        onImport={onImport}
        canReceive={canReceive}
      />
    </>
  );
};
