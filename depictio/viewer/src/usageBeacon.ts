import { sendUsageHit } from 'depictio-react-core';

/** Which app a path opens, for the internal usage statistics. */
export function usagePathKind(pathname: string): { kind: string; dashboardId: string | null } {
  const dash = pathname.match(/^\/dashboard(-edit)?\/([0-9a-f]{24})/);
  if (dash) return { kind: dash[1] ? 'editor' : 'viewer', dashboardId: dash[2] };
  const first = pathname.split('/')[1] || 'dashboards';
  const kind = /^[a-z-]{1,32}$/.test(first) ? first : 'other';
  return { kind, dashboardId: null };
}

/** One beacon per page load. Headless `/embed` renders are not visits. */
export function trackPageView(): void {
  const { pathname } = window.location;
  if (pathname.startsWith('/embed/')) return;
  const { kind, dashboardId } = usagePathKind(pathname);
  try {
    sendUsageHit({ path_kind: kind, dashboard_id: dashboardId });
  } catch {
    // Statistics must never stop the app from rendering.
  }
}
