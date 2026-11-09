import React from 'react';

import { canSeeMigrations } from '../admin/access';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { useMigrationUi } from '../hooks/useMigrationUi';
import ImportProjectModal from './ImportProjectModal';

interface ImportProjectDialogProps {
  opened: boolean;
  onClose: () => void;
  onImport: (file: File, overwrite: boolean) => Promise<void>;
}

/** The way in for a project that exists elsewhere: another instance
 *  (administrators, where migration is on) or a .zip bundle. Opened from the
 *  quiet row of the new-project dialog. */
export const ImportProjectDialog: React.FC<ImportProjectDialogProps> = ({
  opened,
  onClose,
  onImport,
}) => {
  const migrationUi = useMigrationUi();
  const { user, isPublicMode, isDemoMode, isSingleUserMode } = useCurrentUser();
  const canReceive =
    migrationUi &&
    Boolean(user?.is_admin) &&
    canSeeMigrations({ user, isPublicMode, isDemoMode, isSingleUserMode });
  return (
    <ImportProjectModal opened={opened} onClose={onClose} onImport={onImport} canReceive={canReceive} />
  );
};
