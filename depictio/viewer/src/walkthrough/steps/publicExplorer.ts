import type { WalkthroughDefinition } from '../types';

interface PublicExplorerOptions {
  /** TTL of a temporary public-mode user (hours). Surfaced in the duplicate
   *  step so the visitor knows exactly how long their copy will live. */
  expiryHours: number;
  expiryMinutes: number;
}

/** Format a `Nh` or `Nh Mm` string from the auth.temporary_user_expiry_* pair.
 *  Hours-only is the common case (default 24h), so keep that path clean. */
function formatExpiry(hours: number, minutes: number): string {
  if (minutes <= 0) return `${hours}h`;
  if (hours <= 0) return `${minutes}m`;
  return `${hours}h ${minutes}m`;
}

/** Public / explorer walkthrough — runs for anonymous visitors on an instance
 *  whose owner has flipped it to public mode to share their dashboards and
 *  datasets. Goal: (1) point at the available dashboards on the list page,
 *  (2) once the visitor opens one, teach them how to read and use it, and
 *  (3) tell them they can duplicate any dashboard into their own temporary
 *  session if they want to tweak things.
 *
 *  Handles two entry points cleanly via auto-advance:
 *  - Lands on /dashboards-beta → welcome → pick a dashboard → tour resumes
 *    on /dashboard-beta/{id} with sidebar/filter/realtime.
 *  - Lands directly on /dashboard-beta/{id} → welcome → Next jumps past the
 *    list step (route guard doesn't match) → sidebar/filter/realtime.
 */
export function buildPublicExplorerWalkthrough(
  opts: PublicExplorerOptions,
): WalkthroughDefinition {
  const ttl = formatExpiry(opts.expiryHours, opts.expiryMinutes);
  return {
    id: 'public',
    // v6 — bumped after replacing the centered duplicate card with two
    // anchored steps that actually show *how* to duplicate (menu trigger →
    // Duplicate item).
    version: 'v6',
    label: 'Take the tour',
    steps: [
      {
        id: 'welcome',
        target: null,
        title: 'Welcome to Depictio',
        body: `👋 Welcome! This Depictio instance has been made public so the dashboards and datasets it contains can be shared. Open any dashboard below to explore it — or **duplicate** one to get your own editable copy in a temporary session (lasts ${ttl}). The tour walks you through both.`,
        position: 'bottom',
        image: {
          src: '/dashboard-beta/favicon.svg',
          alt: 'Depictio',
          height: 64,
        },
      },
      {
        id: 'dashboard-actions',
        target: 'dashboard-actions',
        route: /^\/dashboards-beta\/?$/,
        title: "Each dashboard's actions menu",
        body: 'Every dashboard has a menu here. Click it to see what you can do with this dashboard — including making your own copy.',
        position: 'left',
        awaitClick: true,
      },
      {
        id: 'dashboard-duplicate',
        target: 'dashboard-duplicate',
        route: /^\/dashboards-beta\/?$/,
        title: 'Duplicate to get your own copy',
        body: `Pick **Duplicate** to spin up your own editable copy in a temporary session (lasts ${ttl}). Tweak filters, rearrange components, save your view — the copy disappears when your session expires. Or hit Next to keep exploring without duplicating.`,
        position: 'left',
        awaitClick: true,
      },
      {
        id: 'pick-dashboard',
        target: 'dashboard-card',
        route: /^\/dashboards-beta\/?$/,
        title: 'Open a dashboard',
        body: 'Click any dashboard card to dive in — the tour resumes inside.',
        position: 'right',
        awaitClick: true,
      },
      {
        id: 'sidebar',
        target: 'sidebar',
        route: /^\/dashboard-beta\//,
        title: 'Navigate dashboard tabs',
        body: 'Each dashboard can have multiple tabs. Switch between them from the sidebar.',
        position: 'right',
      },
      {
        id: 'filter-panel',
        target: 'filter-panel',
        route: /^\/dashboard-beta\//,
        title: 'Filter the data',
        body: 'Use these interactive controls to narrow what every chart, card, and table shows. Selections propagate across the whole dashboard.',
        position: 'right',
      },
      {
        id: 'realtime',
        target: 'realtime-indicator',
        route: /^\/dashboard-beta\//,
        title: 'Live updates',
        body: 'When upstream data changes, this pill lights up. Open Settings to switch on auto-refresh, or click to refresh manually.',
        position: 'bottom',
      },
      {
        id: 'done',
        target: null,
        title: "You're all set",
        body: "That's the tour. Keep exploring at your own pace — and check out the Projects page if you want to dig into the underlying datasets too. You can re-launch this tour any time from the user menu.",
        position: 'bottom',
      },
    ],
  };
}
