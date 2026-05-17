import type { WalkthroughDefinition } from '../types';

/** Public / explorer walkthrough — runs for anonymous visitors on demo or
 *  public-mode deployments. Goal: communicate what a dashboard is and let
 *  the user feel the interactive filtering. No CTA at the end. */
export const publicExplorerWalkthrough: WalkthroughDefinition = {
  id: 'public',
  version: 'v2',
  label: 'Take the tour',
  steps: [
    {
      id: 'welcome',
      target: null,
      title: 'Welcome to Depictio',
      body: "👋 You've landed in a live demo — explore freely, reviewer #2 isn't watching. Let's take a quick tour of what dashboards can do.",
      position: 'bottom',
      image: {
        src: '/dashboard-beta/favicon.svg',
        alt: 'Depictio',
        height: 64,
      },
    },
    {
      id: 'sidebar',
      target: 'sidebar',
      route: /^\/dashboard-beta\//,
      title: 'Navigate dashboards',
      body: 'Each dashboard can have multiple tabs. Switch between them from the sidebar.',
      position: 'right',
    },
    {
      id: 'filter-panel',
      target: 'filter-panel',
      route: /^\/dashboard-beta\//,
      title: 'Filter the data',
      body: 'Use these interactive controls to narrow what every chart, card, and table shows. Selections propagate across the entire dashboard.',
      position: 'right',
    },
    {
      id: 'realtime',
      target: 'realtime-indicator',
      route: /^\/dashboard-beta\//,
      title: 'Live updates',
      body: "When upstream data changes, this pill lights up. Open Settings to switch on auto-refresh, or click to refresh manually.",
      position: 'bottom',
    },
    {
      id: 'done',
      target: null,
      title: "You're all set",
      body: "That's the tour. Keep exploring at your own pace — you can re-launch it any time from the user menu.",
      position: 'bottom',
    },
  ],
};
