import type { DashboardData } from 'depictio-react-core';

/** Does `email` appear in this dashboard's owners list? The shape lives at
 *  `dashboard.permissions.owners[].email` — the React-core `DashboardData`
 *  type leaves these fields under its open-ended index signature, so we
 *  narrow them inline rather than extending the shared type.
 *
 *  Used by App.tsx (viewer chrome) and EditorApp.tsx to gate the Edit /
 *  Add-component / Save affordances and to bounce non-owners off the editor
 *  route. The backend enforces the same rule with 403s on the relevant
 *  endpoints, so this layer is for UX clarity — affordances stay visible
 *  but disabled for non-owners, per the depictio convention. */
export function isDashboardOwner(
  dashboard: DashboardData | null,
  email: string | null,
): boolean {
  if (!email || !dashboard) return false;
  const perms = (
    dashboard as {
      permissions?: { owners?: Array<{ email?: string } | null> };
    }
  ).permissions;
  return Boolean(perms?.owners?.some((o) => o?.email === email));
}
