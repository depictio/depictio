/** Build the in-app href for a dashboard viewer/editor route. Used to wire
 *  cards and sidebar tabs as native `<a href>` elements so browser-level
 *  open-in-new-tab (middle-click, Cmd/Ctrl+Click, Shift+Click, context menu)
 *  works without explicit support code. */

import type { DashboardListEntry } from 'depictio-react-core';

export type DashboardMode = 'view' | 'edit';

export function dashboardHref(
  dashboardId: string,
  mode: DashboardMode = 'view',
): string {
  return mode === 'edit'
    ? `/dashboard-edit/${dashboardId}`
    : `/dashboard/${dashboardId}`;
}

export function dashboardHrefFor(d: DashboardListEntry, mode: DashboardMode = 'view'): string {
  return dashboardHref(String(d.dashboard_id), mode);
}

/** Detect whether a mouse event should bypass SPA navigation and fall through
 *  to the browser (open-in-new-tab, window, etc.). Returns true when the
 *  click should NOT be intercepted by the React onClick handler. */
function isModifiedClick(
  e: React.MouseEvent<HTMLElement> | MouseEvent,
): boolean {
  // Non-primary button (middle, right) — let the browser handle it.
  if (e.button !== 0) return true;
  return e.metaKey || e.ctrlKey || e.shiftKey || e.altKey;
}

/** Build an `onClick` for an `<a href>` rendered as a Mantine `component="a"`.
 *  - Lets modified clicks (middle/Cmd/Ctrl/Shift/Alt + non-left button) fall
 *    through so the browser opens a new tab/window.
 *  - On a plain left-click, prevents default navigation and invokes ``onPlain``
 *    so the SPA router can take over.
 *  Pass a falsy ``onPlain`` (``undefined``/``false``/``null``) to allow native
 *  navigation only — useful for conditional callbacks like
 *  ``cb && (() => cb(id))``. */
export function dashboardLinkClickHandler(
  onPlain: (() => void) | undefined | null | false,
): (e: React.MouseEvent<HTMLElement>) => void {
  return (e) => {
    if (!onPlain) return;
    if (isModifiedClick(e)) return;
    e.preventDefault();
    onPlain();
  };
}
