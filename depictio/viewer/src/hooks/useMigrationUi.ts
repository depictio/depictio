import { useServerInfo } from './useServerInfo';

/** Whether this instance shows the project migration controls (Migrate,
 *  Admin > Migrations, push targets, the editing lock switch). Set by
 *  `DEPICTIO_MIGRATION_UI_ENABLED`; off, and off while the answer is pending,
 *  so nothing flashes in and out. The API keeps its own settings either way. */
export function useMigrationUi(): boolean {
  const { info } = useServerInfo();
  return info?.features?.migration === true;
}
