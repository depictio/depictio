/**
 * In-place tab navigation for the static bundle.
 *
 * The viewer wires its left-rail tab pills (and its "Back to Dashboards" link)
 * as real `<a href="/dashboard/<id>">` anchors so middle-click / Cmd+Click open
 * a browser tab natively. A bundle has no routes: on `file://` every one of
 * those anchors is a navigation to a path that does not exist, and on a static
 * host it is a 404. So the runtime intercepts them at the document level, in
 * the CAPTURE phase — before React's root-container listeners and before the
 * browser's default action — and either switches tab in place or, for a route
 * this bundle cannot serve, does nothing at all.
 *
 * Two deliberate non-choices:
 *
 *   - No `history.pushState({}, '', '/dashboard/<id>')`. A `file://` document
 *     has an opaque origin, and pushing a URL that differs from the current one
 *     throws `SecurityError: Failed to execute 'pushState' on 'History'`. The
 *     URL simply does not move; `window.__DEPICTIO_STATIC_DASHBOARD_ID__` is
 *     what `extractDashboardId()` reads instead.
 *   - No blanket "swallow every click". Only the SPA's own routes are
 *     neutralised, so genuinely external links (an instance URL in the export
 *     provenance, docs links, blob: download anchors) keep working.
 */
import { isBundledTab, setActiveTab } from './bundle';

/** SPA routes served by the real viewer — see `main.tsx` route dispatch. A
 *  `/projects/…` link is the one with an answer inside a bundle: its own
 *  project page. */
const APP_ROUTE_RE =
  /^\/(dashboards?|dashboard-edit|projects?|groups|about|admin|profile|cli-agents|auth|login)(\/|$)/;
/** `/dashboard/<id>` and `/dashboard-edit/<id>` (the rail uses whichever mode). */
const DASHBOARD_ID_RE = /^\/(?:dashboard|dashboard-edit)\/([^/?#]+)/;
/** `/projects/<id>` (and its `#ingestion`, `?table=` variants). */
const PROJECT_RE = /^\/projects?\/[^/?#]+/;

/** What a same-document link to a SPA route means inside a bundle. */
export type BundleRoute =
  | { kind: 'tab'; id: string }
  | { kind: 'project' }
  /** A route this file cannot serve: the click must dead-end, not navigate. */
  | { kind: 'inert' };

/** Classify an app path; null when it is not a SPA route at all. */
export function bundleRouteFor(pathname: string): BundleRoute | null {
  if (!APP_ROUTE_RE.test(pathname)) return null;
  const id = pathname.match(DASHBOARD_ID_RE)?.[1];
  if (id) return { kind: 'tab', id: decodeURIComponent(id) };
  if (PROJECT_RE.test(pathname)) return { kind: 'project' };
  return { kind: 'inert' };
}

export interface BundleNavigationHandlers {
  /** A tab of this bundle was asked for; the caller re-renders App against it. */
  onSwitchTab: (tabId: string) => void;
  /** The dashboard's project was asked for. Returns false when the bundle has
   *  no project page to show, which leaves the click inert. */
  onOpenProject?: () => boolean;
}

/**
 * Install the capture-phase interceptor. Returns an uninstall function (React
 * 18 StrictMode mounts effects twice in dev).
 */
export function installBundleNavigation(
  handlers: BundleNavigationHandlers | ((tabId: string) => void),
): () => void {
  const { onSwitchTab, onOpenProject } =
    typeof handlers === 'function' ? { onSwitchTab: handlers, onOpenProject: undefined } : handlers;
  const handler = (event: MouseEvent) => {
    if (event.defaultPrevented) return;
    const target = event.target as Element | null;
    const anchor = target?.closest?.('a[href]') as HTMLAnchorElement | null;
    if (!anchor) return;
    // An explicit new-tab/window link is somebody deliberately leaving this
    // document — never an in-bundle route.
    if (anchor.target && anchor.target !== '_self') return;

    let url: URL;
    try {
      url = new URL(anchor.href, window.location.href);
    } catch {
      return;
    }
    // Same-document-origin only. On `file://` both sides stringify to "null",
    // which is exactly the case we must catch; an absolute `https://…` link to
    // the source instance has a real origin and is left alone.
    if (url.origin !== window.location.origin) return;
    // This very document (a `#section` or `?query` link): never an app route,
    // even when a static host serves the bundle under `/dashboards/…`.
    if (url.pathname === window.location.pathname) return;
    const route = bundleRouteFor(url.pathname);
    if (!route) return;

    // From here the anchor points at a route this document cannot reach.
    // Whether or not we can honour it, the navigation must not happen.
    event.preventDefault();

    if (route.kind === 'tab' && isBundledTab(route.id)) {
      setActiveTab(route.id);
      onSwitchTab(route.id);
    } else if (route.kind === 'project') {
      onOpenProject?.();
    }
    // Anything else (`/dashboards`, `/admin`, a tab id from outside this
    // family) is inert: the affordance is already hidden inside a bundle
    // (`useIsStaticBundle`), and a stray one must dead-end rather than blank
    // the page.
  };

  document.addEventListener('click', handler, true);
  return () => document.removeEventListener('click', handler, true);
}
