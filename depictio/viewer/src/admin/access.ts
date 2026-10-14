import type { CurrentUser } from '../hooks/useCurrentUser';

interface AdminModes {
  user: CurrentUser | null;
  isPublicMode: boolean;
  isDemoMode: boolean;
  isSingleUserMode: boolean;
}

/** A personal instance, or one with accounts: the admin surface is the real one. */
function isTrustedInstance({ isPublicMode, isDemoMode, isSingleUserMode }: AdminModes): boolean {
  return isSingleUserMode || (!isPublicMode && !isDemoMode);
}

/**
 * Whether the Log & Task views (tasks, ingestion, watchers, logs, health) are
 * offered. A public instance has real admins who sign in, so they get them
 * there too; a temporary guest never does, and a demo instance has no real
 * admin at all. The API enforces the same rule.
 */
export function canSeeMonitoring(modes: AdminModes): boolean {
  if (isTrustedInstance(modes)) return true;
  const { user, isPublicMode, isDemoMode } = modes;
  return isPublicMode && !isDemoMode && Boolean(user?.is_admin) && !user?.is_temporary;
}

/** Whole-database backup and restore stay with trusted instances only. */
export function canSeeBackups(modes: AdminModes): boolean {
  return isTrustedInstance(modes);
}
