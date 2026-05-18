import type { ProjectListEntry } from 'depictio-react-core';

export type Role = 'Owner' | 'Editor' | 'Viewer';

/** Mirror of `_determine_user_role` (depictio/dash/layouts/projects.py:1303) and
 *  the React-side helper in ProjectCard.tsx. Owner > Editor > Viewer. */
export function determineRole(
  project: ProjectListEntry,
  userId: string | null,
): Role | null {
  if (!userId) return null;
  const perms = project.permissions ?? {};
  const isInList = (list?: Array<{ _id?: string; id?: string }>) =>
    !!list?.some((u) => (u._id ?? u.id) === userId);
  if (isInList(perms.owners)) return 'Owner';
  if (isInList(perms.editors)) return 'Editor';
  if (isInList(perms.viewers)) return 'Viewer';
  return null;
}
