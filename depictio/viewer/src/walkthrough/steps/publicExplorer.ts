import type { WalkthroughDefinition } from '../types';

/** Public / explorer walkthrough — runs for anonymous visitors on an instance
 *  whose owner has flipped it to public mode to share their dashboards and
 *  datasets. Goal: (1) point at the available dashboards on the list page,
 *  then (2) once the visitor opens one, teach them how to read and use it.
 *
 *  Handles two entry points cleanly via auto-advance:
 *  - Lands on /dashboards-beta → welcome → pick a dashboard → tour resumes
 *    on /dashboard-beta/{id} with sidebar/filter/realtime.
 *  - Lands directly on /dashboard-beta/{id} → welcome → Next jumps past the
 *    list step (route guard doesn't match) → sidebar/filter/realtime.
 */
export const publicExplorerWalkthrough: WalkthroughDefinition = {
  id: 'public',
  // v3 — bumped after rewording for the "instance owner shared with you"
  // framing and restructuring to walk through the dashboards list.
  version: 'v3',
  label: 'Take the tour',
  steps: [
    {
      id: 'welcome',
      target: null,
      title: 'Welcome to Depictio',
      body: "👋 Welcome! This Depictio instance has been made public so the dashboards and datasets it contains can be shared. Open any dashboard below — the tour will show you how to use it.",
      position: 'bottom',
      image: {
        src: '/dashboard-beta/favicon.svg',
        alt: 'Depictio',
        height: 64,
      },
    },
    {
      id: 'pick-dashboard',
      target: 'dashboard-card',
      route: /^\/dashboards-beta\/?$/,
      title: 'Pick a dashboard',
      body: 'These are the dashboards shared on this instance. Click any of them to open it — the tour resumes inside.',
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
